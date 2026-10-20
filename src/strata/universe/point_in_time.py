"""Point-in-time universe: what was actually tradeable and liquid on each date."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from strata.domain.interfaces import IUniverseProvider
from strata.domain.panel import MarketPanel


class LiquidityUniverse(IUniverseProvider):
    """Top-N symbols by trailing average quote volume among listed, seasoned contracts.

    Row ``d`` uses quote volume of bars ``(d - lookback, d]`` and the listing date only, so it
    is known at the close of ``d``. Delisted contracts drop out once their bars stop and are
    never removed retroactively.
    """

    def __init__(
        self,
        top_n: int = 50,
        lookback_days: int = 30,
        min_age_days: int = 60,
        min_avg_quote_volume: float = 5_000_000.0,
        exclude: Iterable[str] = (),
    ) -> None:
        self.top_n = top_n
        self.lookback_days = lookback_days
        self.min_age_days = min_age_days
        self.min_avg_quote_volume = min_avg_quote_volume
        self.exclude = frozenset(exclude)

    def average_volume(self, panel: MarketPanel) -> pd.DataFrame:
        min_periods = max(1, int(self.lookback_days * 0.8))
        return panel.quote_volume.rolling(self.lookback_days, min_periods=min_periods).mean()

    def membership(self, panel: MarketPanel) -> pd.DataFrame:
        adv = self.average_volume(panel)
        dates = panel.dates
        onboard = panel.onboard_date.reindex(panel.close.columns)
        age_days = pd.DataFrame(
            {
                sym: (dates - onboard[sym]).days if pd.notna(onboard[sym]) else -1
                for sym in panel.close.columns
            },
            index=dates,
        )
        eligible = (
            panel.close.notna()
            & (age_days >= self.min_age_days)
            & (adv >= self.min_avg_quote_volume)
        )
        if self.exclude:
            excluded = [c for c in panel.close.columns if c in self.exclude]
            eligible.loc[:, excluded] = False
        ranks = adv.where(eligible).rank(axis=1, ascending=False, method="first")
        return (ranks <= self.top_n).fillna(False).astype(bool)
