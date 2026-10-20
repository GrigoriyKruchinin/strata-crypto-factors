import pandas as pd

from strata.data.panel_builder import funding_day
from strata.data.parsing import (
    parse_funding_rows,
    parse_funding_zip,
    parse_kline_rows,
    parse_kline_zip,
)
from tests.helpers import kline_csv, zip_csv

START = 1577836800000  # 2020-01-01


def test_kline_zip_without_and_with_header_are_equal() -> None:
    a = parse_kline_zip(zip_csv("a.csv", kline_csv(START, [1.0, 2.0, 3.0])))
    b = parse_kline_zip(zip_csv("b.csv", kline_csv(START, [1.0, 2.0, 3.0], header=True)))
    pd.testing.assert_frame_equal(a, b)
    assert list(a["close"]) == [1.0, 2.0, 3.0]
    assert a["open_time"].iloc[0] == pd.Timestamp("2020-01-01", tz="UTC")


def test_kline_rows_dedup_and_sort() -> None:
    rows = [
        [START + 86_400_000, "2", "2", "2", "2", "1", 0, "20", 1, "0", "0", "0"],
        [START, "1", "1", "1", "1", "1", 0, "10", 1, "0", "0", "0"],
        [START, "1", "1", "1", "1", "1", 0, "10", 1, "0", "0", "0"],
    ]
    frame = parse_kline_rows(rows)
    assert list(frame["close"]) == [1.0, 2.0]


def test_funding_zip_snaps_jitter_to_minute() -> None:
    text = "calc_time,funding_interval_hours,last_funding_rate\n1577923200002,8,0.0001\n"
    frame = parse_funding_zip(zip_csv("f.csv", text))
    assert frame["funding_time"].iloc[0] == pd.Timestamp("2020-01-02", tz="UTC")


def test_funding_rows() -> None:
    frame = parse_funding_rows([{"fundingTime": 1577865600000, "fundingRate": "-0.0002"}])
    assert frame["rate"].iloc[0] == -0.0002


def test_midnight_settlement_belongs_to_previous_bar() -> None:
    times = pd.Series(
        pd.to_datetime(
            ["2020-01-02 00:00", "2020-01-01 08:00", "2020-01-01 16:00", "2020-01-02 08:00"],
            utc=True,
        )
    )
    days = funding_day(times)
    expected = pd.to_datetime(["2020-01-01", "2020-01-01", "2020-01-01", "2020-01-02"], utc=True)
    assert list(days) == list(expected)
