from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from strata.config import FactorSettings
from strata.domain.interfaces import IFactor
from strata.factors.library import LowBeta, Momentum
from strata.factors.normalize import CompositeFactor, cross_sectional_rank
from strata.factors.registry import build_factors, families
from tests.helpers import synthetic_panel
from tests.lookahead import assert_no_lookahead

PANEL = synthetic_panel(n_days=200, n_symbols=10)
# Synthetic panel has no BTCUSDT; alias the first symbol so LowBeta is exercised.
BETA = LowBeta(window=30, benchmark="C00USDT")
ALL_FACTORS: list[IFactor] = [*build_factors(FactorSettings(_env_file=None)), BETA]


@pytest.mark.parametrize("factor", ALL_FACTORS, ids=lambda f: f.name)
def test_factor_has_no_lookahead(factor: IFactor) -> None:
    assert_no_lookahead(factor.compute, PANEL)


def test_composite_has_no_lookahead() -> None:
    composite = CompositeFactor(ALL_FACTORS)
    assert_no_lookahead(composite.compute, PANEL)


def test_registry_covers_all_families() -> None:
    assert families() == [
        "funding_carry",
        "low_beta",
        "low_vol",
        "momentum",
        "reversal",
        "small_size",
    ]
    with pytest.raises(KeyError):
        build_factors(FactorSettings(_env_file=None), ["nope"])


def test_momentum_skips_recent_days() -> None:
    panel = synthetic_panel(n_days=10, n_symbols=1)
    close = pd.DataFrame({panel.symbols[0]: np.arange(1.0, 11.0)}, index=panel.dates)
    panel = replace(panel, close=close)
    mom = Momentum(window=5, skip=2).compute(panel)
    # at row 9: close[7] / close[4] - 1 = 8/5 - 1
    assert mom.iloc[9, 0] == pytest.approx(8 / 5 - 1)


@settings(max_examples=50, deadline=None)
@given(st.lists(st.floats(-1e6, 1e6, allow_nan=False), min_size=2, max_size=40, unique=True))
def test_rank_is_centred_and_bounded(values: list[float]) -> None:
    frame = pd.DataFrame([values])
    universe = pd.DataFrame([[True] * len(values)])
    ranked = cross_sectional_rank(frame, universe).iloc[0]
    assert ranked.sum() == pytest.approx(0.0, abs=1e-9)
    assert ranked.between(-0.5, 0.5).all()
    assert ranked.idxmax() == int(np.argmax(values))


def test_rank_ignores_symbols_outside_universe() -> None:
    frame = pd.DataFrame([[1.0, 2.0, 3.0]])
    universe = pd.DataFrame([[True, True, False]])
    ranked = cross_sectional_rank(frame, universe).iloc[0]
    assert pd.isna(ranked[2])
    assert ranked[1] > ranked[0]
