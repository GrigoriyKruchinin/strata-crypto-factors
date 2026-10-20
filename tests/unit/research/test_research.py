from dataclasses import fields, replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from strata.domain.panel import MarketPanel
from strata.research.experiment_log import JsonlExperimentLog
from strata.research.holdout import HoldoutGuard, HoldoutViolationError
from strata.research.runner import ResearchRunner
from strata.research.spec import FactorSpec, StrategySpec
from strata.research.stats import deflated_sharpe, expected_max_sharpe, probabilistic_sharpe
from strata.research.validation import (
    benchmark_returns,
    btc_regimes,
    random_signal_test,
    regime_breakdown,
    top_coin_exclusion,
    walk_forward,
)
from tests.helpers import synthetic_panel

T = pd.Timestamp


def _panel() -> MarketPanel:
    panel = synthetic_panel(n_days=1000, n_symbols=12, start="2020-01-01")
    rename = {panel.symbols[0]: "BTCUSDT"}
    frames = {
        f.name: getattr(panel, f.name).rename(columns=rename)
        for f in fields(panel)
        if isinstance(getattr(panel, f.name), pd.DataFrame)
    }
    return replace(panel, onboard_date=panel.onboard_date.rename(rename), **frames)


PANEL = _panel()


def _spec(name: str = "mom", window: int = 28) -> StrategySpec:
    return StrategySpec(
        name=name,
        factors=(FactorSpec(family="momentum", params={"window": window, "skip": 7}),),
        top_n=10,
        min_age_days=10,
        min_avg_quote_volume=0.0,
        positions_per_side=3,
        max_coin_weight=0.3,
    )


def _runner(tmp_path: Path) -> ResearchRunner:
    return ResearchRunner(
        PANEL,
        JsonlExperimentLog(tmp_path / "log.jsonl"),
        HoldoutGuard(date(2022, 1, 1), tmp_path / "state"),
        data_version="test",
        code_version="test",
        artifacts_dir=tmp_path / "artifacts",
    )


def test_spec_id_ignores_name_and_is_stable() -> None:
    assert _spec("a").spec_id == _spec("b").spec_id
    assert _spec(window=28).spec_id != _spec(window=56).spec_id


def test_runner_logs_and_guards(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    out = runner.run(_spec(), T("2020-03-01", tz="UTC"), T("2021-06-30", tz="UTC"), label="train")
    assert out.metrics.days == 487
    records = runner.log.records()
    assert len(records) == 1 and records[0].spec_id == _spec().spec_id
    assert runner.log.distinct_variations() == 1
    with pytest.raises(HoldoutViolationError):
        runner.run(_spec(), T("2020-03-01", tz="UTC"), T("2022-02-01", tz="UTC"), label="train")


def test_holdout_opens_once_for_frozen_only(tmp_path: Path) -> None:
    guard = HoldoutGuard(date(2022, 1, 1), tmp_path)
    with pytest.raises(HoldoutViolationError):
        guard.open_once(["x"])
    guard.freeze(["a", "b"], {})
    with pytest.raises(HoldoutViolationError):
        guard.freeze(["c"], {})
    with pytest.raises(HoldoutViolationError):
        guard.open_once(["c"])
    guard.open_once(["a"])
    with pytest.raises(HoldoutViolationError):
        guard.open_once(["a"])


def test_random_signal_distribution() -> None:
    res = random_signal_test(
        _spec(), PANEL, T("2020-03-01", tz="UTC"), T("2020-12-31", tz="UTC"), 0.0, runs=15
    )
    assert len(res.random_sharpes) == 15
    assert np.isfinite(res.random_sharpes).all()
    assert 0.0 <= res.percentile <= 1.0


def test_exclusion_and_walk_forward(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    start, end = T("2020-03-01", tz="UTC"), T("2021-12-31", tz="UTC")
    base = runner.run(_spec(), start, end, label="train")
    excl = top_coin_exclusion(runner, base, start, end, label="train", ks=(1, 2))
    assert len(excl[1].excluded) == 2
    wf = walk_forward(runner, [_spec("a", 28), _spec("b", 56)], start, [2021])
    assert set(wf.chosen) == {"2021"}
    assert wf.oos_returns.index.min() == T("2021-01-01", tz="UTC")
    assert runner.log.distinct_variations("candidate") == 1


def test_benchmarks_and_regimes() -> None:
    start, end = T("2020-03-01", tz="UTC"), T("2021-12-31", tz="UTC")
    bench = benchmark_returns(PANEL, _spec(), start, end)
    btc = bench["btc_buy_hold"]
    # Long BTC perp 100%: open-to-open move minus funding paid (costs only on trade days).
    move = PANEL.open["BTCUSDT"].shift(-1) / PANEL.open["BTCUSDT"] - 1
    expected = (move - PANEL.funding["BTCUSDT"]).loc[start:end]
    # Small residual: weight drifts between weekly rebalances as funding moves equity.
    assert (btc - expected).abs().iloc[3:].median() < 1e-4
    assert btc.corr(expected) > 0.999
    regimes = btc_regimes(PANEL)
    assert set(regimes.unique()) <= {"bull", "bear", "sideways"}
    table = regime_breakdown(bench["equal_weight_long"], regimes)
    assert table["days"].sum() == len(bench["equal_weight_long"])


def test_deflated_sharpe_penalises_many_trials() -> None:
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.001, 0.01, 1000))
    trials = rng.normal(0, 0.03, 200)
    assert probabilistic_sharpe(r) > deflated_sharpe(r, 200, trials)
    assert expected_max_sharpe(1, 1.0) == 0.0
    assert expected_max_sharpe(1000, 1e-3) > expected_max_sharpe(10, 1e-3)


def test_random_signal_parallel_matches_serial() -> None:
    args = (_spec(), PANEL, T("2020-03-01", tz="UTC"), T("2020-08-31", tz="UTC"), 0.0)
    serial = random_signal_test(*args, runs=6, workers=1)
    parallel = random_signal_test(*args, runs=6, workers=3)
    np.testing.assert_allclose(serial.random_sharpes, parallel.random_sharpes)
