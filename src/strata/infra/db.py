"""SQLAlchemy models (PostgreSQL in deployment, SQLite in tests) and session factory."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

PRICE = Numeric(38, 18)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSON}


class InstrumentRow(Base):
    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(40), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    onboard_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delist_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tick_size: Mapped[Decimal | None] = mapped_column(PRICE)
    step_size: Mapped[Decimal | None] = mapped_column(PRICE)
    min_notional: Mapped[Decimal | None] = mapped_column(PRICE)


class CandleRow(Base):
    __tablename__ = "candles"

    symbol: Mapped[str] = mapped_column(String(40), primary_key=True)
    interval: Mapped[str] = mapped_column(String(4), primary_key=True)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    open: Mapped[Decimal] = mapped_column(PRICE)
    high: Mapped[Decimal] = mapped_column(PRICE)
    low: Mapped[Decimal] = mapped_column(PRICE)
    close: Mapped[Decimal] = mapped_column(PRICE)
    volume: Mapped[Decimal] = mapped_column(PRICE)
    quote_volume: Mapped[Decimal] = mapped_column(PRICE)
    trades: Mapped[int] = mapped_column(BigInteger, default=0)


class FundingRow(Base):
    __tablename__ = "funding_rates"

    symbol: Mapped[str] = mapped_column(String(40), primary_key=True)
    funding_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    rate: Mapped[Decimal] = mapped_column(PRICE)


class UniverseRow(Base):
    __tablename__ = "universe_snapshots"

    strategy: Mapped[str] = mapped_column(String(80), primary_key=True)
    signal_date: Mapped[date] = mapped_column(Date, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), primary_key=True)
    avg_quote_volume: Mapped[float] = mapped_column(Float)


class FactorValueRow(Base):
    __tablename__ = "factor_values"

    signal_date: Mapped[date] = mapped_column(Date, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), primary_key=True)
    factor: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[float] = mapped_column(Float)


class TargetPortfolioRow(Base):
    __tablename__ = "target_portfolios"
    __table_args__ = (UniqueConstraint("account", "signal_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account: Mapped[str] = mapped_column(String(40))
    strategy: Mapped[str] = mapped_column(String(80))
    signal_date: Mapped[date] = mapped_column(Date)
    weights: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PositionRow(Base):
    __tablename__ = "positions"

    account: Mapped[str] = mapped_column(String(40), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(PRICE)
    entry_price: Mapped[Decimal] = mapped_column(PRICE)


class AccountRow(Base):
    __tablename__ = "accounts"

    account: Mapped[str] = mapped_column(String(40), primary_key=True)
    cash: Mapped[Decimal] = mapped_column(PRICE)
    initial_equity: Mapped[Decimal] = mapped_column(PRICE)
    started_on: Mapped[date] = mapped_column(Date)
    last_processed: Mapped[date | None] = mapped_column(Date)


class TradeRow(Base):
    __tablename__ = "trades"

    client_order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account: Mapped[str] = mapped_column(String(40))
    symbol: Mapped[str] = mapped_column(String(40))
    side: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[Decimal] = mapped_column(PRICE)
    price: Mapped[Decimal] = mapped_column(PRICE)
    fee: Mapped[Decimal] = mapped_column(PRICE)
    slippage_cost: Mapped[Decimal] = mapped_column(PRICE)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EquityRow(Base):
    __tablename__ = "equity_curve"

    account: Mapped[str] = mapped_column(String(40), primary_key=True)
    bar_date: Mapped[date] = mapped_column(Date, primary_key=True)
    equity: Mapped[Decimal] = mapped_column(PRICE)
    funding: Mapped[Decimal] = mapped_column(PRICE)
    costs: Mapped[Decimal] = mapped_column(PRICE)
    gross_exposure: Mapped[Decimal] = mapped_column(PRICE)


class ExperimentRow(Base):
    __tablename__ = "experiments"

    record_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    spec_id: Mapped[str] = mapped_column(String(32), index=True)
    spec_name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))
    period_label: Mapped[str] = mapped_column(String(40))
    period_start: Mapped[str] = mapped_column(String(10))
    period_end: Mapped[str] = mapped_column(String(10))
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    data_version: Mapped[str] = mapped_column(String(32))
    code_version: Mapped[str] = mapped_column(String(32))
    notes: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[str] = mapped_column(String(40))


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
