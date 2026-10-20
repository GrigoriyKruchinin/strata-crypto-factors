import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from strata.domain.interfaces import PortfolioContext
from strata.portfolio.quantile import QuantilePortfolio, Weighting, cap_weights

DATE = pd.Timestamp("2022-01-01", tz="UTC")


def _scores(values: list[float]) -> pd.Series:
    return pd.Series(values, index=[f"S{i}" for i in range(len(values))])


def _ctx(names: pd.Index, seed: int = 0, prev: pd.Series | None = None) -> PortfolioContext:
    rng = np.random.default_rng(seed)
    return PortfolioContext(
        date=DATE,
        volatility=pd.Series(rng.uniform(0.3, 2.0, len(names)), index=names),
        previous_weights=prev if prev is not None else pd.Series(dtype=float),
        recent_returns=pd.DataFrame(rng.normal(0, 0.05, (60, len(names))), columns=names),
    )


score_lists = st.lists(st.floats(-10, 10, allow_nan=False), min_size=2, max_size=60, unique=True)


@settings(max_examples=100, deadline=None)
@given(
    score_lists,
    st.integers(1, 15),
    st.sampled_from(list(Weighting)),
    st.floats(0.2, 2.0),
    st.floats(0.02, 0.5),
    st.one_of(st.none(), st.floats(0.1, 1.0)),
)
def test_book_invariants(
    values: list[float],
    per_side: int,
    weighting: Weighting,
    gross: float,
    cap: float,
    target_vol: float | None,
) -> None:
    scores = _scores(values)
    pf = QuantilePortfolio(
        positions_per_side=per_side,
        weighting=weighting,
        gross_leverage=gross,
        max_coin_weight=cap,
        target_annual_vol=target_vol,
        max_gross_leverage=2.0,
    )
    w = pf.construct(scores, _ctx(scores.index))
    n = min(per_side, len(values) // 2)
    assert (w > 0).sum() == n and (w < 0).sum() == n
    assert w.sum() == pytest.approx(0.0, abs=1e-9)  # dollar neutral
    assert w.abs().max() <= cap + 1e-9
    assert w.abs().sum() <= 2.0 + 1e-9
    if target_vol is None:
        assert w.abs().sum() <= gross + 1e-9
    longs = set(w[w > 0].index)
    shorts = set(w[w < 0].index)
    assert min(scores[list(longs)]) > max(scores[list(shorts)])


@settings(max_examples=50, deadline=None)
@given(score_lists, st.floats(0.05, 1.0))
def test_turnover_limit(values: list[float], max_turnover: float) -> None:
    scores = _scores(values)
    names = scores.index
    base = QuantilePortfolio(positions_per_side=5)
    prev = base.construct(-scores, _ctx(names))  # opposite book: maximal turnover
    limited = QuantilePortfolio(positions_per_side=5, max_turnover=max_turnover)
    w = limited.construct(scores, _ctx(names, prev=prev))
    turnover = (w.reindex(names, fill_value=0) - prev.reindex(names, fill_value=0)).abs().sum()
    assert turnover <= max_turnover + 1e-9
    assert w.sum() == pytest.approx(0.0, abs=1e-9)


@given(
    st.lists(st.floats(0.01, 100), min_size=1, max_size=30),
    st.floats(0.1, 1.0),
    st.floats(0.01, 1.0),
)
def test_cap_weights(raw: list[float], total: float, cap: float) -> None:
    w = cap_weights(pd.Series(raw), total, cap)
    assert w.max() <= cap + 1e-12
    assert w.sum() <= total + 1e-9
    assert w.sum() == pytest.approx(min(total, cap * len(raw)), rel=1e-6)


def test_too_few_names_returns_empty() -> None:
    w = QuantilePortfolio().construct(_scores([1.0]), _ctx(pd.Index(["S0"])))
    assert w.empty
