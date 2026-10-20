"""Copy research data into the database (incremental, idempotent).

Parquet stays the fast research store; the database is the system of record for the running
system and later dashboards: candles, funding, experiments, universe and factor snapshots.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from strata.data.store import ParquetStore, Table
from strata.infra.db import CandleRow, ExperimentRow, FactorValueRow, FundingRow, UniverseRow
from strata.research.experiment_log import IExperimentLog

logger = logging.getLogger(__name__)

BATCH = 5000


def _utc(value: object) -> pd.Timestamp:
    """SQLite returns naive datetimes; PostgreSQL returns aware ones. Both are UTC."""
    ts = pd.Timestamp(value)  # type: ignore[arg-type]
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _dec(value: float) -> Decimal:
    return Decimal(repr(float(value)))


async def _insert_ignore(
    session: AsyncSession, model: type[DeclarativeBase], rows: Sequence[dict[str, Any]]
) -> None:
    """Bulk insert, skipping rows whose primary key already exists."""
    if not rows:
        return
    dialect = session.get_bind().dialect.name
    insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
    for i in range(0, len(rows), BATCH):
        stmt = insert(model).values(list(rows[i : i + BATCH])).on_conflict_do_nothing()
        await session.execute(stmt)


async def ingest_market(sessions: async_sessionmaker[AsyncSession], store: ParquetStore) -> int:
    """Insert candles/funding newer than what the database already holds per symbol."""
    inserted = 0
    async with sessions() as session:
        last_candle = dict(
            (
                await session.execute(
                    select(CandleRow.symbol, func.max(CandleRow.open_time)).group_by(
                        CandleRow.symbol
                    )
                )
            )
            .tuples()
            .all()
        )
        last_funding = dict(
            (
                await session.execute(
                    select(FundingRow.symbol, func.max(FundingRow.funding_time)).group_by(
                        FundingRow.symbol
                    )
                )
            )
            .tuples()
            .all()
        )
    for symbol in store.symbols(Table.KLINES_1D):
        klines = store.read_table(Table.KLINES_1D, symbol)
        funding = store.read_table(Table.FUNDING, symbol)
        candle_rows: list[dict[str, Any]] = []
        if klines is not None:
            since = last_candle.get(symbol)
            if since is not None:
                klines = klines.loc[klines["open_time"] > _utc(since)]
            candle_rows = [
                {
                    "symbol": symbol,
                    "interval": "1d",
                    "open_time": pd.Timestamp(r["open_time"]).to_pydatetime(),
                    "open": _dec(r["open"]),
                    "high": _dec(r["high"]),
                    "low": _dec(r["low"]),
                    "close": _dec(r["close"]),
                    "volume": _dec(r["volume"]),
                    "quote_volume": _dec(r["quote_volume"]),
                    "trades": int(r["trades"]),
                }
                for r in klines.to_dict("records")
            ]
        funding_rows: list[dict[str, Any]] = []
        if funding is not None:
            since_f = last_funding.get(symbol)
            if since_f is not None:
                funding = funding.loc[funding["funding_time"] > _utc(since_f)]
            funding_rows = [
                {
                    "symbol": symbol,
                    "funding_time": pd.Timestamp(r["funding_time"]).to_pydatetime(),
                    "rate": _dec(r["rate"]),
                }
                for r in funding.to_dict("records")
            ]
        if candle_rows or funding_rows:
            async with sessions() as session, session.begin():
                await _insert_ignore(session, CandleRow, candle_rows)
                await _insert_ignore(session, FundingRow, funding_rows)
            inserted += len(candle_rows) + len(funding_rows)
    logger.info("ingested %d market rows", inserted)
    return inserted


async def ingest_experiments(
    sessions: async_sessionmaker[AsyncSession], log: IExperimentLog
) -> int:
    rows = [asdict(r) for r in log.records()]
    async with sessions() as session, session.begin():
        await _insert_ignore(session, ExperimentRow, rows)
    return len(rows)


async def record_signal(
    sessions: async_sessionmaker[AsyncSession],
    *,
    strategy: str,
    signal_date: date,
    universe_adv: pd.Series,
    factor_scores: dict[str, pd.Series],
) -> None:
    """Persist the point-in-time universe and factor values behind one rebalance."""
    universe_rows = [
        {
            "strategy": strategy,
            "signal_date": signal_date,
            "symbol": str(s),
            "avg_quote_volume": float(v),
        }
        for s, v in universe_adv.dropna().to_dict().items()
    ]
    factor_rows = [
        {"signal_date": signal_date, "symbol": str(s), "factor": name, "value": float(v)}
        for name, series in factor_scores.items()
        for s, v in series.dropna().to_dict().items()
    ]
    async with sessions() as session, session.begin():
        await _insert_ignore(session, UniverseRow, universe_rows)
        await _insert_ignore(session, FactorValueRow, factor_rows)
