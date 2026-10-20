"""Paper trader: runs the research strategy on live public data with virtual orders.

Daily cycle at ``today 00:xx UTC`` processes every closed bar since the last run:

* positions held over bar ``b`` pay/receive the funding settled in ``(b, b+1]`` (marked at
  ``close[b]``), exactly as in the backtest;
* after the signal bar (Sunday close for weekly) the book is rebalanced at ``close[b]``
  (== the backtest's ``open[b+1]`` fill) with costs from the same cost model;
* contracts that stop trading are force-closed at their last close with maximum slippage.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pandas as pd

from strata.backtest.engine import Backtester, Rebalance
from strata.domain.models import Fill, Instrument, Position, Symbol
from strata.domain.panel import MarketPanel
from strata.paper.gateway import SimulatedGateway
from strata.paper.repository import AccountRecord, EquityPoint, IPaperRepository
from strata.paper.sizing import size_orders

logger = logging.getLogger(__name__)

ONE_DAY = timedelta(days=1)


class StaleDataError(RuntimeError):
    """The latest closed bar is missing: never trade on stale data."""


@dataclass
class CycleReport:
    account: str
    processed: list[date]
    equity: Decimal
    previous_equity: Decimal
    funding: Decimal
    costs: Decimal
    fills: list[Fill] = field(default_factory=list)
    target: dict[str, float] = field(default_factory=dict)
    signal_date: date | None = None
    dropped: list[Symbol] = field(default_factory=list)
    forced_exits: list[Symbol] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def rebalanced(self) -> bool:
        return self.signal_date is not None


def _dec(value: float) -> Decimal:
    return Decimal(repr(float(value)))


def _row(frame: pd.DataFrame, ts: pd.Timestamp) -> pd.Series:
    """Row ``ts`` of a date-indexed frame (``ts`` must exist)."""
    row: pd.Series = frame.iloc[int(frame.index.searchsorted(ts))]
    return row


def _decimals(series: pd.Series) -> dict[Symbol, Decimal]:
    """Non-NaN entries of a float Series as ``{symbol: Decimal}``."""
    return {str(k): _dec(float(v)) for k, v in series.dropna().to_dict().items()}


class PaperTrader:
    def __init__(
        self,
        *,
        account: str,
        strategy_name: str,
        backtester: Backtester,
        repository: IPaperRepository,
        panel_provider: Callable[[], MarketPanel],
        instruments: dict[Symbol, Instrument],
        initial_equity: Decimal = Decimal(3000),
    ) -> None:
        self.account = account
        self.strategy_name = strategy_name
        self.backtester = backtester
        self.repository = repository
        self.panel_provider = panel_provider
        self.instruments = instruments
        self.initial_equity = initial_equity

    def _is_signal(self, day: date) -> bool:
        cfg = self.backtester.config
        return cfg.rebalance is Rebalance.DAILY or day.weekday() == cfg.signal_weekday

    async def cycle(self, today: date) -> CycleReport:
        last_bar = today - ONE_DAY
        panel = self.panel_provider()
        last_ts = pd.Timestamp(last_bar, tz="UTC")
        if len(panel.dates) == 0 or panel.dates[-1] < last_ts:
            raise StaleDataError(
                f"latest bar {panel.dates[-1] if len(panel.dates) else None} < required {last_bar}"
            )
        panel = panel.truncate(last_ts)

        record = await self.repository.load_account(self.account)
        if record is None:
            record = AccountRecord(self.account, self.initial_equity, self.initial_equity, last_bar)
        positions = await self.repository.load_positions(self.account)
        start = record.last_processed + ONE_DAY if record.last_processed else last_bar
        bars = [d.date() for d in pd.date_range(start, last_bar, freq="D")]
        gateway = SimulatedGateway(record.cash, positions, self.backtester.cost_model)
        previous_equity = self._equity_at(gateway, panel, start - ONE_DAY)
        report = CycleReport(
            self.account, bars, previous_equity, previous_equity, Decimal(0), Decimal(0)
        )
        if not bars:
            report.warnings.append("nothing to process: cycle already ran for this bar")
            report.equity = previous_equity
            return report

        adv = panel.quote_volume.rolling(30, min_periods=1).mean()
        equity_points: list[EquityPoint] = []
        for bar in bars:
            ts = pd.Timestamp(bar, tz="UTC")
            self._set_market(gateway, panel, adv, ts)
            funding = gateway.apply_funding(_decimals(_row(panel.funding, ts)))
            report.funding += funding
            costs_before = report.costs
            report.forced_exits += await self._force_exit_dead(gateway, panel, ts, report)
            equity_points.append(self._point(gateway, bar, funding, report.costs - costs_before))

        signals = [b for b in bars if self._is_signal(b)]
        target_payload = None
        if signals:
            signal = signals[-1]
            if signal != bars[-1]:
                report.warnings.append(f"late rebalance: signal {signal} executed at {bars[-1]}")
            target = self.backtester.target_at(panel, pd.Timestamp(signal, tz="UTC"))
            report.signal_date = signal
            report.target = {str(k): float(v) for k, v in target.items()}
            prices = _decimals(panel.close.iloc[-1])
            sizing = size_orders(
                _decimals(target),
                {s: p.quantity for s, p in gateway.positions.items()},
                prices,
                gateway.equity(),
                instruments=self.instruments,
                order_prefix=f"{self.account}-{bars[-1]:%Y%m%d}",
            )
            report.dropped = sizing.dropped
            fills = await gateway.submit(sizing.orders)
            report.fills += fills
            trade_costs = sum((f.fee + f.slippage_cost for f in fills), Decimal(0))
            report.costs += trade_costs
            last = equity_points[-1]
            equity_points[-1] = self._point(
                gateway, bars[-1], last.funding, last.costs + trade_costs
            )
            target_payload = (self.strategy_name, signal, report.target)

        record.cash = gateway.cash
        record.last_processed = bars[-1]
        report.equity = gateway.equity()
        await self.repository.save_state(
            record, gateway.positions, report.fills, equity_points, target_payload
        )
        return report

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _set_market(
        gateway: SimulatedGateway, panel: MarketPanel, adv: pd.DataFrame, ts: pd.Timestamp
    ) -> None:
        history = panel.close.loc[:ts]
        marks = _decimals(history.ffill().iloc[-1])
        advs = _decimals(_row(adv, ts))
        now = datetime.combine(ts.date() + ONE_DAY, time(0, 5), tzinfo=UTC)
        gateway.set_market(marks, advs, now)

    async def _force_exit_dead(
        self, gateway: SimulatedGateway, panel: MarketPanel, ts: pd.Timestamp, report: CycleReport
    ) -> list[Symbol]:
        dead = [s for s in gateway.positions if pd.isna(panel.close.at[ts, s])]
        if not dead:
            return []
        # Same rule as the backtest: exit at the last close, sized against trailing ADV.
        current = {s: gateway.positions[s].quantity for s in dead}
        sizing = size_orders(
            {},
            current,
            {s: gateway.marks[s] for s in dead},
            gateway.equity(),
            instruments=self.instruments,
            order_prefix=f"{self.account}-{ts:%Y%m%d}-exit",
        )
        fills = await gateway.submit(sizing.orders)
        report.fills += fills
        report.costs += sum((f.fee + f.slippage_cost for f in fills), Decimal(0))
        report.warnings += [f"{s}: no bar on {ts.date()}, position force-closed" for s in dead]
        return dead

    @staticmethod
    def _point(
        gateway: SimulatedGateway, bar: date, funding: Decimal, costs: Decimal
    ) -> EquityPoint:
        gross = sum(
            (
                abs(p.quantity * gateway.marks.get(s, p.entry_price))
                for s, p in gateway.positions.items()
            ),
            Decimal(0),
        )
        return EquityPoint(bar, gateway.equity(), funding, costs, gross)

    @staticmethod
    def _equity_at(gateway: SimulatedGateway, panel: MarketPanel, bar: date) -> Decimal:
        ts = pd.Timestamp(bar, tz="UTC")
        history = panel.close.loc[:ts]
        if history.empty:
            return gateway.cash
        marks = history.ffill().iloc[-1].dropna()
        value = sum(
            (p.quantity * _dec(marks[s]) for s, p in gateway.positions.items() if s in marks),
            Decimal(0),
        )
        return gateway.cash + value


# ---------------------------------------------------------------------- reconciliation


@dataclass(frozen=True)
class Reconciliation:
    start: date
    end: date
    days: int
    paper_return: float
    backtest_return: float
    deviation: float  # |paper - backtest| / max(|backtest|, 1%)

    def within(self, tolerance: float) -> bool:
        return self.deviation <= tolerance


def reconcile(
    backtester: Backtester, panel: MarketPanel, curve: list[EquityPoint], initial: Decimal
) -> Reconciliation | None:
    """Compare the paper equity curve with a backtest over the same holding bars.

    Paper equity after bar ``b`` is marked at ``close[b]`` ~ ``open[b+1]``, i.e. the backtest's
    equity after holding bar ``b``; the last paper bar needs ``open[b+1]`` and is skipped.
    """
    if len(curve) < 2:
        return None
    start = pd.Timestamp(curve[0].bar_date, tz="UTC")
    end = min(pd.Timestamp(curve[-1].bar_date, tz="UTC"), panel.dates[-2])
    if end <= start:
        return None
    paper = {pd.Timestamp(p.bar_date, tz="UTC"): float(p.equity) for p in curve}
    result = backtester.run(panel, start, end)
    bt_equity = result.daily["equity"] / backtester.config.initial_equity
    common = [d for d in bt_equity.index if d in paper]
    if not common:
        return None
    last = common[-1]
    paper_ret = paper[last] / float(initial) - 1.0
    bt_ret = float(bt_equity.loc[last]) - 1.0
    deviation = abs(paper_ret - bt_ret) / max(abs(bt_ret), 0.01)
    return Reconciliation(start.date(), last.date(), len(common), paper_ret, bt_ret, deviation)


def positions_snapshot(positions: dict[Symbol, Position]) -> dict[str, str]:
    return {s: str(p.quantity) for s, p in sorted(positions.items())}
