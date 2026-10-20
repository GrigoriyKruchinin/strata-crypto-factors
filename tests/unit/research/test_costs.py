from decimal import Decimal

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from strata.costs.model import SquareRootImpactCostModel

MODEL = SquareRootImpactCostModel()


def test_vector_and_decimal_paths_agree() -> None:
    trade = pd.Series({"A": 0.1, "B": -0.05})
    adv = pd.Series({"A": 50_000_000.0, "B": 2_000_000.0})
    vec = MODEL.trading_cost(trade, equity=3000.0, adv_quote=adv)
    for sym in trade.index:
        notional = Decimal(str(abs(trade[sym]) * 3000))
        est = MODEL.estimate_fill(notional, Decimal(str(adv[sym])))
        assert float(est.total) / 3000 == pytest.approx(vec[sym], rel=1e-9)


@given(st.floats(1, 1e6), st.floats(1e5, 1e10))
def test_cost_monotone_in_size_and_doubles(notional: float, adv: float) -> None:
    small = MODEL.estimate_fill(Decimal(str(notional)), Decimal(str(adv)))
    big = MODEL.estimate_fill(Decimal(str(notional * 2)), Decimal(str(adv)))
    assert big.total / Decimal(2) >= small.total * Decimal("0.999999")
    doubled = MODEL.with_multiplier(Decimal(2)).estimate_fill(
        Decimal(str(notional)), Decimal(str(adv))
    )
    assert doubled.total == pytest.approx(small.total * 2)


def test_unknown_adv_charges_max_slippage() -> None:
    cost = MODEL.trading_cost(pd.Series({"A": 0.1}), 1000.0, pd.Series({"A": float("nan")}))
    assert cost["A"] == pytest.approx(0.1 * (0.0005 + 0.05))


def test_funding_sign() -> None:
    weights = pd.Series({"L": 0.5, "S": -0.5})
    rates = pd.Series({"L": 0.001, "S": 0.001})
    pnl = MODEL.funding_pnl(weights, rates)
    assert pnl["L"] == pytest.approx(-0.0005)  # long pays positive funding
    assert pnl["S"] == pytest.approx(0.0005)  # short receives it
