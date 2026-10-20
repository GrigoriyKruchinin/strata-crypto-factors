"""Base factor library.

Each factor's sign is fixed *a priori* from the literature (Liu, Tsyvinski & Wu 2022;
Frazzini & Pedersen 2014; carry literature) so that "higher score = expected outperformer".
Flipping a sign after looking at results counts as a new variation in the experiment log.
Every ``compute`` uses rolling/shifted windows ending at row ``d`` only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strata.domain.interfaces import IFactor
from strata.domain.panel import MarketPanel


class Momentum(IFactor):
    """Past return over ``(t - window, t - skip]``: winners keep winning (time-series of weeks)."""

    def __init__(self, window: int = 28, skip: int = 7) -> None:
        if not 0 <= skip < window:
            raise ValueError("require 0 <= skip < window")
        self.window = window
        self.skip = skip
        self.name = f"momentum_{window}_{skip}"

    def compute(self, panel: MarketPanel) -> pd.DataFrame:
        close = panel.close
        return close.shift(self.skip) / close.shift(self.window) - 1.0


class ShortTermReversal(IFactor):
    """Negative of the last ``window``-day return: short-term losers rebound."""

    def __init__(self, window: int = 7) -> None:
        self.window = window
        self.name = f"reversal_{window}"

    def compute(self, panel: MarketPanel) -> pd.DataFrame:
        return -(panel.close / panel.close.shift(self.window) - 1.0)


class LowVolatility(IFactor):
    """Negative realised volatility: low-vol coins have better risk-adjusted returns."""

    def __init__(self, window: int = 30) -> None:
        self.window = window
        self.name = f"low_vol_{window}"

    def compute(self, panel: MarketPanel) -> pd.DataFrame:
        min_periods = max(2, int(self.window * 0.8))
        return -panel.returns().rolling(self.window, min_periods=min_periods).std()


class SmallSize(IFactor):
    """Negative log of average traded value (size/liquidity proxy): small coins outperform."""

    def __init__(self, window: int = 30) -> None:
        self.window = window
        self.name = f"small_size_{window}"

    def compute(self, panel: MarketPanel) -> pd.DataFrame:
        min_periods = max(1, int(self.window * 0.8))
        adv = panel.quote_volume.rolling(self.window, min_periods=min_periods).mean()
        positive = adv.where(adv > 0)
        return -pd.DataFrame(np.log(positive), index=adv.index, columns=adv.columns)


class FundingCarry(IFactor):
    """Negative cumulative funding: short coins whose longs pay, long coins whose shorts pay."""

    def __init__(self, window: int = 14) -> None:
        self.window = window
        self.name = f"funding_carry_{window}"

    def compute(self, panel: MarketPanel) -> pd.DataFrame:
        min_periods = max(1, int(self.window * 0.8))
        return -panel.funding.rolling(self.window, min_periods=min_periods).sum()


class LowBeta(IFactor):
    """Negative rolling beta to BTC (betting against beta)."""

    def __init__(self, window: int = 60, benchmark: str = "BTCUSDT") -> None:
        self.window = window
        self.benchmark = benchmark
        self.name = f"low_beta_{window}"

    def compute(self, panel: MarketPanel) -> pd.DataFrame:
        rets = panel.returns()
        if self.benchmark not in rets.columns:
            return pd.DataFrame(np.nan, index=rets.index, columns=rets.columns)
        bench = rets[self.benchmark]
        min_periods = max(2, int(self.window * 0.8))
        cov = rets.rolling(self.window, min_periods=min_periods).cov(bench)
        var = bench.rolling(self.window, min_periods=min_periods).var()
        return -cov.div(var, axis=0)
