"""Dollar-neutral long/short quantile portfolio."""

from __future__ import annotations

import math
from enum import StrEnum

import numpy as np
import pandas as pd

from strata.domain.interfaces import IPortfolioConstructor, PortfolioContext

ANNUALISATION = 365.0


class Weighting(StrEnum):
    EQUAL = "equal"
    INVERSE_VOL = "inverse_vol"


def cap_weights(weights: pd.Series, side_total: float, cap: float) -> pd.Series:
    """Scale positive ``weights`` to sum to ``side_total`` with no name above ``cap``.

    Excess above the cap is redistributed pro rata to uncapped names; if the cap binds for
    everyone the side sums to less than ``side_total`` (never more).
    """
    if weights.empty or side_total <= 0:
        return weights * 0.0
    w = weights / weights.sum() * side_total
    for _ in range(len(w)):
        over = w > cap + 1e-15
        if not over.any():
            break
        excess = float((w[over] - cap).sum())
        w[over] = cap
        free = ~over & (w < cap)
        if not free.any():
            break
        w[free] += excess * w[free] / w[free].sum()
    return w.clip(upper=cap)


class QuantilePortfolio(IPortfolioConstructor):
    def __init__(
        self,
        *,
        positions_per_side: int = 10,
        weighting: Weighting = Weighting.EQUAL,
        gross_leverage: float = 1.0,
        max_coin_weight: float = 0.15,
        target_annual_vol: float | None = None,
        max_gross_leverage: float = 2.0,
        max_turnover: float | None = None,
    ) -> None:
        if positions_per_side < 1:
            raise ValueError("positions_per_side must be >= 1")
        if gross_leverage > max_gross_leverage:
            raise ValueError("gross_leverage exceeds max_gross_leverage")
        self.positions_per_side = positions_per_side
        self.weighting = weighting
        self.gross_leverage = gross_leverage
        self.max_coin_weight = max_coin_weight
        self.target_annual_vol = target_annual_vol
        self.max_gross_leverage = max_gross_leverage
        self.max_turnover = max_turnover

    def _side(self, names: pd.Index, context: PortfolioContext, total: float) -> pd.Series:
        if self.weighting is Weighting.INVERSE_VOL:
            vol = context.volatility.reindex(names)
            vol = vol.where(vol > 0).fillna(vol.median() if vol.notna().any() else 1.0)
            raw = 1.0 / vol
        else:
            raw = pd.Series(1.0, index=names)
        return cap_weights(raw.astype(float), total, self.max_coin_weight)

    def _vol_scale(self, weights: pd.Series, context: PortfolioContext) -> float:
        if self.target_annual_vol is None or context.recent_returns is None:
            return 1.0
        rets = context.recent_returns.reindex(columns=weights.index).fillna(0.0)
        if len(rets) < 10:
            return 1.0
        cov = rets.cov().to_numpy()
        w = weights.to_numpy()
        vol = math.sqrt(max(float(w @ cov @ w), 0.0) * ANNUALISATION)
        if vol <= 0:
            return 1.0
        return self.target_annual_vol / vol

    def construct(self, scores: pd.Series, context: PortfolioContext) -> pd.Series:
        valid = scores.dropna()
        n = min(self.positions_per_side, len(valid) // 2)
        if n == 0:
            return pd.Series(dtype=float)
        ordered = valid.sort_values(kind="mergesort")
        shorts = ordered.index[:n]
        longs = ordered.index[-n:]
        half = self.gross_leverage / 2.0
        long_w = self._side(longs, context, half)
        short_w = self._side(shorts, context, half)
        # Keep dollar neutrality even when caps bind unevenly.
        side = min(float(long_w.sum()), float(short_w.sum()))
        long_w *= side / long_w.sum()
        short_w *= side / short_w.sum()
        weights = pd.concat([long_w, -short_w])

        scale = self._vol_scale(weights, context)
        gross = float(weights.abs().sum())
        max_scale = self.max_gross_leverage / gross if gross > 0 else 1.0
        cap_scale = self.max_coin_weight / float(weights.abs().max())
        weights *= min(scale, max_scale, cap_scale)

        if self.max_turnover is not None and not context.previous_weights.empty:
            weights = _limit_turnover(weights, context.previous_weights, self.max_turnover)
        nonzero: pd.Series = weights.loc[weights.abs() > 0]
        return nonzero.sort_index()


def _limit_turnover(target: pd.Series, previous: pd.Series, max_turnover: float) -> pd.Series:
    """Move only part of the way from ``previous`` to ``target`` (one-way turnover cap)."""
    names = target.index.union(previous.index)
    t = target.reindex(names, fill_value=0.0)
    p = previous.reindex(names, fill_value=0.0)
    turnover = float((t - p).abs().sum())
    if turnover <= max_turnover or turnover == 0:
        return t
    step = max_turnover / turnover
    blended = p + step * (t - p)
    # Blending two neutral books stays neutral; clean numerical dust.
    blended[np.isclose(blended, 0.0, atol=1e-12)] = 0.0
    return blended
