"""Factor registry: builds the configured factor set (OCP: register new IFactor classes here)."""

from __future__ import annotations

from collections.abc import Callable

from strata.config import FactorSettings
from strata.domain.interfaces import IFactor
from strata.factors.library import (
    FundingCarry,
    LowBeta,
    LowVolatility,
    Momentum,
    ShortTermReversal,
    SmallSize,
)

FactorBuilder = Callable[[FactorSettings], list[IFactor]]

_REGISTRY: dict[str, FactorBuilder] = {
    "momentum": lambda s: [Momentum(w, s.momentum_skip_days) for w in s.momentum_windows],
    "reversal": lambda s: [ShortTermReversal(s.reversal_window)],
    "low_vol": lambda s: [LowVolatility(s.volatility_window)],
    "small_size": lambda s: [SmallSize(s.liquidity_window)],
    "funding_carry": lambda s: [FundingCarry(s.funding_window)],
    "low_beta": lambda s: [LowBeta(s.beta_window)],
}


def register(family: str, builder: FactorBuilder) -> None:
    if family in _REGISTRY:
        raise ValueError(f"factor family {family!r} already registered")
    _REGISTRY[family] = builder


def families() -> list[str]:
    return sorted(_REGISTRY)


def build_factors(settings: FactorSettings, only: list[str] | None = None) -> list[IFactor]:
    names = only or families()
    unknown = set(names) - set(_REGISTRY)
    if unknown:
        raise KeyError(f"unknown factor families: {sorted(unknown)}")
    return [f for name in names for f in _REGISTRY[name](settings)]
