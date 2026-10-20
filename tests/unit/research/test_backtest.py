from dataclasses import replace
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from strata.backtest.engine import BacktestConfig, Backtester, Rebalance
from strata.backtest.metrics import compute_metrics, max_drawdown, monthly_return, sharpe
from strata.costs.model import SquareRootImpactCostModel
from strata.domain.interfaces import IFactor
from strata.domain.panel import MarketPanel
from strata.factors.library import Momentum
from strata.portfolio.quantile import QuantilePortfolio
from strata.universe.point_in_time import LiquidityUniverse
from tests.helpers import synthetic_panel
from tests.lookahead import _scramble_after

ZERO_COST = SquareRootImpactCostModel(
    taker_fee=Decimal(0), base_slippage_bps=Decimal(0), impact_coefficient=Decimal(0)
)


class Fixed(IFactor):
    name = "fixed"

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    def compute(self, panel: MarketPanel) -> pd.DataFrame:
        return pd.DataFrame(
            [self.scores] * len(panel.dates), index=panel.dates, columns=panel.close.columns
        )


def _two_coin_panel() -> MarketPanel:
    idx = pd.date_range("2022-01-01", periods=5, freq="D", tz="UTC")
    open_ = pd.DataFrame({"A": [100, 100, 110, 121, 121], "B": [50, 50, 45, 45, 45]}, index=idx)
    open_ = open_.astype(float)
    close = open_.shift(-1).fillna(open_)
    vol = pd.DataFrame(1e9, index=idx, columns=open_.columns)
    funding = pd.DataFrame({"A": 0.001, "B": 0.0}, index=idx)
    return MarketPanel(
        open=open_,
        high=close,
        low=close,
        close=close,
        quote_volume=vol,
        funding=funding,
        onboard_date=pd.Series(
            pd.Timestamp("2020-01-01", tz="UTC"), index=open_.columns, dtype="datetime64[ns, UTC]"
        ),
    )


def _bt(factor: IFactor, cost: SquareRootImpactCostModel = ZERO_COST, **cfg: object) -> Backtester:
    return Backtester(
        LiquidityUniverse(top_n=10, min_age_days=0, min_avg_quote_volume=0.0, lookback_days=1),
        factor,
        QuantilePortfolio(positions_per_side=1, gross_leverage=1.0, max_coin_weight=0.5),
        cost,
        BacktestConfig(**cfg),  # type: ignore[arg-type]
    )


def test_hand_computed_two_coin_book() -> None:
    panel = _two_coin_panel()
    result = _bt(Fixed({"A": 1.0, "B": -1.0}), rebalance=Rebalance.DAILY).run(panel)
    r = result.daily
    # Signal on day 0 -> trade at open of day 1: long A 0.5, short B 0.5.
    # Bar 1: A +10%, B -10%  => 0.5*0.10 + (-0.5)*(-0.10) = 0.10; funding: long A pays 0.0005.
    assert r["net_return"].iloc[0] == 0.0
    assert r["gross_return"].iloc[1] == pytest.approx(0.10)
    assert r["funding_return"].iloc[1] == pytest.approx(-0.0005)
    assert r["long_exposure"].iloc[1] == pytest.approx(0.5)
    assert r["short_exposure"].iloc[1] == pytest.approx(0.5)
    equity = 3000.0 * np.prod(1 + r["net_return"].to_numpy())
    assert r["equity"].iloc[-1] == pytest.approx(equity)
    assert result.contributions.sum().sum() == pytest.approx(r["equity"].iloc[-1] - 3000.0)


def test_costs_scale_with_multiplier() -> None:
    panel = _two_coin_panel()
    base = SquareRootImpactCostModel()
    one = _bt(Fixed({"A": 1.0, "B": -1.0}), base, rebalance=Rebalance.DAILY).run(panel)
    two = _bt(
        Fixed({"A": 1.0, "B": -1.0}), base.with_multiplier(Decimal(2)), rebalance=Rebalance.DAILY
    ).run(panel)
    first = one.daily["cost_return"].iloc[1]
    assert first < 0
    assert two.daily["cost_return"].iloc[1] == pytest.approx(2 * first)


def test_backtest_has_no_lookahead() -> None:
    panel = synthetic_panel(n_days=220, n_symbols=12)
    bt = Backtester(
        LiquidityUniverse(top_n=8, min_age_days=10, min_avg_quote_volume=0.0),
        Momentum(28, 7),
        QuantilePortfolio(positions_per_side=3),
        SquareRootImpactCostModel(),
        BacktestConfig(rebalance=Rebalance.WEEKLY),
    )
    full = bt.run(panel)
    for cut in panel.dates[[100, 150, 200]]:
        scrambled = bt.run(_scramble_after(panel, cut))
        before = cut - pd.Timedelta(days=1)
        pd.testing.assert_series_equal(full.returns.loc[:before], scrambled.returns.loc[:before])
        for sdate, target in full.targets.items():
            if sdate <= cut:
                pd.testing.assert_series_equal(target, scrambled.targets[sdate])


def test_delisted_position_is_force_closed() -> None:
    panel = synthetic_panel(n_days=220, n_symbols=12)
    dead = panel.symbols[-1]
    last = pd.DatetimeIndex(panel.close[dead].dropna().index)[-1]
    # Make the dying coin the top long every day.
    scores = pd.DataFrame(0.0, index=panel.dates, columns=panel.close.columns)
    scores[dead] = 1.0
    scores.iloc[:, 0] = -1.0
    bt = _bt(Fixed({}), rebalance=Rebalance.DAILY)
    result = bt.run(panel, scores=scores)
    assert result.targets[last - pd.Timedelta(days=1)].get(dead, 0.0) > 0
    after = result.daily.loc[last + pd.Timedelta(days=1) :]
    assert (result.contributions.loc[last + pd.Timedelta(days=1) :, dead] == 0).all()
    assert len(after) > 0


def test_weekly_rebalances_only_on_signal_weekday() -> None:
    panel = synthetic_panel(n_days=60, n_symbols=8)
    result = _bt(Momentum(14, 2), rebalance=Rebalance.WEEKLY).run(panel)
    assert all(d.weekday() == 6 for d in result.targets)
    traded_days = result.daily.index[result.daily["turnover"] > 0]
    assert all(d.weekday() == 0 for d in traded_days)


def test_metric_helpers() -> None:
    r = pd.Series([0.1, -0.5, 0.2])
    assert max_drawdown(r) == pytest.approx(0.5)
    assert sharpe(pd.Series([0.01] * 10)) == 0.0
    panel = replace(synthetic_panel(n_days=120, n_symbols=8))
    m = compute_metrics(_bt(Momentum(14, 2)).run(panel))
    assert m.days == 120
    assert 0 <= m.max_coin_profit_share <= 1


def test_monthly_return_matches_compounding() -> None:
    daily = (1.015) ** (12 / 365.25) - 1
    assert monthly_return(pd.Series([daily] * 730)) == pytest.approx(0.015, rel=1e-9)
    assert monthly_return(pd.Series([-0.001] * 100)) < 0
