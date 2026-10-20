import pandas as pd

from strata.universe.point_in_time import LiquidityUniverse
from tests.helpers import synthetic_panel
from tests.lookahead import assert_no_lookahead

PANEL = synthetic_panel(n_days=240, n_symbols=12)


def _traded(sym: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(PANEL.close[sym].dropna().index)


def _universe(**kw: object) -> LiquidityUniverse:
    params: dict[str, object] = {"top_n": 5, "min_age_days": 20, "min_avg_quote_volume": 0.0}
    params.update(kw)
    return LiquidityUniverse(**params)  # type: ignore[arg-type]


def test_universe_has_no_lookahead() -> None:
    assert_no_lookahead(_universe().membership, PANEL)


def test_universe_size_and_listing_rules() -> None:
    members = _universe().membership(PANEL)
    assert (members.sum(axis=1) <= 5).all()
    assert members.iloc[-1].sum() == 5
    # never a member before it is listed + seasoned, or after it stops trading
    for sym in PANEL.symbols:
        first = _traded(sym)[0]
        seasoned = first + pd.Timedelta(days=20)
        assert not members.loc[: seasoned - pd.Timedelta(days=1), sym].any()
        last = _traded(sym)[-1]
        assert not members.loc[last + pd.Timedelta(days=1) :, sym].any()


def test_delisted_symbol_is_member_while_trading() -> None:
    dead = PANEL.symbols[-1]
    members = _universe(top_n=12).membership(PANEL)
    last = _traded(dead)[-1]
    assert members.at[last, dead]


def test_exclude_list() -> None:
    sym = PANEL.symbols[0]
    members = _universe(exclude=[sym]).membership(PANEL)
    assert not members[sym].any()
