"""Parsers for Binance kline / funding payloads (data.binance.vision CSVs and REST JSON)."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence
from typing import Any

import pandas as pd

KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
]
KLINE_FRAME_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "trades",
]
FUNDING_FRAME_COLUMNS = ["funding_time", "rate"]


def _read_zipped_csv(payload: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected exactly one CSV in archive, got {names}")
        return zf.read(names[0])


def _has_header(raw: bytes) -> bool:
    first = raw.split(b"\n", 1)[0].strip()
    return bool(first) and not first[:1].isdigit()


def _to_utc(ms: pd.Series) -> pd.Series:
    return pd.to_datetime(ms.astype("int64"), unit="ms", utc=True)


def empty_klines() -> pd.DataFrame:
    frame = pd.DataFrame({c: pd.Series(dtype="float64") for c in KLINE_FRAME_COLUMNS})
    frame["open_time"] = pd.Series(dtype="datetime64[ns, UTC]")
    frame["trades"] = pd.Series(dtype="int64")
    return frame


def empty_funding() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "funding_time": pd.Series(dtype="datetime64[ns, UTC]"),
            "rate": pd.Series(dtype="float64"),
        }
    )


def parse_kline_zip(payload: bytes) -> pd.DataFrame:
    raw = _read_zipped_csv(payload)
    if not raw.strip():
        return empty_klines()
    frame = pd.read_csv(
        io.BytesIO(raw),
        header=0 if _has_header(raw) else None,
        names=KLINE_COLUMNS,
    )
    return _normalise_klines(frame)


def parse_kline_rows(rows: Sequence[Sequence[Any]]) -> pd.DataFrame:
    if not rows:
        return empty_klines()
    frame = pd.DataFrame([list(r)[: len(KLINE_COLUMNS)] for r in rows], columns=KLINE_COLUMNS)
    return _normalise_klines(frame)


def _normalise_klines(frame: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "open_time": _to_utc(frame["open_time"]),
            "open": frame["open"].astype("float64"),
            "high": frame["high"].astype("float64"),
            "low": frame["low"].astype("float64"),
            "close": frame["close"].astype("float64"),
            "volume": frame["volume"].astype("float64"),
            "quote_volume": frame["quote_volume"].astype("float64"),
            "trades": frame["trades"].astype("int64"),
        }
    )
    return out.sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)


def parse_funding_zip(payload: bytes) -> pd.DataFrame:
    raw = _read_zipped_csv(payload)
    if not raw.strip():
        return empty_funding()
    has_header = _has_header(raw)
    frame = pd.read_csv(
        io.BytesIO(raw),
        header=0 if has_header else None,
        names=None if has_header else ["calc_time", "funding_interval_hours", "last_funding_rate"],
    )
    return _normalise_funding(frame["calc_time"], frame["last_funding_rate"])


def parse_funding_rows(rows: Sequence[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return empty_funding()
    frame = pd.DataFrame(rows)
    return _normalise_funding(frame["fundingTime"], frame["fundingRate"])


def _normalise_funding(times: pd.Series, rates: pd.Series) -> pd.DataFrame:
    # Settlement timestamps carry a few ms of jitter (e.g. 00:00:00.002); snap to the minute
    # so a midnight settlement is attributed to the bar that ends at midnight.
    out = pd.DataFrame(
        {
            "funding_time": _to_utc(times).dt.round("min"),
            "rate": rates.astype("float64"),
        }
    )
    return out.sort_values("funding_time").drop_duplicates("funding_time").reset_index(drop=True)
