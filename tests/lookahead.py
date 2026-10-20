"""Reusable no-look-ahead assertions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, replace

import numpy as np
import pandas as pd

from strata.domain.panel import MarketPanel


def _scramble_after(panel: MarketPanel, cut: pd.Timestamp, seed: int = 0) -> MarketPanel:
    rng = np.random.default_rng(seed)
    out: dict[str, pd.DataFrame] = {}
    for f in fields(panel):
        frame = getattr(panel, f.name)
        if isinstance(frame, pd.DataFrame):
            frame = frame.copy()
            future = frame.index > cut
            noise = rng.lognormal(0, 1, frame.loc[future].shape)
            frame.loc[future] = frame.loc[future].to_numpy() * noise
            out[f.name] = frame
    return replace(panel, **out)  # type: ignore[arg-type]  # only DataFrame fields


def assert_no_lookahead(
    compute: Callable[[MarketPanel], pd.DataFrame], panel: MarketPanel, n_cuts: int = 4
) -> None:
    """Rows ``<= t`` must not change when data after ``t`` is removed or scrambled."""
    full = compute(panel)
    dates = panel.dates
    cuts = dates[np.linspace(len(dates) // 4, len(dates) - 2, n_cuts).astype(int)]
    for cut in cuts:
        truncated = compute(panel.truncate(cut))
        pd.testing.assert_frame_equal(
            full.loc[:cut], truncated.loc[:cut], check_dtype=False, check_freq=False
        )
        scrambled = compute(_scramble_after(panel, cut))
        pd.testing.assert_frame_equal(
            full.loc[:cut], scrambled.loc[:cut], check_dtype=False, check_freq=False
        )
