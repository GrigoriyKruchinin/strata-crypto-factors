"""Cross-sectional normalisation and combination of factor scores."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd

from strata.domain.interfaces import IFactor
from strata.domain.panel import MarketPanel


def cross_sectional_rank(scores: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    """Uniform ranks in ``[-0.5, 0.5]`` within the universe of each date; NaN outside."""
    masked = scores.where(universe)
    pct = masked.rank(axis=1, pct=True, method="average")
    count = masked.notna().sum(axis=1)
    # Map pct ranks (1/n .. 1) to a symmetric grid centred on zero.
    centred = pct.sub(0.5 / count.where(count > 0), axis=0).sub(0.5)
    return centred.where(count.gt(1), axis=0)


def cross_sectional_zscore(
    scores: pd.DataFrame, universe: pd.DataFrame, winsor_quantile: float = 0.05
) -> pd.DataFrame:
    masked = scores.where(universe)
    if winsor_quantile > 0:
        lower = masked.quantile(winsor_quantile, axis=1)
        upper = masked.quantile(1 - winsor_quantile, axis=1)
        masked = masked.clip(lower=lower, upper=upper, axis=0)
    mean = masked.mean(axis=1)
    std = masked.std(axis=1)
    return masked.sub(mean, axis=0).div(std.where(std > 0), axis=0)


class CompositeFactor(IFactor):
    """Weighted average of cross-sectionally ranked component factors.

    Ranks are taken over all listed symbols (not only the universe) so the composite is a
    pure function of the panel; the portfolio step applies the universe mask afterwards.
    """

    def __init__(
        self, components: Sequence[IFactor], weights: Mapping[str, float] | None = None
    ) -> None:
        if not components:
            raise ValueError("composite needs at least one component")
        self.components = list(components)
        self.weights = dict(weights) if weights else {f.name: 1.0 for f in components}
        self.name = "composite[" + "+".join(f.name for f in self.components) + "]"

    def compute(self, panel: MarketPanel) -> pd.DataFrame:
        listed = panel.close.notna()
        total: pd.DataFrame | None = None
        weight_sum: pd.DataFrame | None = None
        for factor in self.components:
            w = self.weights.get(factor.name, 0.0)
            if w == 0.0:
                continue
            ranked = cross_sectional_rank(factor.compute(panel), listed)
            contrib = ranked.fillna(0.0) * w
            present = ranked.notna().astype(float) * abs(w)
            total = contrib if total is None else total + contrib
            weight_sum = present if weight_sum is None else weight_sum + present
        if total is None or weight_sum is None:
            raise ValueError("all composite weights are zero")
        return total.div(weight_sum.where(weight_sum > 0))
