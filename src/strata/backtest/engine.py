"""Event-ordered daily backtester.

Timeline for a holding bar ``h`` (all UTC):

1. At ``open[h]`` trade from drifted weights to the target decided at the close of the signal
   bar ``h - execution_delay`` (signal rows ``<= h - delay`` only). Fees and slippage are paid.
2. Hold over bar ``h``: earn ``open[h+1] / open[h] - 1`` and the funding settled in
   ``(h, h+1]``. If the contract has no ``open[h+1]`` (delisting/gap) the position is exited at
   ``close[h]`` and the exit is charged as a trade.
3. Weights drift with returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
import pandas as pd

from strata.domain.interfaces import (
    ICostModel,
    IFactor,
    IPortfolioConstructor,
    IUniverseProvider,
    PortfolioContext,
)
from strata.domain.panel import MarketPanel

ANNUALISATION = 365


class Rebalance(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


@dataclass(frozen=True)
class BacktestConfig:
    rebalance: Rebalance = Rebalance.WEEKLY
    #: Weekday of the *signal* bar for weekly rebalancing (6 = Sunday close, trade Monday open).
    signal_weekday: int = 6
    execution_delay_days: int = 1
    initial_equity: float = 3000.0
    vol_window: int = 30
    cov_window: int = 60


@dataclass
class BacktestResult:
    daily: pd.DataFrame  # per holding bar: equity, returns and cost breakdown
    contributions: pd.DataFrame  # per bar x symbol PnL in quote currency (after costs)
    targets: dict[pd.Timestamp, pd.Series] = field(default_factory=dict)  # by signal date

    @property
    def returns(self) -> pd.Series:
        net: pd.Series = self.daily["net_return"]
        return net


class Backtester:
    def __init__(
        self,
        universe: IUniverseProvider,
        factor: IFactor,
        constructor: IPortfolioConstructor,
        cost_model: ICostModel,
        config: BacktestConfig | None = None,
    ) -> None:
        self.universe = universe
        self.factor = factor
        self.constructor = constructor
        self.cost_model = cost_model
        self.config = config or BacktestConfig()

    def _is_signal_date(self, date: pd.Timestamp) -> bool:
        if self.config.rebalance is Rebalance.DAILY:
            return True
        return date.weekday() == self.config.signal_weekday

    def run(
        self,
        panel: MarketPanel,
        start: pd.Timestamp | None = None,
        end: pd.Timestamp | None = None,
        scores: pd.DataFrame | None = None,
        membership: pd.DataFrame | None = None,
    ) -> BacktestResult:
        """Simulate holding bars in ``[start, end]``. ``scores``/``membership`` may be passed in
        precomputed (e.g. for permutation tests); they must follow the same timing contract."""
        m = self._prepare(panel, scores, membership)
        dates = panel.dates
        lo = 0 if start is None else int(dates.searchsorted(start))
        hi = len(dates) if end is None else int(dates.searchsorted(end, side="right"))
        state = _State(w=np.zeros(len(m.symbols)), equity=self.config.initial_equity)
        rows: list[dict[str, float | pd.Timestamp]] = []
        contrib: list[np.ndarray] = []
        targets: dict[pd.Timestamp, pd.Series] = {}

        for h in range(lo, hi):
            row, day_contrib = self._step(m, h, state, targets)
            rows.append(row)
            contrib.append(day_contrib)
            if state.equity <= 0:
                break

        daily = pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()
        contributions = pd.DataFrame(
            np.array(contrib) if contrib else np.zeros((0, len(m.symbols))),
            index=daily.index,
            columns=m.symbols,
        )
        return BacktestResult(daily=daily, contributions=contributions, targets=targets)

    def _prepare(
        self,
        panel: MarketPanel,
        scores: pd.DataFrame | None,
        membership: pd.DataFrame | None,
    ) -> _Market:
        cfg = self.config
        dates = panel.dates
        symbols = panel.close.columns
        raw_scores = self.factor.compute(panel) if scores is None else scores
        raw_members = self.universe.membership(panel) if membership is None else membership
        daily_rets = panel.returns()
        vol = daily_rets.rolling(cfg.vol_window, min_periods=max(2, cfg.vol_window // 2)).std()
        open_ = panel.open.to_numpy(dtype=float)
        close = panel.close.to_numpy(dtype=float)
        next_open = np.vstack([open_[1:], np.full((1, open_.shape[1]), np.nan)])
        no_next = np.isnan(next_open) & ~np.isnan(open_)
        held = np.where(no_next, close / open_ - 1.0, next_open / open_ - 1.0)
        return _Market(
            dates=dates,
            symbols=symbols,
            scores=raw_scores.reindex(index=dates, columns=symbols),
            members=raw_members.reindex(index=dates, columns=symbols).fillna(False).astype(bool),
            daily_rets=daily_rets,
            vol=vol * np.sqrt(ANNUALISATION),
            adv=panel.quote_volume.rolling(30, min_periods=1).mean(),
            tradeable=~np.isnan(open_),
            held_ret=np.nan_to_num(held, nan=0.0),
            no_next=no_next,
            funding=np.nan_to_num(panel.funding.to_numpy(dtype=float), nan=0.0),
        )

    def _rebalance(
        self, m: _Market, h: int, state: _State, targets: dict[pd.Timestamp, pd.Series]
    ) -> tuple[np.ndarray, float]:
        """Trade to the new target at ``open[h]``; return (cost vector, turnover)."""
        cfg = self.config
        signal_idx = h - cfg.execution_delay_days
        n = len(m.symbols)
        if signal_idx < 0 or not self._is_signal_date(m.dates[signal_idx]):
            return np.zeros(n), 0.0
        sdate = m.dates[signal_idx]
        row_scores = m.scores.iloc[signal_idx]
        eligible = m.members.iloc[signal_idx] & row_scores.notna() & m.tradeable[h]
        ctx = PortfolioContext(
            date=sdate,
            volatility=m.vol.iloc[signal_idx][eligible],
            previous_weights=pd.Series(state.w, index=m.symbols)[state.w != 0],
            recent_returns=m.daily_rets.iloc[
                max(0, signal_idx - cfg.cov_window + 1) : signal_idx + 1
            ].loc[:, eligible],
        )
        target_s = self.constructor.construct(row_scores[eligible], ctx)
        targets[sdate] = target_s
        target = target_s.reindex(m.symbols, fill_value=0.0).to_numpy(dtype=float)
        trade = target - state.w
        cost = self.cost_model.trading_cost(
            pd.Series(trade, index=m.symbols), state.equity, m.adv.iloc[signal_idx]
        ).to_numpy(dtype=float)
        state.w = target
        return cost, float(np.abs(trade).sum())

    def _step(
        self, m: _Market, h: int, state: _State, targets: dict[pd.Timestamp, pd.Series]
    ) -> tuple[dict[str, float | pd.Timestamp], np.ndarray]:
        cost_vec, turnover = self._rebalance(m, h, state, targets)
        w = state.w
        gross_vec = w * m.held_ret[h]
        fund_vec = self.cost_model.funding_pnl(
            pd.Series(w, index=m.symbols), pd.Series(m.funding[h], index=m.symbols)
        ).to_numpy(dtype=float)

        # Positions whose contract has no next bar are exited at the close and charged.
        forced = m.no_next[h] & (w != 0)
        exit_vec = np.zeros(len(m.symbols))
        if forced.any():
            exit_trade = np.where(forced, -w * (1.0 + m.held_ret[h]), 0.0)
            exit_vec = self.cost_model.trading_cost(
                pd.Series(exit_trade, index=m.symbols), state.equity, m.adv.iloc[h]
            ).to_numpy(dtype=float)

        gross_ret = float(gross_vec.sum())
        funding_ret = float(fund_vec.sum())
        cost_ret = float(cost_vec.sum() + exit_vec.sum())
        net_ret = gross_ret + funding_ret - cost_ret
        day_contrib = (gross_vec + fund_vec - cost_vec - exit_vec) * state.equity
        start_equity = state.equity
        state.equity *= 1.0 + net_ret
        row: dict[str, float | pd.Timestamp] = {
            "date": m.dates[h],
            "equity": state.equity,
            "start_equity": start_equity,
            "gross_return": gross_ret,
            "funding_return": funding_ret,
            "cost_return": -cost_ret,
            "net_return": net_ret,
            "turnover": turnover + float(np.abs(np.where(forced, w, 0.0)).sum()),
            "long_exposure": float(w[w > 0].sum()),
            "short_exposure": float(-w[w < 0].sum()),
            "positions": int((w != 0).sum()),
        }
        # Drift: position notionals move with prices, equity with the net result.
        growth = 1.0 + net_ret
        drifted = w * (1.0 + m.held_ret[h]) / growth if growth > 0 else np.zeros_like(w)
        drifted[forced] = 0.0
        state.w = drifted
        return row, day_contrib


@dataclass
class _State:
    w: np.ndarray
    equity: float


@dataclass(frozen=True)
class _Market:
    dates: pd.DatetimeIndex
    symbols: pd.Index
    scores: pd.DataFrame
    members: pd.DataFrame
    daily_rets: pd.DataFrame
    vol: pd.DataFrame
    adv: pd.DataFrame
    tradeable: np.ndarray
    held_ret: np.ndarray
    no_next: np.ndarray
    funding: np.ndarray
