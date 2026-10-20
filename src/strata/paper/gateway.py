"""Simulated order gateway: fills at the reference mark price adjusted by the cost model."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from strata.domain.interfaces import ICostModel, IOrderGateway
from strata.domain.models import AccountState, Fill, OrderRequest, Position, Side, Symbol


class SimulatedGateway(IOrderGateway):
    """Linear-perpetual accounting: equity = cash + sum(qty * mark).

    Buying ``q`` at ``p`` moves ``q * p`` out of cash (shorting moves it in); fees, slippage
    and funding are debited from cash.
    """

    def __init__(
        self,
        cash: Decimal,
        positions: Mapping[Symbol, Position],
        cost_model: ICostModel,
    ) -> None:
        self.cash = cash
        self.positions: dict[Symbol, Position] = {s: p for s, p in positions.items() if p.quantity}
        self.cost_model = cost_model
        self.marks: dict[Symbol, Decimal] = {}
        self.adv: dict[Symbol, Decimal] = {}
        self.now: datetime | None = None

    def set_market(
        self, marks: Mapping[Symbol, Decimal], adv: Mapping[Symbol, Decimal], now: datetime
    ) -> None:
        self.marks = dict(marks)
        self.adv = dict(adv)
        self.now = now

    def equity(self) -> Decimal:
        value = sum(
            (p.quantity * self.marks.get(s, p.entry_price) for s, p in self.positions.items()),
            Decimal(0),
        )
        return self.cash + value

    async def account(self) -> AccountState:
        kwargs = {"as_of": self.now} if self.now is not None else {}
        return AccountState(equity=self.equity(), positions=dict(self.positions), **kwargs)

    def apply_funding(self, rates: Mapping[Symbol, Decimal]) -> Decimal:
        """Debit funding for current positions; returns the PnL (negative = paid)."""
        pnl = Decimal(0)
        for symbol, pos in self.positions.items():
            rate = rates.get(symbol)
            mark = self.marks.get(symbol)
            if rate is None or mark is None:
                continue
            pnl -= pos.quantity * mark * rate
        self.cash += pnl
        return pnl

    async def submit(self, orders: Sequence[OrderRequest]) -> list[Fill]:
        if self.now is None:
            raise RuntimeError("set_market() before submitting orders")
        fills: list[Fill] = []
        for order in orders:
            mark = self.marks.get(order.symbol)
            if mark is None:
                continue  # no price: order rejected
            notional = order.quantity * mark
            est = self.cost_model.estimate_fill(notional, self.adv.get(order.symbol, Decimal(0)))
            slip_per_unit = est.slippage / order.quantity
            sign = Decimal(1) if order.side is Side.BUY else Decimal(-1)
            price = mark + sign * slip_per_unit
            signed_qty = sign * order.quantity
            self.cash -= signed_qty * price + est.fee
            pos = self.positions.get(order.symbol) or Position(order.symbol)
            new_qty = pos.quantity + signed_qty
            if new_qty == 0:
                self.positions.pop(order.symbol, None)
            else:
                same_direction = pos.quantity == 0 or (pos.quantity > 0) == (signed_qty > 0)
                if same_direction:
                    pos.entry_price = (
                        pos.quantity * pos.entry_price + signed_qty * price
                    ) / new_qty
                elif (new_qty > 0) != (pos.quantity > 0):
                    pos.entry_price = price  # flipped side
                pos.quantity = new_qty
                self.positions[order.symbol] = pos
            fills.append(
                Fill(
                    symbol=order.symbol,
                    side=order.side,
                    quantity=order.quantity,
                    price=price,
                    fee=est.fee,
                    slippage_cost=est.slippage,
                    client_order_id=order.client_order_id,
                    filled_at=self.now,
                )
            )
        return fills
