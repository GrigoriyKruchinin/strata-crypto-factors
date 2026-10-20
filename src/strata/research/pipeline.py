"""Stage 1 research pipeline implementing ``docs/research/protocol.md`` step by step."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from strata.backtest.metrics import (
    Metrics,
    growth,
    rolling_window_returns,
    sharpe,
    yearly_returns,
)
from strata.data.panel_builder import build_panel
from strata.data.store import ParquetStore
from strata.domain.panel import MarketPanel
from strata.research.experiment_log import JsonlExperimentLog, git_version
from strata.research.grid import candidate_grid
from strata.research.holdout import HoldoutGuard
from strata.research.runner import HOLDOUT, ResearchRunner, RunOutput
from strata.research.spec import StrategySpec
from strata.research.stats import deflated_sharpe
from strata.research.validation import (
    benchmark_metrics,
    benchmark_returns,
    btc_regimes,
    correlation,
    random_signal_test,
    regime_breakdown,
    top_coin_exclusion,
    walk_forward,
)

logger = logging.getLogger(__name__)

TRAIN_START = pd.Timestamp("2020-04-01", tz="UTC")
TRAIN_END = pd.Timestamp("2023-12-31", tz="UTC")
HOLDOUT_START = pd.Timestamp("2024-01-01", tz="UTC")
WALK_FORWARD_YEARS = (2021, 2022, 2023)
MIN_COST2_SHARPE = 0.5
TARGET_VOL = 0.20
FINALISTS = 3


@dataclass(frozen=True)
class GoCriteria:
    """Agreed 2026-10-19 (todo.md). Fixed before the holdout is opened."""

    min_annual_return: float = 0.20
    max_drawdown: float = 0.25
    min_sharpe: float = 1.0
    min_cost2_sharpe: float = 0.5
    min_random_percentile: float = 0.95
    max_coin_profit_share: float = 0.15
    min_positive_6m_windows: float = 0.60
    max_paper_deviation: float = 0.25
    min_paper_days: int = 28


def evaluate_criteria(
    holdout: Metrics,
    cost2: Metrics,
    random_percentile: float,
    criteria: GoCriteria | None = None,
) -> dict[str, dict[str, Any]]:
    c = criteria or GoCriteria()
    checks = {
        "annual_return": (
            holdout.annual_return,
            f">= {c.min_annual_return:.0%}",
            holdout.annual_return >= c.min_annual_return,
        ),
        "max_drawdown": (
            holdout.max_drawdown,
            f"<= {c.max_drawdown:.0%}",
            holdout.max_drawdown <= c.max_drawdown,
        ),
        "sharpe": (holdout.sharpe, f">= {c.min_sharpe}", holdout.sharpe >= c.min_sharpe),
        "cost2_sharpe": (
            cost2.sharpe,
            f">= {c.min_cost2_sharpe}",
            cost2.sharpe >= c.min_cost2_sharpe,
        ),
        "random_percentile": (
            random_percentile,
            f">= {c.min_random_percentile:.0%}",
            random_percentile >= c.min_random_percentile,
        ),
        "max_coin_profit_share": (
            holdout.max_coin_profit_share,
            f"<= {c.max_coin_profit_share:.0%}",
            holdout.max_coin_profit_share <= c.max_coin_profit_share,
        ),
        "positive_6m_windows": (
            holdout.positive_6m_windows,
            f">= {c.min_positive_6m_windows:.0%}",
            holdout.positive_6m_windows >= c.min_positive_6m_windows,
        ),
    }
    return {k: {"value": v, "threshold": t, "pass": bool(p)} for k, (v, t, p) in checks.items()}


def _json_default(obj: object) -> object:
    if isinstance(obj, np.integer | np.floating):
        return obj.item()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return str(obj)


class ResearchPipeline:
    def __init__(
        self,
        data_root: Path,
        research_dir: Path,
        artifacts_dir: Path,
        *,
        random_runs: int = 1000,
        seed: int = 42,
        workers: int = 1,
        grid: list[StrategySpec] | None = None,
    ) -> None:
        self.store = ParquetStore(data_root)
        self.research_dir = research_dir
        self.results_dir = research_dir / "results"
        self.artifacts_dir = artifacts_dir
        self.random_runs = random_runs
        self.seed = seed
        self.workers = workers
        self.grid = grid if grid is not None else candidate_grid()
        self.log = JsonlExperimentLog(research_dir / "experiment-log.jsonl")
        self.guard = HoldoutGuard(HOLDOUT_START.date(), research_dir)
        self._panel: MarketPanel | None = None

    # ------------------------------------------------------------------ plumbing
    @property
    def panel(self) -> MarketPanel:
        if self._panel is None:
            self._panel = build_panel(self.store)
        return self._panel

    def runner(self) -> ResearchRunner:
        return ResearchRunner(
            self.panel,
            self.log,
            self.guard,
            data_version=self.store.data_version(),
            code_version=git_version(),
            artifacts_dir=self.artifacts_dir,
        )

    def _save(self, name: str, payload: dict[str, Any]) -> Path:
        self.results_dir.mkdir(parents=True, exist_ok=True)
        path = self.results_dir / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, default=_json_default))
        return path

    def _load(self, name: str) -> dict[str, Any]:
        data: dict[str, Any] = json.loads((self.results_dir / f"{name}.json").read_text())
        return data

    def _spec(self, spec_id: str) -> StrategySpec:
        for spec in self.grid:
            if spec.spec_id == spec_id:
                return spec
        raise KeyError(spec_id)

    def _save_returns(self, name: str, returns: dict[str, pd.Series]) -> None:
        frame = pd.DataFrame(returns)
        path = self.results_dir / f"{name}_returns.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, float_format="%.8f")

    # ------------------------------------------------------------------ step 1-3, 5-6
    def train(self) -> Path:
        runner = self.runner()
        rows: list[dict[str, Any]] = []
        trial_daily_sharpes: list[float] = []
        outputs: dict[str, RunOutput] = {}
        for spec in self.grid:
            logger.info("train: %s", spec.name)
            base = runner.run(spec, TRAIN_START, TRAIN_END, label="train")
            cost2 = runner.run(
                spec.model_copy(update={"cost_multiplier": 2.0}),
                TRAIN_START,
                TRAIN_END,
                label="train",
                kind="robustness",
                notes=f"costs x2 of {spec.spec_id}",
            )
            outputs[spec.spec_id] = base
            r = base.result.returns
            trial_daily_sharpes.append(float(r.mean() / r.std()) if r.std() > 0 else 0.0)
            rows.append(
                {
                    "spec_id": spec.spec_id,
                    "name": spec.name,
                    **base.metrics.as_dict(),
                    "cost2_sharpe": cost2.metrics.sharpe,
                    "cost2_annual_return": cost2.metrics.annual_return,
                    "yearly": yearly_returns(r).to_dict(),
                }
            )
        ranking = sorted(rows, key=lambda x: x["sharpe"], reverse=True)
        eligible = [x for x in ranking if x["cost2_sharpe"] >= MIN_COST2_SHARPE]
        finalists = [x["spec_id"] for x in eligible[:FINALISTS]]

        wf = walk_forward(runner, self.grid, TRAIN_START, WALK_FORWARD_YEARS)
        n_trials = self.log.distinct_variations("candidate")
        trials = np.array(trial_daily_sharpes)
        for row in rows:
            row["deflated_sharpe"] = deflated_sharpe(
                outputs[row["spec_id"]].result.returns, n_trials, trials
            )
        primary = finalists[0] if finalists else None
        leverage = None
        if primary is not None:
            vol = next(x["annual_vol"] for x in rows if x["spec_id"] == primary)
            leverage = float(np.clip(TARGET_VOL / vol, 0.5, 2.0)) if vol > 0 else 1.0
        factor_returns = {s.name: outputs[s.spec_id].result.returns for s in self.grid}
        corr = pd.DataFrame(factor_returns).corr().round(3)
        self._save_returns("train", factor_returns)
        return self._save(
            "train",
            {
                "period": [str(TRAIN_START.date()), str(TRAIN_END.date())],
                "ranking": ranking,
                "finalists": finalists,
                "primary": primary,
                "primary_leverage": leverage,
                "walk_forward": {
                    "chosen": wf.chosen,
                    "oos_sharpe": wf.sharpe,
                    "oos_total_return": growth(wf.oos_returns) - 1.0,
                },
                "distinct_candidates": n_trials,
                "correlation": corr.to_dict(),
            },
        )

    # ------------------------------------------------------------------ step 4
    def robustness(self) -> Path:
        train = self._load("train")
        runner = self.runner()
        regimes = btc_regimes(self.panel)
        out: dict[str, Any] = {}
        bench_saved = False
        for spec_id in train["finalists"]:
            spec = self._spec(spec_id)
            logger.info("robustness: %s", spec.name)
            base = runner.run(spec, TRAIN_START, TRAIN_END, label="train", kind="robustness")
            rnd = random_signal_test(
                spec,
                self.panel,
                TRAIN_START,
                TRAIN_END,
                base.metrics.sharpe,
                runs=self.random_runs,
                seed=self.seed,
                workers=self.workers,
            )
            excl = top_coin_exclusion(runner, base, TRAIN_START, TRAIN_END, label="train")
            bench = benchmark_returns(self.panel, spec, TRAIN_START, TRAIN_END)
            if not bench_saved:
                self._save_returns("train_benchmarks", bench)
                bench_saved = True
            out[spec_id] = {
                "name": spec.name,
                "sharpe": base.metrics.sharpe,
                "random_signal": {
                    "percentile": rnd.percentile,
                    "p95_random_sharpe": rnd.p95,
                    "median_random_sharpe": float(np.median(rnd.random_sharpes)),
                },
                "exclusion": [
                    {
                        "excluded": e.excluded,
                        "sharpe": e.metrics.sharpe,
                        "annual_return": e.metrics.annual_return,
                    }
                    for e in excl
                ],
                "regimes": regime_breakdown(base.result.returns, regimes).to_dict("index"),
                "benchmarks": {k: benchmark_metrics(v) for k, v in bench.items()},
                "corr_btc": correlation(base.result.returns, bench["btc_buy_hold"]),
            }
        return self._save("robustness", out)

    # ------------------------------------------------------------------ freeze + holdout
    def freeze(self) -> Path:
        train = self._load("train")
        if train["primary"] is None:
            raise RuntimeError(
                "no candidate passed the costs x2 filter on train; nothing to freeze"
            )
        self.guard.freeze(
            train["finalists"],
            {"primary": train["primary"], "primary_leverage": train["primary_leverage"]},
        )
        return self.guard.freeze_path

    def holdout(self, end: pd.Timestamp | None = None) -> Path:
        self.guard.frozen_spec_ids()  # raises if the candidate set was never frozen
        frozen = json.loads(self.guard.freeze_path.read_text())
        primary_id: str = frozen["details"]["primary"]
        leverage: float = frozen["details"]["primary_leverage"]
        self.guard.open_once([primary_id])
        last = self.panel.dates[-2]  # holding bar d needs open[d+1]
        hold_end = min(end, last) if end is not None else last
        base_spec = self._spec(primary_id)
        spec = base_spec.model_copy(
            update={"gross_leverage": leverage, "name": f"{base_spec.name}@{leverage:.2f}x"}
        )
        runner = self.runner()
        main = runner.run(spec, HOLDOUT_START, hold_end, label=HOLDOUT, kind="holdout")
        cost2 = runner.run(
            spec.model_copy(update={"cost_multiplier": 2.0}),
            HOLDOUT_START,
            hold_end,
            label=HOLDOUT,
            kind="holdout",
            notes="costs x2",
        )
        rnd = random_signal_test(
            spec,
            self.panel,
            HOLDOUT_START,
            hold_end,
            main.metrics.sharpe,
            runs=self.random_runs,
            seed=self.seed,
            workers=self.workers,
        )
        excl = top_coin_exclusion(runner, main, HOLDOUT_START, hold_end, label=HOLDOUT)
        bench = benchmark_returns(self.panel, spec, HOLDOUT_START, hold_end)
        regimes = btc_regimes(self.panel)
        r = main.result.returns
        self._save_returns("holdout", {"strategy": r, **bench})
        windows = rolling_window_returns(r)
        return self._save(
            "holdout",
            {
                "period": [str(HOLDOUT_START.date()), str(hold_end.date())],
                "spec_id": spec.spec_id,
                "base_spec_id": primary_id,
                "name": spec.name,
                "leverage": leverage,
                "metrics": main.metrics.as_dict(),
                "cost2_metrics": cost2.metrics.as_dict(),
                "random_signal": {
                    "percentile": rnd.percentile,
                    "p95_random_sharpe": rnd.p95,
                    "median_random_sharpe": float(np.median(rnd.random_sharpes)),
                },
                "exclusion": [
                    {
                        "excluded": e.excluded,
                        "sharpe": e.metrics.sharpe,
                        "annual_return": e.metrics.annual_return,
                    }
                    for e in excl
                ],
                "yearly": yearly_returns(r).to_dict(),
                "rolling_6m": {
                    "count": len(windows),
                    "positive_share": float((windows > 0).mean()) if len(windows) else 0.0,
                },
                "regimes": regime_breakdown(r, regimes).to_dict("index"),
                "benchmarks": {k: benchmark_metrics(v) for k, v in bench.items()},
                "corr_btc": correlation(r, bench["btc_buy_hold"]),
                "top_coins": main.result.contributions.sum()
                .sort_values()
                .pipe(lambda s: {"best": s.tail(5).to_dict(), "worst": s.head(5).to_dict()}),
                "criteria": evaluate_criteria(main.metrics, cost2.metrics, rnd.percentile),
                "sharpe_check": sharpe(r),
            },
        )
