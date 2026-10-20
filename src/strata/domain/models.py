"""Exchange-agnostic domain entities.

Money and quantities are ``Decimal`` here: these types flow into accounting and execution.
Timestamps are always timezone-aware UTC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from enum import StrEnum

Symbol = str


def utc(dt: datetime) -> datetime:
    """Return ``dt`` as aware UTC; naive input is interpreted as UTC."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class InstrumentStatus(StrEnum):
    TRADING = "TRADING"
    SETTLING = "SETTLING"
    DELISTED = "DELISTED"
    PENDING = "PENDING"


@dataclass(frozen=True, slots=True)
class Instrument:
    """A perpetual contract with its trading filters and lifecycle dates."""

    symbol: Symbol
    base_asset: str
    quote_asset: str
    status: InstrumentStatus
    onboard_time: datetime | None
    delist_time: datetime | None = None
    tick_size: Decimal = Decimal("0.0001")
    step_size: Decimal = Decimal("0.001")
    min_qty: Decimal = Decimal("0.001")
    min_notional: Decimal = Decimal(5)

    def round_price(self, price: Decimal) -> Decimal:
        return round_to_increment(price, self.tick_size, ROUND_HALF_EVEN)

    def round_qty(self, qty: Decimal) -> Decimal:
        """Round quantity toward zero to the step size (never overshoot the target)."""
        return round_to_increment(qty, self.step_size, ROUND_DOWN)

    def is_tradeable_qty(self, qty: Decimal, price: Decimal) -> bool:
        q = abs(qty)
        return q >= self.min_qty and q * price >= self.min_notional


def round_to_increment(value: Decimal, increment: Decimal, rounding: str) -> Decimal:
    if increment <= 0:
        raise ValueError("increment must be positive")
    units = (value / increment).to_integral_value(rounding=rounding)
    return (units * increment).quantize(increment)


@dataclass(frozen=True, slots=True)
class Candle:
    """OHLCV bar; ``open_time`` is the bar start. The bar is known only after its close."""

    symbol: Symbol
    interval: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    trades: int = 0


@dataclass(frozen=True, slots=True)
class FundingRate:
    """A settled funding event. Positive rate: longs pay shorts."""

    symbol: Symbol
    funding_time: datetime
    rate: Decimal
    mark_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class OrderRequest:
    symbol: Symbol
    side: Side
    quantity: Decimal
    client_order_id: str
    limit_price: Decimal | None = None
    reduce_only: bool = False


@dataclass(frozen=True, slots=True)
class Fill:
    symbol: Symbol
    side: Side
    quantity: Decimal
    price: Decimal
    fee: Decimal
    slippage_cost: Decimal
    client_order_id: str
    filled_at: datetime


@dataclass(slots=True)
class Position:
    """Signed position: positive quantity is long, negative is short."""

    symbol: Symbol
    quantity: Decimal = Decimal(0)
    entry_price: Decimal = Decimal(0)

    def notional(self, mark: Decimal) -> Decimal:
        return self.quantity * mark


@dataclass(frozen=True, slots=True)
class AccountState:
    equity: Decimal
    positions: dict[Symbol, Position] = field(default_factory=dict)
    as_of: datetime = field(default_factory=lambda: datetime.now(UTC))
