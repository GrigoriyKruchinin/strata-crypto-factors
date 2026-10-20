"""Binance USDT-M futures public REST adapter (no API keys required)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pandas as pd

from strata.data.http import RateLimiter, get_with_retry
from strata.data.parsing import parse_funding_rows, parse_kline_rows
from strata.domain.interfaces import BaseExchangeAdapter
from strata.domain.models import Candle, FundingRate, Instrument, InstrumentStatus, Symbol, utc

_INTERVAL_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
_FAR_FUTURE_MS = 4_000_000_000_000  # Binance uses ~2100-12-25 as "no delivery" for perps
KLINE_LIMIT = 1500
FUNDING_LIMIT = 1000


def _kline_weight(limit: int) -> int:
    if limit < 100:
        return 1
    if limit < 500:
        return 2
    if limit <= 1000:
        return 5
    return 10


def _ms(dt: datetime) -> int:
    return int(utc(dt).timestamp() * 1000)


def _filter(filters: list[dict[str, Any]], kind: str, key: str, default: str) -> Decimal:
    for f in filters:
        if f.get("filterType") == kind and key in f:
            return Decimal(str(f[key]))
    return Decimal(default)


def parse_instrument(raw: dict[str, Any]) -> Instrument:
    filters: list[dict[str, Any]] = raw.get("filters", [])
    onboard_ms = int(raw.get("onboardDate", 0))
    delivery_ms = int(raw.get("deliveryDate", 0))
    status_raw = str(raw.get("status", "TRADING"))
    status = (
        InstrumentStatus(status_raw)
        if status_raw in InstrumentStatus.__members__
        else InstrumentStatus.PENDING
    )
    delist = (
        datetime.fromtimestamp(delivery_ms / 1000, tz=UTC)
        if 0 < delivery_ms < _FAR_FUTURE_MS
        else None
    )
    return Instrument(
        symbol=str(raw["symbol"]),
        base_asset=str(raw.get("baseAsset", "")),
        quote_asset=str(raw.get("quoteAsset", "")),
        status=status,
        onboard_time=datetime.fromtimestamp(onboard_ms / 1000, tz=UTC) if onboard_ms else None,
        delist_time=delist,
        tick_size=_filter(filters, "PRICE_FILTER", "tickSize", "0.0001"),
        step_size=_filter(filters, "LOT_SIZE", "stepSize", "0.001"),
        min_qty=_filter(filters, "LOT_SIZE", "minQty", "0.001"),
        min_notional=_filter(filters, "MIN_NOTIONAL", "notional", "5"),
    )


def is_crypto_perpetual(raw: dict[str, Any]) -> bool:
    """USDT-margined perpetual on a crypto underlying (excludes TradFi/equity contracts)."""
    return (
        raw.get("contractType") == "PERPETUAL"
        and raw.get("quoteAsset") == "USDT"
        and raw.get("underlyingType", "COIN") == "COIN"
    )


class BinanceUsdmAdapter(BaseExchangeAdapter):
    name = "binance_usdm"

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str = "https://fapi.binance.com",
        weight_per_minute: int = 1200,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._limiter = RateLimiter(weight_per_minute)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None, weight: int) -> Any:
        await self._limiter.acquire(weight)
        response = await get_with_retry(self._client, f"{self._base_url}{path}", params=params)
        return response.json()

    async def exchange_info(self) -> list[dict[str, Any]]:
        data = await self._get("/fapi/v1/exchangeInfo", None, 1)
        symbols: list[dict[str, Any]] = data["symbols"]
        return symbols

    async def list_instruments(self) -> list[Instrument]:
        return [parse_instrument(s) for s in await self.exchange_info() if is_crypto_perpetual(s)]

    async def fetch_kline_frame(
        self, symbol: Symbol, interval: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Closed bars with ``start <= open_time`` and ``close_time < end``."""
        step = _INTERVAL_MS[interval]
        cursor, end_ms = _ms(start), _ms(end)
        frames: list[pd.DataFrame] = []
        while cursor + step <= end_ms:
            rows = await self._get(
                "/fapi/v1/klines",
                {
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms - 1,
                    "limit": KLINE_LIMIT,
                },
                _kline_weight(KLINE_LIMIT),
            )
            if not rows:
                break
            frame = parse_kline_rows(rows)
            frames.append(frame)
            last_open = int(rows[-1][0])
            if len(rows) < KLINE_LIMIT:
                break
            cursor = last_open + step
        if not frames:
            return parse_kline_rows([])
        out = pd.concat(frames, ignore_index=True).drop_duplicates("open_time")
        closed = out["open_time"] + pd.Timedelta(milliseconds=step) <= pd.Timestamp(
            end_ms, unit="ms", tz="UTC"
        )
        return out.loc[closed].reset_index(drop=True)

    async def fetch_funding_frame(
        self, symbol: Symbol, start: datetime, end: datetime
    ) -> pd.DataFrame:
        cursor, end_ms = _ms(start), _ms(end)
        frames: list[pd.DataFrame] = []
        while cursor < end_ms:
            rows = await self._get(
                "/fapi/v1/fundingRate",
                {"symbol": symbol, "startTime": cursor, "endTime": end_ms, "limit": FUNDING_LIMIT},
                # The endpoint shares a 500 req / 5 min IP budget; charge it conservatively.
                5,
            )
            if not rows:
                break
            frames.append(parse_funding_rows(rows))
            if len(rows) < FUNDING_LIMIT:
                break
            cursor = int(rows[-1]["fundingTime"]) + 1
        if not frames:
            return parse_funding_rows([])
        return pd.concat(frames, ignore_index=True).drop_duplicates("funding_time")

    async def fetch_candles(
        self, symbol: Symbol, interval: str, start: datetime, end: datetime
    ) -> list[Candle]:
        frame = await self.fetch_kline_frame(symbol, interval, start, end)
        return [
            Candle(
                symbol=symbol,
                interval=interval,
                open_time=pd.Timestamp(r["open_time"]).to_pydatetime(),
                open=Decimal(str(r["open"])),
                high=Decimal(str(r["high"])),
                low=Decimal(str(r["low"])),
                close=Decimal(str(r["close"])),
                volume=Decimal(str(r["volume"])),
                quote_volume=Decimal(str(r["quote_volume"])),
                trades=int(r["trades"]),
            )
            for r in frame.to_dict("records")
        ]

    async def fetch_funding_rates(
        self, symbol: Symbol, start: datetime, end: datetime
    ) -> list[FundingRate]:
        frame = await self.fetch_funding_frame(symbol, start, end)
        return [
            FundingRate(
                symbol=symbol,
                funding_time=pd.Timestamp(r["funding_time"]).to_pydatetime(),
                rate=Decimal(str(r["rate"])),
            )
            for r in frame.to_dict("records")
        ]


def last_closed_daily_bar_end(now: datetime | None = None) -> datetime:
    """Midnight UTC of today: every daily bar opening before it is closed."""
    current = utc(now or datetime.now(UTC))
    return current.replace(hour=0, minute=0, second=0, microsecond=0)
