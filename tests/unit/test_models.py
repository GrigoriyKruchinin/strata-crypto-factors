from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from strata.domain.models import Instrument, InstrumentStatus


def _inst() -> Instrument:
    return Instrument(
        symbol="ETHUSDT",
        base_asset="ETH",
        quote_asset="USDT",
        status=InstrumentStatus.TRADING,
        onboard_time=None,
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        min_notional=Decimal(20),
    )


@given(st.decimals(min_value=0, max_value=10_000, places=6, allow_nan=False))
def test_round_qty_never_exceeds_target(qty: Decimal) -> None:
    rounded = _inst().round_qty(qty)
    assert rounded <= qty
    assert qty - rounded < Decimal("0.001")
    assert rounded % Decimal("0.001") == 0


@given(st.decimals(min_value=Decimal("0.01"), max_value=100_000, places=4, allow_nan=False))
def test_round_price_on_tick(price: Decimal) -> None:
    rounded = _inst().round_price(price)
    assert rounded % Decimal("0.01") == 0
    assert abs(rounded - price) <= Decimal("0.005")


def test_min_notional() -> None:
    inst = _inst()
    assert not inst.is_tradeable_qty(Decimal("0.005"), Decimal(2000))
    assert inst.is_tradeable_qty(Decimal("-0.02"), Decimal(2000))
