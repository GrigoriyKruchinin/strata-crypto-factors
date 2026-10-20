from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from strata.data.binance_rest import BinanceUsdmAdapter
from strata.data.binance_vision import BinanceVisionClient, MonthlyFile, VisionDataset
from strata.data.loader import HistoryLoader
from strata.data.panel_builder import build_panel
from strata.data.parsing import parse_kline_rows
from strata.data.store import ParquetStore, Table
from tests.helpers import DAY_MS, kline_csv, zip_csv

JAN_2020 = 1577836800000
FEB_2020 = JAN_2020 + 31 * DAY_MS


class FakeVision(BinanceVisionClient):
    def __init__(self) -> None:
        super().__init__(httpx.AsyncClient())
        self.downloads = 0
        self.files: dict[str, bytes] = {
            "LIVEUSDT/klines/2020-01": zip_csv("k.csv", kline_csv(JAN_2020, [1.0] * 31)),
            "DEADUSDT/klines/2020-01": zip_csv("k.csv", kline_csv(JAN_2020, [2.0] * 10)),
            "LIVEUSDT/fundingRate/2020-01": zip_csv(
                "f.csv",
                "calc_time,funding_interval_hours,last_funding_rate\n"
                f"{JAN_2020 + 8 * 3600_000},8,0.0001\n{JAN_2020 + DAY_MS},8,0.0002\n",
            ),
        }

    async def list_symbols(self, dataset: VisionDataset = VisionDataset.KLINES) -> list[str]:
        return ["DEADUSDT", "LIVEUSDT", "LIVEUSDC", "BTCUSDT_200626", "STOCKUSDT"]

    async def list_monthly_files(
        self, symbol: str, dataset: VisionDataset, interval: str = "1d"
    ) -> list[MonthlyFile]:
        return [
            MonthlyFile(symbol, dataset, 2020, 1, f"{symbol}/{dataset.value}/2020-01")
            for key in self.files
            if key == f"{symbol}/{dataset.value}/2020-01"
        ]

    async def download_verified(self, url: str) -> bytes:
        self.downloads += 1
        return self.files[url]


class FakeRest(BinanceUsdmAdapter):
    def __init__(self) -> None:
        super().__init__(httpx.AsyncClient())

    async def exchange_info(self) -> list[dict[str, Any]]:
        base = {"contractType": "PERPETUAL", "quoteAsset": "USDT", "underlyingType": "COIN"}
        return [
            {**base, "symbol": "LIVEUSDT", "status": "TRADING", "onboardDate": JAN_2020},
            {**base, "symbol": "STOCKUSDT", "status": "TRADING", "underlyingType": "EQUITY"},
        ]

    async def fetch_kline_frame(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        assert start >= datetime(2020, 2, 1, tzinfo=UTC)
        assert end == datetime(2020, 2, 3, tzinfo=UTC)
        rows = [
            [FEB_2020 + i * DAY_MS, "3", "3", "3", "3", "1", 0, "30", 1, "0", "0", "0"]
            for i in range(2)
        ]
        frame = parse_kline_rows(rows)
        return frame.loc[frame["open_time"] >= start].reset_index(drop=True)

    async def fetch_funding_frame(
        self, symbol: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "funding_time": pd.Series(dtype="datetime64[ns, UTC]"),
                "rate": pd.Series(dtype="float64"),
            }
        )


async def test_loader_end_to_end(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    vision = FakeVision()
    loader = HistoryLoader(
        vision,
        FakeRest(),
        store,
        history_start=date(2020, 1, 1),
        now=lambda: datetime(2020, 2, 3, 12, tzinfo=UTC),
    )
    result = await loader.run()

    assert result.failed == {}
    assert store.symbols(Table.KLINES_1D) == ["DEADUSDT", "LIVEUSDT"]  # no USDC, quarterly, equity
    live = store.read_table(Table.KLINES_1D, "LIVEUSDT")
    assert live is not None and len(live) == 33  # 31 archive + 2 REST tail bars
    meta = store.read_instruments().set_index("symbol")
    assert meta.loc["DEADUSDT", "status"] == "DELISTED"
    assert meta.loc["DEADUSDT", "delist_time"] == pd.Timestamp("2020-01-11", tz="UTC")
    assert meta.loc["LIVEUSDT", "status"] == "TRADING"
    assert store.read_manifest()["data_version"]

    # Second run uses the on-disk cache (resume/checkpoint) and downloads nothing.
    downloads = vision.downloads
    again = await loader.run()
    assert vision.downloads == downloads
    assert again.downloaded_files == 0 and again.cached_files == 3

    # Flat zero-volume bars after delisting are not tradeable bars.
    dead = store.read_table(Table.KLINES_1D, "DEADUSDT")
    assert dead is not None
    dead.loc[dead.index[-3:], "quote_volume"] = 0.0
    store.write_table(Table.KLINES_1D, "DEADUSDT", dead)
    panel = build_panel(store)
    assert panel.close["DEADUSDT"].last_valid_index() == pd.Timestamp("2020-01-07", tz="UTC")
    store.write_table(Table.KLINES_1D, "DEADUSDT", dead.assign(quote_volume=20.0))
    panel = build_panel(store)
    assert panel.close["DEADUSDT"].last_valid_index() == pd.Timestamp("2020-01-10", tz="UTC")
    # Settlements at 08:00 and next midnight both belong to the 2020-01-01 bar.
    assert panel.funding.loc["2020-01-01", "LIVEUSDT"] == 0.0001 + 0.0002
    assert pd.isna(panel.funding.loc["2020-01-20", "DEADUSDT"])


async def test_refresh_appends_rest_tail(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    loader = HistoryLoader(
        FakeVision(),
        FakeRest(),
        store,
        history_start=date(2020, 1, 1),
        now=lambda: datetime(2020, 2, 3, 12, tzinfo=UTC),
    )
    await loader.run(only=["DEADUSDT"])
    assert store.symbols(Table.KLINES_1D) == ["DEADUSDT"]
    result = await loader.refresh()  # LIVEUSDT is new -> full archive + tail
    assert result.failed == {}
    live = store.read_table(Table.KLINES_1D, "LIVEUSDT")
    assert live is not None and len(live) == 33
    again = await loader.refresh()  # known symbol -> tail only, no duplicates
    assert again.failed == {}
    live = store.read_table(Table.KLINES_1D, "LIVEUSDT")
    assert live is not None and len(live) == 33
