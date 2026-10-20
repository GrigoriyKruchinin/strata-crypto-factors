"""Shared test builders."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from strata.data.store import ParquetStore, Table
from strata.domain.panel import MarketPanel

DAY_MS = 86_400_000


def zip_csv(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, text)
    return buf.getvalue()


def kline_csv(start_ms: int, closes: list[float], header: bool = False) -> str:
    lines = []
    if header:
        lines.append(
            "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
            "taker_buy_volume,taker_buy_quote_volume,ignore"
        )
    for i, c in enumerate(closes):
        t = start_ms + i * DAY_MS
        lines.append(
            f"{t},{c},{c * 1.01},{c * 0.99},{c},10,{t + DAY_MS - 1},{c * 10},5,5,{c * 5},0"
        )
    return "\n".join(lines) + "\n"


def synthetic_panel(
    n_days: int = 300,
    n_symbols: int = 12,
    seed: int = 7,
    start: str = "2021-01-01",
) -> MarketPanel:
    """Random-walk market with staggered listings and one delisting, for unit tests."""
    rng = np.random.default_rng(seed)
    index = pd.date_range(start, periods=n_days, freq="D", tz="UTC")
    symbols = [f"C{i:02d}USDT" for i in range(n_symbols)]
    market = rng.normal(0, 0.03, n_days)
    rets = market[:, None] * rng.uniform(0.5, 1.5, n_symbols) + rng.normal(
        0, 0.04, (n_days, n_symbols)
    )
    close = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=index, columns=symbols)
    # Staggered listings: symbol i lists on day 10*i (first five trade from day 0).
    for i, sym in enumerate(symbols):
        listed = max(0, 10 * (i - 4))
        close.loc[index[:listed], sym] = np.nan
    # Last symbol delists two thirds of the way through.
    close.loc[index[2 * n_days // 3 :], symbols[-1]] = np.nan
    open_ = close.shift(1).fillna(close)
    open_ = open_.where(close.notna())
    volume = pd.DataFrame(
        rng.lognormal(16, 1, (n_days, n_symbols)), index=index, columns=symbols
    ).where(close.notna())
    funding = pd.DataFrame(
        rng.normal(0.0002, 0.0003, (n_days, n_symbols)), index=index, columns=symbols
    ).where(close.notna())
    onboard = close.apply(lambda s: s.first_valid_index())
    return MarketPanel(
        open=open_,
        high=open_.where(open_ > close, close) * 1.01,
        low=open_.where(open_ < close, close) * 0.99,
        close=close,
        quote_volume=volume,
        funding=funding,
        onboard_date=pd.Series(onboard, dtype="datetime64[ns, UTC]"),
    )


def write_store(panel: MarketPanel, root: Path) -> ParquetStore:
    store = ParquetStore(root)
    for sym in panel.symbols:
        traded = panel.close[sym].notna()
        idx = panel.dates[traded]
        store.write_table(
            Table.KLINES_1D,
            sym,
            pd.DataFrame(
                {
                    "open_time": idx,
                    "open": panel.open.loc[idx, sym].to_numpy(),
                    "high": panel.high.loc[idx, sym].to_numpy(),
                    "low": panel.low.loc[idx, sym].to_numpy(),
                    "close": panel.close.loc[idx, sym].to_numpy(),
                    "volume": 1.0,
                    "quote_volume": panel.quote_volume.loc[idx, sym].to_numpy(),
                    "trades": 1,
                }
            ),
        )
        store.write_table(
            Table.FUNDING,
            sym,
            pd.DataFrame(
                {
                    "funding_time": idx + pd.Timedelta(hours=8),
                    "rate": panel.funding.loc[idx, sym].to_numpy(),
                }
            ),
        )
    return store
