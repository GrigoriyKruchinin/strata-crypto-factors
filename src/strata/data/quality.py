"""Data quality checks: gaps, zero-volume bars, extreme moves, funding coverage."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

#: A daily move beyond this (|ret| > 80%) is flagged for review, not dropped.
EXTREME_RETURN = 0.8


@dataclass(frozen=True)
class SymbolQuality:
    symbol: str
    bars: int
    first_bar: str
    last_bar: str
    missing_days: int
    zero_volume_days: int
    extreme_moves: int
    funding_events: int
    funding_missing_days: int

    @property
    def has_issues(self) -> bool:
        return bool(self.missing_days or self.funding_missing_days)


@dataclass
class QualityReport:
    symbols: list[SymbolQuality] = field(default_factory=list)

    def add(self, item: SymbolQuality) -> None:
        self.symbols.append(item)

    def summary(self) -> dict[str, int]:
        return {
            "symbols": len(self.symbols),
            "symbols_with_gaps": sum(1 for s in self.symbols if s.missing_days),
            "missing_days_total": sum(s.missing_days for s in self.symbols),
            "zero_volume_days_total": sum(s.zero_volume_days for s in self.symbols),
            "extreme_moves_total": sum(s.extreme_moves for s in self.symbols),
            "symbols_with_funding_gaps": sum(1 for s in self.symbols if s.funding_missing_days),
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "summary": self.summary(),
            "issues": [
                asdict(s) for s in sorted(self.symbols, key=lambda s: s.symbol) if s.has_issues
            ],
        }
        path.write_text(json.dumps(payload, indent=2))


def check_symbol(symbol: str, klines: pd.DataFrame, funding: pd.DataFrame) -> SymbolQuality:
    times = pd.DatetimeIndex(klines["open_time"])
    expected = pd.date_range(times.min(), times.max(), freq="D")
    missing = len(expected.difference(times))
    returns = klines["close"].pct_change(fill_method=None).abs()
    funding_days = (
        pd.DatetimeIndex(funding["funding_time"] - pd.Timedelta(1, "ns")).floor("D").unique()
        if len(funding)
        else pd.DatetimeIndex([], tz="UTC")
    )
    funding_missing = len(expected.difference(funding_days)) if len(funding) else len(expected)
    return SymbolQuality(
        symbol=symbol,
        bars=len(klines),
        first_bar=str(times.min().date()),
        last_bar=str(times.max().date()),
        missing_days=missing,
        zero_volume_days=int((klines["quote_volume"] <= 0).sum()),
        extreme_moves=int((returns > EXTREME_RETURN).sum()),
        funding_events=len(funding),
        funding_missing_days=funding_missing,
    )
