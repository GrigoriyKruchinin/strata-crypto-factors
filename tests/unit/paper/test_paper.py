from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from strata.costs.model import SquareRootImpactCostModel
from strata.domain.models import OrderRequest, Position, Side
from strata.infra.db import Base, make_engine, make_sessionmaker
from strata.paper.gateway import SimulatedGateway
from strata.paper.repository import InMemoryPaperRepository, SqlPaperRepository
from strata.paper.sizing import default_instrument, size_orders
from strata.paper.trader import PaperTrader, StaleDataError, reconcile
from strata.research.grid import MOM_28
from strata.research.spec import StrategySpec
from tests.helpers import synthetic_panel

PANEL = synthetic_panel(n_days=200, n_symbols=12, start="2021-01-01")
SPEC = StrategySpec(
    name="mom",
    factors=(MOM_28,),
    top_n=10,
    min_age_days=10,
    min_avg_quote_volume=0.0,
    positions_per_side=3,
    max_coin_weight=0.3,
)
D = Decimal
LAST_CLOSE: dict[str, float] = {
    str(k): float(v) for k, v in PANEL.close.loc["2021-04-19"].dropna().to_dict().items()
}


def test_size_orders_rounds_drops_and_closes() -> None:
    inst = {s: default_instrument(s) for s in ["A", "B", "C"]}
    res = size_orders(
        {"A": D("0.2"), "B": D("0.001")},
        {"C": D("1.5")},
        {"A": D(100), "B": D(100), "C": D(10)},
        D(3000),
        instruments=inst,
        order_prefix="t",
    )
    assert res.target_quantities == {"A": D("6.000")}
    assert res.dropped == ["B"]  # $3 < $20 min notional
    by_symbol = {o.symbol: o for o in res.orders}
    assert by_symbol["A"].side is Side.BUY and by_symbol["A"].quantity == D(6)
    assert by_symbol["C"].side is Side.SELL and by_symbol["C"].reduce_only


async def test_gateway_accounting_identity() -> None:
    model = SquareRootImpactCostModel()
    gw = SimulatedGateway(D(1000), {}, model)
    gw.set_market({"A": D(100)}, {"A": D(10_000_000)}, pd.Timestamp("2021-01-01").to_pydatetime())
    fills = await gw.submit([OrderRequest("A", Side.BUY, D(2), "o1")])
    costs = fills[0].fee + fills[0].slippage_cost
    assert gw.equity() == pytest.approx(D(1000) - costs)
    assert gw.positions["A"].quantity == D(2)
    funding = gw.apply_funding({"A": D("0.001")})
    assert funding == D("-0.2")
    await gw.submit([OrderRequest("A", Side.SELL, D(2), "o2")])
    assert "A" not in gw.positions


async def _run_days(trader: PaperTrader, start: date, days: int) -> list[object]:
    return [await trader.cycle(start + timedelta(days=i)) for i in range(days)]


def _trader(repo: InMemoryPaperRepository | SqlPaperRepository) -> PaperTrader:
    return PaperTrader(
        account="paper",
        strategy_name=SPEC.name,
        backtester=SPEC.build_backtester(),
        repository=repo,
        panel_provider=lambda: PANEL,
        instruments={},
        initial_equity=D(3000),
    )


async def test_paper_matches_backtest_and_is_idempotent() -> None:
    repo = InMemoryPaperRepository()
    trader = _trader(repo)
    start = date(2021, 4, 1)
    reports = await _run_days(trader, start, 60)
    assert any(r.rebalanced for r in reports)  # type: ignore[attr-defined]
    assert all(
        r.signal_date is None or r.signal_date.weekday() == 6  # type: ignore[attr-defined]
        for r in reports
    )
    again = await trader.cycle(start + timedelta(days=59))
    assert again.processed == [] and again.warnings

    curve = await repo.equity_curve("paper")
    assert len(curve) == 60
    rec = reconcile(SPEC.build_backtester(), PANEL, curve, D(3000))
    assert rec is not None
    # Same signals, same fill price, same cost model: only sizing/rounding differ.
    assert abs(rec.paper_return - rec.backtest_return) < 0.005
    assert rec.deviation < 0.15
    assert rec.within(0.25)


async def test_catch_up_after_missed_days() -> None:
    repo = InMemoryPaperRepository()
    trader = _trader(repo)
    await trader.cycle(date(2021, 4, 1))
    report = await trader.cycle(date(2021, 4, 12))  # laptop was off for 10 days
    assert len(report.processed) == 11
    assert report.signal_date == date(2021, 4, 11)


async def test_refuses_stale_data() -> None:
    trader = _trader(InMemoryPaperRepository())
    with pytest.raises(StaleDataError):
        await trader.cycle(date(2022, 1, 1))  # panel ends 2021-07-19


async def test_sql_repository_roundtrip(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'paper.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    repo = SqlPaperRepository(make_sessionmaker(engine))
    trader = _trader(repo)
    reports = await _run_days(trader, date(2021, 4, 1), 20)
    positions = await repo.load_positions("paper")
    account = await repo.load_account("paper")
    assert account is not None and account.last_processed == date(2021, 4, 19)
    assert all(isinstance(p, Position) for p in positions.values())
    assert float(reports[-1].equity) == pytest.approx(  # type: ignore[attr-defined]
        float(
            account.cash
            + sum(
                (p.quantity * D(repr(LAST_CLOSE[s])) for s, p in positions.items()),
                D(0),
            )
        ),
        rel=1e-9,
    )
    # Replaying a cycle never duplicates trades (clientOrderId is the key).
    curve = await repo.equity_curve("paper")
    assert len(curve) == 20
    await engine.dispose()
