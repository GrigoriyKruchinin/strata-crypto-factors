"""Declarative strategy specification: one spec = one tested variation."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from strata.backtest.engine import BacktestConfig, Backtester, Rebalance
from strata.costs.model import SquareRootImpactCostModel
from strata.domain.interfaces import IFactor
from strata.factors.library import (
    FundingCarry,
    LowBeta,
    LowVolatility,
    Momentum,
    ShortTermReversal,
    SmallSize,
)
from strata.factors.normalize import CompositeFactor
from strata.portfolio.quantile import QuantilePortfolio, Weighting
from strata.universe.point_in_time import LiquidityUniverse

FACTOR_CLASSES: dict[str, type[IFactor]] = {
    "momentum": Momentum,
    "reversal": ShortTermReversal,
    "low_vol": LowVolatility,
    "small_size": SmallSize,
    "funding_carry": FundingCarry,
    "low_beta": LowBeta,
}

DEFAULT_EXCLUDE = ("USDCUSDT", "BTCDOMUSDT", "DEFIUSDT", "FDUSDUSDT", "TUSDUSDT", "USDPUSDT")


class FactorSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    family: str
    params: dict[str, int | float | str] = Field(default_factory=dict)
    weight: float = 1.0

    def build(self) -> IFactor:
        cls = FACTOR_CLASSES[self.family]
        factor: IFactor = cls(**self.params)
        return factor


class StrategySpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    factors: tuple[FactorSpec, ...]
    # universe
    top_n: int = 50
    volume_lookback_days: int = 30
    min_age_days: int = 60
    min_avg_quote_volume: float = 5_000_000.0
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE
    # portfolio
    positions_per_side: int = 10
    weighting: Weighting = Weighting.EQUAL
    gross_leverage: float = 1.0
    max_gross_leverage: float = 2.0
    max_coin_weight: float = 0.15
    target_annual_vol: float | None = None
    max_turnover: float | None = None
    # execution / costs
    rebalance: Rebalance = Rebalance.WEEKLY
    execution_delay_days: int = 1
    initial_equity: float = 3000.0
    cost_multiplier: float = 1.0

    def config_dict(self) -> dict[str, Any]:
        """Everything except the display name: two specs with equal configs are one variation."""
        return self.model_dump(mode="json", exclude={"name"})

    @property
    def spec_id(self) -> str:
        payload = json.dumps(self.config_dict(), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]

    def build_factor(self) -> IFactor:
        built = [f.build() for f in self.factors]
        if len(built) == 1 and self.factors[0].weight == 1.0:
            return built[0]
        return CompositeFactor(
            built, {b.name: f.weight for b, f in zip(built, self.factors, strict=True)}
        )

    def build_universe(self, exclude_extra: tuple[str, ...] = ()) -> LiquidityUniverse:
        return LiquidityUniverse(
            top_n=self.top_n,
            lookback_days=self.volume_lookback_days,
            min_age_days=self.min_age_days,
            min_avg_quote_volume=self.min_avg_quote_volume,
            exclude=(*self.exclude, *exclude_extra),
        )

    def build_backtester(self, exclude_extra: tuple[str, ...] = ()) -> Backtester:
        return Backtester(
            universe=self.build_universe(exclude_extra),
            factor=self.build_factor(),
            constructor=QuantilePortfolio(
                positions_per_side=self.positions_per_side,
                weighting=self.weighting,
                gross_leverage=self.gross_leverage,
                max_coin_weight=self.max_coin_weight,
                target_annual_vol=self.target_annual_vol,
                max_gross_leverage=self.max_gross_leverage,
                max_turnover=self.max_turnover,
            ),
            cost_model=SquareRootImpactCostModel(
                cost_multiplier=Decimal(str(self.cost_multiplier))
            ),
            config=BacktestConfig(
                rebalance=self.rebalance,
                execution_delay_days=self.execution_delay_days,
                initial_equity=self.initial_equity,
            ),
        )
