"""Wide, date-by-symbol market data used by the research layer.

Timing convention (enforced by tests):

* Row ``d`` of every field describes the daily bar ``[d 00:00, d+1 00:00)`` UTC and is
  known only after ``d+1 00:00``. A signal stamped ``d`` may use rows ``<= d`` only.
* ``funding`` row ``d`` is the sum of funding rates settled in ``(d 00:00, d+1 00:00]``,
  i.e. the payments a position held over bar ``d`` (opened just after ``d 00:00``) incurs.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

import pandas as pd


@dataclass(frozen=True)
class MarketPanel:
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    quote_volume: pd.DataFrame
    funding: pd.DataFrame
    onboard_date: pd.Series  # symbol -> first trading date (Timestamp)

    def __post_init__(self) -> None:
        index = self.close.index
        columns = self.close.columns
        if not isinstance(index, pd.DatetimeIndex) or not index.is_monotonic_increasing:
            raise ValueError("panel index must be an increasing DatetimeIndex")
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, pd.DataFrame) and (
                not value.index.equals(index) or not value.columns.equals(columns)
            ):
                raise ValueError(f"field {f.name!r} is not aligned with close")

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.close.index)

    @property
    def symbols(self) -> list[str]:
        return [str(c) for c in self.close.columns]

    def returns(self) -> pd.DataFrame:
        """Close-to-close simple returns stamped at the bar where they are realised."""
        return self.close.pct_change(fill_method=None)

    def open_to_open_returns(self) -> pd.DataFrame:
        """Return earned by holding from ``open[d]`` to ``open[d+1]``, stamped at ``d``.

        Row ``d`` uses ``open[d+1]`` and therefore is only known at the end of bar ``d``.
        """
        return self.open.shift(-1) / self.open - 1.0

    def truncate(self, end: pd.Timestamp) -> MarketPanel:
        """Panel restricted to rows ``<= end`` (used by look-ahead tests and live runs)."""
        frames = {
            f.name: getattr(self, f.name).loc[:end]
            for f in fields(self)
            if isinstance(getattr(self, f.name), pd.DataFrame)
        }
        return replace(self, **frames)

    def select(self, start: pd.Timestamp | None, end: pd.Timestamp | None) -> MarketPanel:
        frames = {
            f.name: getattr(self, f.name).loc[start:end]
            for f in fields(self)
            if isinstance(getattr(self, f.name), pd.DataFrame)
        }
        return replace(self, **frames)
