"""Composition root: wires settings into concrete components (DIP).

Each process builds only what its role needs, so e.g. the notifier role never sees DB
credentials and the data role never sees the Telegram token.
"""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strata.config import DatabaseSettings, DataSettings, ExchangeSettings, PaperSettings
from strata.data.binance_rest import BinanceUsdmAdapter
from strata.data.binance_vision import BinanceVisionClient
from strata.data.loader import HistoryLoader
from strata.data.panel_builder import build_panel
from strata.data.store import ParquetStore
from strata.domain.models import Instrument, InstrumentStatus
from strata.domain.panel import MarketPanel
from strata.infra.db import make_engine, make_sessionmaker
from strata.paper.repository import SqlPaperRepository
from strata.paper.trader import PaperTrader
from strata.research.grid import candidate_grid
from strata.research.spec import StrategySpec


def store(settings: DataSettings | None = None) -> ParquetStore:
    return ParquetStore((settings or DataSettings()).root_dir)


def history_loader(vision_http: httpx.AsyncClient, rest_http: httpx.AsyncClient) -> HistoryLoader:
    data = DataSettings()
    exchange = ExchangeSettings()
    return HistoryLoader(
        BinanceVisionClient(vision_http, exchange.vision_base_url),
        BinanceUsdmAdapter(rest_http, exchange.rest_base_url, exchange.max_requests_per_minute),
        store(data),
        history_start=data.history_start,
        quote_asset=data.quote_asset,
        concurrency=data.download_concurrency,
    )


def paper_strategy(settings: PaperSettings) -> StrategySpec:
    """Primary frozen candidate at its train-derived leverage."""
    path = settings.frozen_candidates_path
    if not path.exists():
        raise RuntimeError(
            f"{path} not found: run `strata research train` and `strata research freeze` first"
        )
    details = json.loads(path.read_text())["details"]
    spec_id: str = details["primary"]
    leverage = float(details["primary_leverage"])
    base = next((s for s in candidate_grid() if s.spec_id == spec_id), None)
    if base is None:
        raise RuntimeError(f"frozen primary {spec_id} is not in the candidate grid")
    return base.model_copy(
        update={
            "gross_leverage": leverage,
            "initial_equity": float(settings.initial_equity),
            "name": f"{base.name}@{leverage:.2f}x",
        }
    )


def instruments(st: ParquetStore) -> dict[str, Instrument]:
    if not st.instruments_path.exists():
        return {}
    out: dict[str, Instrument] = {}
    for row in st.read_instruments().to_dict("records"):
        if row.get("step_size") is None or pd.isna(row.get("step_size")):
            continue
        status = str(row["status"])
        out[str(row["symbol"])] = Instrument(
            symbol=str(row["symbol"]),
            base_asset=str(row["symbol"]).removesuffix("USDT"),
            quote_asset="USDT",
            status=InstrumentStatus(status)
            if status in InstrumentStatus.__members__
            else InstrumentStatus.PENDING,
            onboard_time=None,
            tick_size=Decimal(str(row["tick_size"])),
            step_size=Decimal(str(row["step_size"])),
            min_qty=Decimal(str(row["step_size"])),
            min_notional=Decimal(str(row["min_notional"])),
        )
    return out


def paper_trader() -> tuple[PaperTrader, StrategySpec]:
    paper = PaperSettings()
    spec = paper_strategy(paper)
    st = store()
    sessions = make_sessionmaker(make_engine(DatabaseSettings().async_url))
    trader = PaperTrader(
        account=paper.account,
        strategy_name=spec.name,
        backtester=spec.build_backtester(),
        repository=SqlPaperRepository(sessions),
        panel_provider=lambda: build_panel(st),
        instruments=instruments(st),
        initial_equity=paper.initial_equity,
    )
    return trader, spec


def signal_snapshot(
    spec: StrategySpec, panel: MarketPanel, signal_date: pd.Timestamp
) -> tuple[pd.Series, dict[str, pd.Series]]:
    """Universe (with trailing ADV) and raw factor scores behind a rebalance at ``signal_date``."""
    view = panel.truncate(signal_date)
    universe = spec.build_universe()
    members = universe.membership(view).iloc[-1]
    adv = universe.average_volume(view).iloc[-1][members]
    scores = {f.name: f.compute(view).iloc[-1][members] for f in (x.build() for x in spec.factors)}
    return adv, scores


def sessions() -> async_sessionmaker[AsyncSession]:
    return make_sessionmaker(make_engine(DatabaseSettings().async_url))
