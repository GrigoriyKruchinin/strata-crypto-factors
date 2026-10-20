from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select

from strata.data.store import ParquetStore
from strata.infra.db import (
    Base,
    CandleRow,
    ExperimentRow,
    FactorValueRow,
    FundingRow,
    make_engine,
    make_sessionmaker,
)
from strata.infra.ingest import ingest_experiments, ingest_market, record_signal
from strata.research.experiment_log import ExperimentRecord, JsonlExperimentLog
from tests.helpers import synthetic_panel, write_store


async def test_ingest_is_incremental_and_idempotent(tmp_path: Path) -> None:
    panel = synthetic_panel(n_days=40, n_symbols=3)
    store: ParquetStore = write_store(panel, tmp_path / "data")
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = make_sessionmaker(engine)

    first = await ingest_market(sessions, store)
    assert first == int(panel.close.notna().sum().sum()) * 2  # candles + funding
    assert await ingest_market(sessions, store) == 0  # nothing new
    async with sessions() as s:
        assert await s.scalar(select(func.count()).select_from(CandleRow)) == first // 2
        assert await s.scalar(select(func.count()).select_from(FundingRow)) == first // 2

    log = JsonlExperimentLog(tmp_path / "log.jsonl")
    log.append(
        ExperimentRecord(
            "s", "n", "train", "2020-01-01", "2020-12-31", {}, {"sharpe": 1.0}, "dv", "cv"
        )
    )
    assert await ingest_experiments(sessions, log) == 1
    await ingest_experiments(sessions, log)
    await record_signal(
        sessions,
        strategy="x",
        signal_date=date(2021, 1, 3),
        universe_adv=pd.Series({"A": 1.0}),
        factor_scores={"f": pd.Series({"A": 0.5, "B": float("nan")})},
    )
    async with sessions() as s:
        assert await s.scalar(select(func.count()).select_from(ExperimentRow)) == 1
        assert await s.scalar(select(func.count()).select_from(FactorValueRow)) == 1
    await engine.dispose()
