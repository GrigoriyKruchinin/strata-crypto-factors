"""Convert target weights into exchange-valid order quantities (Decimal)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from strata.domain.models import Instrument, InstrumentStatus, OrderRequest, Side, Symbol


@dataclass
class SizingResult:
    orders: list[OrderRequest]
    target_quantities: dict[Symbol, Decimal]
    dropped: list[Symbol] = field(default_factory=list)  # below exchange minimums


def default_instrument(symbol: Symbol) -> Instrument:
    """Conservative filters when exchange metadata is missing."""
    return Instrument(
        symbol=symbol,
        base_asset=symbol.removesuffix("USDT"),
        quote_asset="USDT",
        status=InstrumentStatus.TRADING,
        onboard_time=None,
        min_notional=Decimal(20),
    )


def size_orders(
    weights: Mapping[Symbol, Decimal],
    current: Mapping[Symbol, Decimal],
    prices: Mapping[Symbol, Decimal],
    equity: Decimal,
    *,
    instruments: Mapping[Symbol, Instrument],
    order_prefix: str,
) -> SizingResult:
    """Target quantity = weight * equity / price, rounded toward zero to the step size.

    Positions whose target notional is below ``minNotional`` are dropped (target 0), which
    turns a large theoretical book into the compact book a small account can hold. Closing
    orders are always allowed (reduce-only orders are exempt from ``minNotional``).
    """
    targets: dict[Symbol, Decimal] = {}
    dropped: list[Symbol] = []
    for symbol, weight in weights.items():
        price = prices.get(symbol)
        if price is None or price <= 0 or weight == 0:
            continue
        inst = instruments.get(symbol) or default_instrument(symbol)
        qty = inst.round_qty(weight * equity / price)
        if not inst.is_tradeable_qty(qty, price):
            dropped.append(symbol)
            continue
        targets[symbol] = qty

    orders: list[OrderRequest] = []
    for symbol in sorted(set(targets) | {s for s, q in current.items() if q != 0}):
        target = targets.get(symbol, Decimal(0))
        delta = target - current.get(symbol, Decimal(0))
        if delta == 0:
            continue
        inst = instruments.get(symbol) or default_instrument(symbol)
        price = prices.get(symbol)
        closing = target == 0
        if price is None:
            continue
        if not closing and not inst.is_tradeable_qty(delta, price):
            continue  # adjustment too small to trade; keep the current position
        orders.append(
            OrderRequest(
                symbol=symbol,
                side=Side.BUY if delta > 0 else Side.SELL,
                quantity=abs(delta),
                client_order_id=f"{order_prefix}-{symbol}"[:36],
                reduce_only=closing,
            )
        )
    return SizingResult(orders, targets, dropped)
