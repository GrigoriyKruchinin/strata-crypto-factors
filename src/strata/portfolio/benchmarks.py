"""Simple benchmark constructors (long-only, for comparison only)."""

from __future__ import annotations

import pandas as pd

from strata.domain.interfaces import IPortfolioConstructor, PortfolioContext


class EqualWeightLong(IPortfolioConstructor):
    """Long every eligible symbol with equal weight (gross = ``gross_leverage``)."""

    def __init__(self, gross_leverage: float = 1.0) -> None:
        self.gross_leverage = gross_leverage

    def construct(self, scores: pd.Series, context: PortfolioContext) -> pd.Series:
        names = scores.dropna().index
        if len(names) == 0:
            return pd.Series(dtype=float)
        return pd.Series(self.gross_leverage / len(names), index=names)


class SingleAssetLong(IPortfolioConstructor):
    def __init__(self, symbol: str = "BTCUSDT") -> None:
        self.symbol = symbol

    def construct(self, scores: pd.Series, context: PortfolioContext) -> pd.Series:
        if self.symbol not in scores.dropna().index:
            return pd.Series(dtype=float)
        return pd.Series({self.symbol: 1.0})
