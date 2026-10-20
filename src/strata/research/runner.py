"""Research runner: every backtest goes through here so it is guarded and logged."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from strata.backtest.engine import BacktestResult
from strata.backtest.metrics import Metrics, compute_metrics
from strata.domain.panel import MarketPanel
from strata.research.experiment_log import ExperimentRecord, IExperimentLog
from strata.research.holdout import HoldoutGuard, HoldoutViolationError
from strata.research.spec import StrategySpec

HOLDOUT = "holdout"


@dataclass
class RunOutput:
    spec: StrategySpec
    result: BacktestResult
    metrics: Metrics


class ResearchRunner:
    def __init__(
        self,
        panel: MarketPanel,
        log: IExperimentLog,
        guard: HoldoutGuard,
        *,
        data_version: str,
        code_version: str,
        artifacts_dir: Path | None = None,
    ) -> None:
        self.panel = panel
        self.log = log
        self.guard = guard
        self.data_version = data_version
        self.code_version = code_version
        self.artifacts_dir = artifacts_dir

    def run(
        self,
        spec: StrategySpec,
        start: pd.Timestamp,
        end: pd.Timestamp,
        *,
        label: str,
        kind: str = "candidate",
        exclude_extra: tuple[str, ...] = (),
        notes: str = "",
    ) -> RunOutput:
        if label != HOLDOUT:
            self.guard.check_research_period(end)
        elif not self.guard.is_opened():
            raise HoldoutViolationError("holdout runs require HoldoutGuard.open_once() first")
        # Signals need history before ``start``; the guard above bounds the end of data used.
        panel = self.panel.truncate(end + pd.Timedelta(days=1))
        result = spec.build_backtester(exclude_extra).run(panel, start, end)
        metrics = compute_metrics(result)
        self.log.append(
            ExperimentRecord(
                spec_id=spec.spec_id,
                spec_name=spec.name,
                period_label=label,
                period_start=str(start.date()),
                period_end=str(end.date()),
                config={**spec.config_dict(), "exclude_extra": list(exclude_extra)},
                metrics=metrics.as_dict(),
                data_version=self.data_version,
                code_version=self.code_version,
                kind=kind,
                notes=notes,
            )
        )
        if self.artifacts_dir is not None:
            path = self.artifacts_dir / "runs" / f"{spec.spec_id}_{label}_{kind}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            result.daily.to_parquet(path)
        return RunOutput(spec, result, metrics)
