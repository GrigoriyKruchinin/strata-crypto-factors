"""History loader: survivorship-free daily klines and funding for all USDT-M perpetuals.

Monthly archives from data.binance.vision are cached on disk (the cache doubles as the resume
checkpoint); the current, not-yet-archived month is filled from the public REST API.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd

from strata.data.binance_rest import BinanceUsdmAdapter, is_crypto_perpetual, parse_instrument
from strata.data.binance_vision import BinanceVisionClient, MonthlyFile, VisionDataset
from strata.data.parsing import empty_funding, empty_klines, parse_funding_zip, parse_kline_zip
from strata.data.quality import QualityReport, check_symbol
from strata.data.store import ParquetStore, Table
from strata.domain.models import InstrumentStatus

logger = logging.getLogger(__name__)

ONE_DAY = timedelta(days=1)
#: A symbol whose last bar is older than this (relative to the run date) is treated as delisted.
DELIST_STALENESS = timedelta(days=3)


@dataclass
class LoadResult:
    symbols: int = 0
    downloaded_files: int = 0
    cached_files: int = 0
    failed: dict[str, str] = field(default_factory=dict)
    quality: QualityReport = field(default_factory=QualityReport)


def is_candidate_symbol(symbol: str, quote: str = "USDT") -> bool:
    return symbol.endswith(quote) and "_" not in symbol


class HistoryLoader:
    def __init__(
        self,
        vision: BinanceVisionClient,
        rest: BinanceUsdmAdapter | None,
        store: ParquetStore,
        *,
        history_start: date,
        quote_asset: str = "USDT",
        concurrency: int = 8,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._vision = vision
        self._rest = rest
        self._store = store
        self._start = history_start
        self._quote = quote_asset
        self._sem = asyncio.Semaphore(concurrency)
        self._now = now

    # ------------------------------------------------------------------ public API
    async def run(self, only: Iterable[str] | None = None) -> LoadResult:
        result = LoadResult()
        exchange_raw = await self._exchange_info()
        excluded = {str(s["symbol"]) for s in exchange_raw if not is_crypto_perpetual(s)}
        vision_symbols = await self._vision.list_symbols(VisionDataset.KLINES)
        live_symbols = {str(s["symbol"]) for s in exchange_raw if is_crypto_perpetual(s)}
        symbols = sorted(
            s
            for s in set(vision_symbols) | live_symbols
            if is_candidate_symbol(s, self._quote) and s not in excluded
        )
        if only is not None:
            wanted = set(only)
            symbols = [s for s in symbols if s in wanted]
        logger.info("loading %d symbols", len(symbols))

        trading = {
            str(s["symbol"])
            for s in exchange_raw
            if is_crypto_perpetual(s) and s.get("status") == InstrumentStatus.TRADING.value
        }
        await asyncio.gather(*(self._load_symbol(s, s in trading, result) for s in symbols))
        result.symbols = len(symbols) - len(result.failed)
        self._store.write_instruments(self._instrument_table(symbols, exchange_raw))
        self._store.write_manifest(
            {
                "updated_at": self._now().isoformat(),
                "history_start": self._start.isoformat(),
                "symbols": result.symbols,
                "data_version": self._store.data_version(),
                "failed": result.failed,
            }
        )
        return result

    # ------------------------------------------------------------------ internals
    async def _exchange_info(self) -> list[dict[str, Any]]:
        if self._rest is None:
            return []
        try:
            return await self._rest.exchange_info()
        except Exception:  # REST may be geo-blocked; the archive alone is still usable
            logger.exception("exchangeInfo unavailable; continuing with archive data only")
            return []

    def _wanted(self, files: list[MonthlyFile]) -> list[MonthlyFile]:
        first = (self._start.year, self._start.month)
        return [f for f in files if (f.year, f.month) >= first]

    async def _fetch_month(self, file: MonthlyFile, result: LoadResult) -> bytes:
        cached = self._store.read_raw(file.dataset.value, file.symbol, file.period)
        if cached is not None:
            result.cached_files += 1
            return cached
        async with self._sem:
            payload = await self._vision.download_verified(file.url)
        self._store.write_raw(file.dataset.value, file.symbol, file.period, payload)
        result.downloaded_files += 1
        return payload

    async def _archive_frames(
        self, symbol: str, result: LoadResult
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        async with self._sem:
            kline_files = self._wanted(
                await self._vision.list_monthly_files(symbol, VisionDataset.KLINES)
            )
            funding_files = self._wanted(
                await self._vision.list_monthly_files(symbol, VisionDataset.FUNDING)
            )
        kline_payloads = await asyncio.gather(*(self._fetch_month(f, result) for f in kline_files))
        funding_payloads = await asyncio.gather(
            *(self._fetch_month(f, result) for f in funding_files)
        )
        klines = pd.concat(
            [empty_klines(), *(parse_kline_zip(p) for p in kline_payloads)], ignore_index=True
        )
        funding = pd.concat(
            [empty_funding(), *(parse_funding_zip(p) for p in funding_payloads)],
            ignore_index=True,
        )
        return klines, funding

    async def _rest_tail(
        self, symbol: str, klines: pd.DataFrame, funding: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        if self._rest is None:
            return klines, funding
        start = datetime(self._start.year, self._start.month, self._start.day, tzinfo=UTC)
        end = self._now().astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        k_from = klines["open_time"].max() + ONE_DAY if len(klines) else start
        f_from = funding["funding_time"].max() + timedelta(minutes=1) if len(funding) else start
        async with self._sem:
            tail_k = await self._rest.fetch_kline_frame(symbol, "1d", _py(k_from), end)
            tail_f = await self._rest.fetch_funding_frame(symbol, _py(f_from), self._now())
        return (
            pd.concat([klines, tail_k], ignore_index=True),
            pd.concat([funding, tail_f], ignore_index=True),
        )

    async def _load_symbol(self, symbol: str, trading: bool, result: LoadResult) -> None:
        try:
            klines, funding = await self._archive_frames(symbol, result)
            if trading:
                klines, funding = await self._rest_tail(symbol, klines, funding)
            klines = (
                klines.sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
            )
            funding = (
                funding.sort_values("funding_time")
                .drop_duplicates("funding_time")
                .reset_index(drop=True)
            )
            if klines.empty:
                logger.info("%s: no klines since %s, skipped", symbol, self._start)
                return
            self._store.write_table(Table.KLINES_1D, symbol, klines)
            self._store.write_table(Table.FUNDING, symbol, funding)
            result.quality.add(check_symbol(symbol, klines, funding))
        except Exception as exc:
            logger.exception("%s: load failed", symbol)
            result.failed[symbol] = f"{type(exc).__name__}: {exc}"

    def _instrument_table(
        self, symbols: list[str], exchange_raw: list[dict[str, Any]]
    ) -> pd.DataFrame:
        info = {str(s["symbol"]): s for s in exchange_raw}
        now = self._now().astimezone(UTC)
        rows: list[dict[str, Any]] = []
        for symbol in symbols:
            klines = self._store.read_table(Table.KLINES_1D, symbol)
            if klines is None or klines.empty:
                continue
            traded = klines.loc[klines["quote_volume"] > 0, "open_time"]
            if traded.empty:
                continue
            first_bar = traded.min().to_pydatetime()
            last_bar = traded.max().to_pydatetime()
            raw = info.get(symbol)
            if raw is not None:
                inst = parse_instrument(raw)
                status = inst.status.value
                delist = inst.delist_time
                onboard = inst.onboard_time or first_bar
                tick: Decimal | None = inst.tick_size
                step: Decimal | None = inst.step_size
                notional: Decimal | None = inst.min_notional
            else:
                stale = now - (last_bar + ONE_DAY) > DELIST_STALENESS
                status = (
                    InstrumentStatus.DELISTED.value if stale else InstrumentStatus.PENDING.value
                )
                delist = last_bar + ONE_DAY if stale else None
                onboard = first_bar
                tick = step = notional = None
            rows.append(
                {
                    "symbol": symbol,
                    "status": status,
                    "onboard_time": onboard,
                    "delist_time": delist,
                    "first_bar": first_bar,
                    "last_bar": last_bar,
                    "tick_size": str(tick) if tick is not None else None,
                    "step_size": str(step) if step is not None else None,
                    "min_notional": str(notional) if notional is not None else None,
                }
            )
        frame = pd.DataFrame(rows)
        for col in ("onboard_time", "delist_time", "first_bar", "last_bar"):
            if col in frame:
                frame[col] = pd.to_datetime(frame[col], utc=True)
        return frame


def _py(ts: pd.Timestamp | datetime) -> datetime:
    return ts.to_pydatetime() if isinstance(ts, pd.Timestamp) else ts
