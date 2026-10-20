"""Build a ``MarketPanel`` from the parquet store."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from strata.data.store import ParquetStore, Table
from strata.domain.panel import MarketPanel


def funding_day(times: pd.Series) -> pd.Series:
    """Bar date a settlement belongs to: settlement in ``(d, d+1]`` -> ``d``."""
    return (times - pd.Timedelta(1, "ns")).dt.floor("D")


def build_panel(
    store: ParquetStore,
    symbols: Iterable[str] | None = None,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> MarketPanel:
    names = list(symbols) if symbols is not None else store.symbols(Table.KLINES_1D)
    fields: dict[str, dict[str, pd.Series]] = {
        k: {} for k in ("open", "high", "low", "close", "quote_volume", "funding")
    }
    onboard: dict[str, pd.Timestamp] = {}
    for symbol in names:
        klines = store.read_table(Table.KLINES_1D, symbol)
        if klines is None or klines.empty:
            continue
        # The archive keeps emitting flat zero-volume bars after a delisting (sometimes for
        # years); a bar nobody traded is not a tradeable bar.
        klines = klines.loc[klines["quote_volume"] > 0]
        if klines.empty:
            continue
        indexed = klines.set_index(pd.DatetimeIndex(klines["open_time"]).tz_convert("UTC"))
        for col in ("open", "high", "low", "close", "quote_volume"):
            fields[col][symbol] = indexed[col].astype("float64")
        onboard[symbol] = pd.Timestamp(indexed.index.min())
        funding = store.read_table(Table.FUNDING, symbol)
        if funding is not None and not funding.empty:
            fields["funding"][symbol] = (
                funding.groupby(funding_day(funding["funding_time"]))["rate"]
                .sum()
                .astype("float64")
            )
    if store.instruments_path.exists():
        meta = store.read_instruments().set_index("symbol")["onboard_time"].dropna()
        onboard.update({str(k): pd.Timestamp(v) for k, v in meta.items() if k in onboard})
    frames = {k: pd.DataFrame(v) for k, v in fields.items()}
    index = frames["close"].index.sort_values()
    columns = frames["close"].columns
    full_index = (
        pd.date_range(index.min(), index.max(), freq="D", tz="UTC") if len(index) else index
    )
    aligned = {
        k: f.reindex(index=full_index, columns=columns).sort_index() for k, f in frames.items()
    }
    # Missing funding while a contract trades means "no settlement recorded"; keep NaN outside
    # the trading window so costs are never charged on bars that did not exist.
    traded = aligned["close"].notna()
    aligned["funding"] = aligned["funding"].fillna(0.0).where(traded)
    panel = MarketPanel(
        open=aligned["open"],
        high=aligned["high"],
        low=aligned["low"],
        close=aligned["close"],
        quote_volume=aligned["quote_volume"],
        funding=aligned["funding"],
        onboard_date=pd.Series(onboard, dtype="datetime64[ns, UTC]"),
    )
    if start is not None or end is not None:
        panel = panel.select(start, end)
    return panel
