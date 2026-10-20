import json
from dataclasses import fields, replace
from pathlib import Path

import pandas as pd
import pytest

from strata.data.store import ParquetStore, Table
from strata.domain.panel import MarketPanel
from strata.research.grid import MOM_28, REV_7
from strata.research.holdout import HoldoutViolationError
from strata.research.pipeline import ResearchPipeline
from strata.research.spec import StrategySpec
from tests.helpers import synthetic_panel


def _write_store(panel: MarketPanel, root: Path) -> ParquetStore:
    store = ParquetStore(root)
    for sym in panel.symbols:
        traded = panel.close[sym].notna()
        idx = panel.dates[traded]
        store.write_table(
            Table.KLINES_1D,
            sym,
            pd.DataFrame(
                {
                    "open_time": idx,
                    "open": panel.open.loc[idx, sym].to_numpy(),
                    "high": panel.high.loc[idx, sym].to_numpy(),
                    "low": panel.low.loc[idx, sym].to_numpy(),
                    "close": panel.close.loc[idx, sym].to_numpy(),
                    "volume": 1.0,
                    "quote_volume": panel.quote_volume.loc[idx, sym].to_numpy(),
                    "trades": 1,
                }
            ),
        )
        store.write_table(
            Table.FUNDING,
            sym,
            pd.DataFrame(
                {
                    "funding_time": idx + pd.Timedelta(hours=8),
                    "rate": panel.funding.loc[idx, sym].to_numpy(),
                }
            ),
        )
    return store


def _panel() -> MarketPanel:
    panel = synthetic_panel(n_days=2100, n_symbols=12, start="2020-01-01")
    rename = {panel.symbols[0]: "BTCUSDT"}
    frames = {
        f.name: getattr(panel, f.name).rename(columns=rename)
        for f in fields(panel)
        if isinstance(getattr(panel, f.name), pd.DataFrame)
    }
    return replace(panel, onboard_date=panel.onboard_date.rename(rename), **frames)


def test_pipeline_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_store(_panel(), tmp_path / "data")
    common = {"top_n": 10, "min_age_days": 10, "min_avg_quote_volume": 0.0}
    grid = [
        StrategySpec(name="mom", factors=(MOM_28,), positions_per_side=3, **common),
        StrategySpec(name="rev", factors=(REV_7,), positions_per_side=3, **common),
    ]
    pipe = ResearchPipeline(
        tmp_path / "data", tmp_path / "research", tmp_path / "artifacts", random_runs=3, grid=grid
    )
    # Synthetic random walks have no edge: loosen the costs x2 filter so the flow runs.
    monkeypatch.setattr("strata.research.pipeline.MIN_COST2_SHARPE", -100.0)
    train = json.loads(pipe.train().read_text())
    assert {r["name"] for r in train["ranking"]} == {"mom", "rev"}
    assert train["primary"] in {g.spec_id for g in grid}
    assert 0.5 <= train["primary_leverage"] <= 2.0
    assert train["distinct_candidates"] == 2
    assert set(train["walk_forward"]["chosen"]) == {"2021", "2022", "2023"}

    rob = json.loads(pipe.robustness().read_text())
    assert set(rob) == set(train["finalists"])

    with pytest.raises(HoldoutViolationError):
        pipe.holdout()  # not frozen yet
    pipe.freeze()
    hold = json.loads(pipe.holdout().read_text())
    assert hold["period"][0] == "2024-01-01"
    assert set(hold["criteria"]) >= {"sharpe", "random_percentile", "max_drawdown"}
    with pytest.raises(HoldoutViolationError):
        pipe.holdout()  # opened once only

    log_lines = (tmp_path / "research" / "experiment-log.jsonl").read_text().splitlines()
    labels = {json.loads(line)["period_label"] for line in log_lines}
    assert {"train", "holdout", "wf_oos_2021"} <= labels
