"""Pre-registered candidate grid (committed before any result on real data was seen).

Changing this file after results are known creates new variations; they are all counted in
the experiment log and in the multiple-testing correction.
"""

from __future__ import annotations

from strata.backtest.engine import Rebalance
from strata.portfolio.quantile import Weighting
from strata.research.spec import FactorSpec, StrategySpec

MOM_28 = FactorSpec(family="momentum", params={"window": 28, "skip": 7})
MOM_56 = FactorSpec(family="momentum", params={"window": 56, "skip": 7})
MOM_84 = FactorSpec(family="momentum", params={"window": 84, "skip": 7})
REV_7 = FactorSpec(family="reversal", params={"window": 7})
LOW_VOL = FactorSpec(family="low_vol", params={"window": 30})
SMALL = FactorSpec(family="small_size", params={"window": 30})
CARRY = FactorSpec(family="funding_carry", params={"window": 14})
LOW_BETA = FactorSpec(family="low_beta", params={"window": 60})

ALL_SIX = (MOM_28, REV_7, LOW_VOL, SMALL, CARRY, LOW_BETA)


def candidate_grid() -> list[StrategySpec]:
    singles = {
        "momentum_28": MOM_28,
        "momentum_56": MOM_56,
        "momentum_84": MOM_84,
        "reversal_7": REV_7,
        "low_vol_30": LOW_VOL,
        "small_size_30": SMALL,
        "funding_carry_14": CARRY,
        "low_beta_60": LOW_BETA,
    }
    composites: dict[str, tuple[FactorSpec, ...]] = {
        "mom_carry": (MOM_28, CARRY),
        "mom_lowvol": (MOM_28, LOW_VOL),
        "ltw_size_mom": (MOM_28, SMALL),
        "all_six": ALL_SIX,
    }
    specs = [StrategySpec(name=n, factors=(f,)) for n, f in singles.items()]
    specs += [StrategySpec(name=n, factors=f) for n, f in composites.items()]
    specs += [
        StrategySpec(name="reversal_7_daily", factors=(REV_7,), rebalance=Rebalance.DAILY),
        StrategySpec(name="all_six_daily", factors=ALL_SIX, rebalance=Rebalance.DAILY),
        StrategySpec(name="all_six_invvol", factors=ALL_SIX, weighting=Weighting.INVERSE_VOL),
        StrategySpec(
            name="mom_carry_invvol", factors=(MOM_28, CARRY), weighting=Weighting.INVERSE_VOL
        ),
        StrategySpec(name="all_six_top30", factors=ALL_SIX, top_n=30),
        StrategySpec(name="mom_carry_top30", factors=(MOM_28, CARRY), top_n=30),
    ]
    return specs
