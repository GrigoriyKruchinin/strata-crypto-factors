"""Robustness checks required before any Go/No-Go conclusion."""

from __future__ import annotations

import multiprocessing
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from strata.backtest.engine import BacktestConfig, Backtester
from strata.backtest.metrics import (
    Metrics,
    coin_profit_shares,
    compute_metrics,
    growth,
    max_drawdown,
    sharpe,
)
from strata.costs.model import SquareRootImpactCostModel
from strata.domain.interfaces import IFactor
from strata.domain.panel import MarketPanel
from strata.portfolio.benchmarks import EqualWeightLong, SingleAssetLong
from strata.research.runner import ResearchRunner, RunOutput
from strata.research.spec import StrategySpec
from strata.research.stats import percentile_of


class _ZeroFactor(IFactor):
    name = "zero"

    def compute(self, panel: MarketPanel) -> pd.DataFrame:
        return pd.DataFrame(0.0, index=panel.dates, columns=panel.close.columns)


# --------------------------------------------------------------------------- random signal


@dataclass
class RandomSignalResult:
    real_sharpe: float
    random_sharpes: np.ndarray
    percentile: float

    @property
    def p95(self) -> float:
        return float(np.percentile(self.random_sharpes, 95))


_WORKER: dict[str, Any] = {}


def _init_worker(state: dict[str, Any]) -> None:
    """Keys: bt, view, membership, start, end, seed (inherited by forked workers)."""
    _WORKER.update(state)


def _random_sharpe(run_id: int) -> float:
    view: MarketPanel = _WORKER["view"]
    bt: Backtester = _WORKER["bt"]
    # Seed per run (not per worker): results do not depend on how runs are split.
    rng = np.random.default_rng([_WORKER["seed"], run_id])
    scores = pd.DataFrame(
        rng.random(view.close.shape), index=view.dates, columns=view.close.columns
    )
    result = bt.run(
        view, _WORKER["start"], _WORKER["end"], scores=scores, membership=_WORKER["membership"]
    )
    return sharpe(result.returns)


def random_signal_test(
    spec: StrategySpec,
    panel: MarketPanel,
    start: pd.Timestamp,
    end: pd.Timestamp,
    real_sharpe: float,
    *,
    runs: int = 1000,
    seed: int = 42,
    workers: int = 1,
) -> RandomSignalResult:
    """Same universe, construction and costs, with uniformly random ranks each date.

    Random uniform scores are equivalent to shuffling the real ranks among eligible symbols.
    """
    view = panel.truncate(end + pd.Timedelta(days=1))
    bt = spec.build_backtester()
    membership = bt.universe.membership(view)
    state = {
        "bt": bt,
        "view": view,
        "membership": membership,
        "start": start,
        "end": end,
        "seed": seed,
    }
    if workers <= 1:
        _init_worker(state)
        sharpes = np.array([_random_sharpe(i) for i in range(runs)])
    else:
        ctx = multiprocessing.get_context("fork")
        with ProcessPoolExecutor(
            workers, mp_context=ctx, initializer=_init_worker, initargs=(state,)
        ) as pool:
            sharpes = np.array(list(pool.map(_random_sharpe, range(runs), chunksize=8)))
    return RandomSignalResult(real_sharpe, sharpes, percentile_of(real_sharpe, sharpes))


# --------------------------------------------------------------------------- top-coin exclusion


@dataclass
class ExclusionResult:
    excluded: list[str]
    metrics: Metrics


def top_coin_exclusion(
    runner: ResearchRunner,
    base: RunOutput,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    label: str,
    ks: Sequence[int] = (1, 2, 3),
) -> list[ExclusionResult]:
    shares = coin_profit_shares(base.result)
    out: list[ExclusionResult] = []
    for k in ks:
        top = [str(s) for s in shares.index[:k]]
        run = runner.run(
            base.spec,
            start,
            end,
            label=label,
            kind="robustness",
            exclude_extra=tuple(top),
            notes=f"exclude top {k} coins",
        )
        out.append(ExclusionResult(top, run.metrics))
    return out


# --------------------------------------------------------------------------- regimes


def btc_regimes(
    panel: MarketPanel, benchmark: str = "BTCUSDT", threshold: float = 0.15
) -> pd.Series:
    """Label each calendar quarter bull / bear / sideways by the benchmark's return."""
    close = panel.close[benchmark].dropna()
    quarterly = close.resample("QE").last().pct_change(fill_method=None)
    first = close.resample("QE").first()
    quarterly = quarterly.fillna(close.resample("QE").last() / first - 1.0)
    labels = pd.Series("sideways", index=quarterly.index)
    labels[quarterly > threshold] = "bull"
    labels[quarterly < -threshold] = "bear"
    daily = labels.reindex(panel.dates, method="bfill")
    out: pd.Series = daily.fillna("sideways")
    return out


def regime_breakdown(returns: pd.Series, regimes: pd.Series) -> pd.DataFrame:
    aligned = regimes.reindex(returns.index)
    rows = []
    for name, group in returns.groupby(aligned):
        rows.append(
            {
                "regime": name,
                "days": len(group),
                "total_return": growth(group) - 1.0,
                "sharpe": sharpe(group),
                "max_drawdown": max_drawdown(group),
            }
        )
    return pd.DataFrame(rows).set_index("regime") if rows else pd.DataFrame()


# --------------------------------------------------------------------------- walk-forward


@dataclass
class WalkForwardResult:
    oos_returns: pd.Series
    chosen: dict[str, str] = field(default_factory=dict)  # test period -> spec name

    @property
    def sharpe(self) -> float:
        return sharpe(self.oos_returns)


def walk_forward(
    runner: ResearchRunner,
    candidates: Sequence[StrategySpec],
    train_start: pd.Timestamp,
    test_years: Sequence[int],
) -> WalkForwardResult:
    """Expanding window: pick the best in-sample Sharpe up to year Y-1, trade it in year Y."""
    pieces: list[pd.Series] = []
    chosen: dict[str, str] = {}
    for year in test_years:
        is_end = pd.Timestamp(f"{year - 1}-12-31", tz="UTC")
        oos_start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        oos_end = pd.Timestamp(f"{year}-12-31", tz="UTC")
        scored = [
            (
                runner.run(
                    spec, train_start, is_end, label=f"wf_is_{year}", kind="robustness"
                ).metrics.sharpe,
                spec,
            )
            for spec in candidates
        ]
        best = max(scored, key=lambda t: t[0])[1]
        chosen[str(year)] = best.name
        oos = runner.run(best, oos_start, oos_end, label=f"wf_oos_{year}", kind="robustness")
        pieces.append(oos.result.returns)
    returns = pd.concat(pieces) if pieces else pd.Series(dtype=float)
    return WalkForwardResult(returns, chosen)


# --------------------------------------------------------------------------- benchmarks


def benchmark_returns(
    panel: MarketPanel,
    spec: StrategySpec,
    start: pd.Timestamp,
    end: pd.Timestamp,
    btc: str = "BTCUSDT",
) -> dict[str, pd.Series]:
    view = panel.truncate(end + pd.Timedelta(days=1))
    cfg = BacktestConfig(rebalance=spec.rebalance, initial_equity=spec.initial_equity)
    costs = SquareRootImpactCostModel()
    universe = spec.build_universe()
    btc_bt = Backtester(universe, _ZeroFactor(), SingleAssetLong(btc), costs, cfg)
    ew_bt = Backtester(universe, _ZeroFactor(), EqualWeightLong(), costs, cfg)
    # BTC is always "eligible" for its own benchmark regardless of universe rank.
    all_members = view.close.notna()
    return {
        "btc_buy_hold": btc_bt.run(view, start, end, membership=all_members).returns,
        "equal_weight_long": ew_bt.run(view, start, end).returns,
    }


def benchmark_metrics(returns: pd.Series) -> dict[str, float]:
    return {
        "total_return": growth(returns) - 1.0,
        "sharpe": sharpe(returns),
        "max_drawdown": max_drawdown(returns),
    }


def correlation(a: pd.Series, b: pd.Series) -> float:
    joined = pd.concat([a, b], axis=1).dropna()
    if len(joined) < 3:
        return float("nan")
    return float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))


def full_metrics(run: RunOutput) -> Metrics:
    return compute_metrics(run.result)
