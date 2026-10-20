"""Client for the free bulk archive at data.binance.vision (USDT-M futures).

The archive keeps files for delisted contracts, which is what makes a survivorship-free
universe possible. Every downloaded archive is verified against its published SHA-256.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import StrEnum

import httpx

from strata.data.http import get_optional, get_with_retry

_S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
_MONTH_RE = re.compile(r"-(\d{4})-(\d{2})\.zip$")
DEFAULT_LISTING_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"


class VisionDataset(StrEnum):
    KLINES = "klines"
    FUNDING = "fundingRate"


@dataclass(frozen=True, slots=True)
class MonthlyFile:
    symbol: str
    dataset: VisionDataset
    year: int
    month: int
    url: str

    @property
    def period(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


class ChecksumMismatchError(RuntimeError):
    pass


class BinanceVisionClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str = "https://data.binance.vision",
        listing_url: str = DEFAULT_LISTING_URL,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._listing_url = listing_url

    @staticmethod
    def _prefix(dataset: VisionDataset, symbol: str = "", interval: str = "1d") -> str:
        root = f"data/futures/um/monthly/{dataset.value}/"
        if not symbol:
            return root
        if dataset is VisionDataset.KLINES:
            return f"{root}{symbol}/{interval}/"
        return f"{root}{symbol}/"

    async def _list(self, prefix: str, *, delimiter: bool) -> tuple[list[str], list[str]]:
        """Return (keys, common prefixes) under ``prefix``, following S3 pagination."""
        keys: list[str] = []
        prefixes: list[str] = []
        marker = ""
        while True:
            params = {"prefix": prefix, "marker": marker}
            if delimiter:
                params["delimiter"] = "/"
            response = await get_with_retry(self._client, self._listing_url, params=params)
            root = ET.fromstring(response.content)  # noqa: S314 - trusted endpoint
            keys += [e.text or "" for e in root.findall("s3:Contents/s3:Key", _S3_NS)]
            prefixes += [e.text or "" for e in root.findall("s3:CommonPrefixes/s3:Prefix", _S3_NS)]
            truncated = (root.findtext("s3:IsTruncated", "false", _S3_NS) or "").lower() == "true"
            if not truncated:
                return keys, prefixes
            marker = root.findtext("s3:NextMarker", "", _S3_NS) or (keys or prefixes)[-1]

    async def list_symbols(self, dataset: VisionDataset = VisionDataset.KLINES) -> list[str]:
        _, prefixes = await self._list(self._prefix(dataset), delimiter=True)
        return sorted(p.rstrip("/").rsplit("/", 1)[-1] for p in prefixes)

    async def list_monthly_files(
        self, symbol: str, dataset: VisionDataset, interval: str = "1d"
    ) -> list[MonthlyFile]:
        keys, _ = await self._list(self._prefix(dataset, symbol, interval), delimiter=False)
        files: list[MonthlyFile] = []
        for key in keys:
            match = _MONTH_RE.search(key)
            if match is None:
                continue
            files.append(
                MonthlyFile(
                    symbol=symbol,
                    dataset=dataset,
                    year=int(match.group(1)),
                    month=int(match.group(2)),
                    url=f"{self._base_url}/{key}",
                )
            )
        return sorted(files, key=lambda f: (f.year, f.month))

    async def download_verified(self, url: str) -> bytes:
        response = await get_with_retry(self._client, url)
        checksum = await get_optional(self._client, f"{url}.CHECKSUM")
        payload = response.content
        if checksum is not None:
            expected = checksum.text.split()[0].strip().lower()
            actual = hashlib.sha256(payload).hexdigest()
            if actual != expected:
                raise ChecksumMismatchError(f"{url}: sha256 {actual} != {expected}")
        return payload
