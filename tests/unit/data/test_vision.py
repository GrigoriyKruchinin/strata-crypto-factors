import hashlib

import httpx
import pytest
import respx

from strata.data.binance_vision import (
    DEFAULT_LISTING_URL,
    BinanceVisionClient,
    ChecksumMismatchError,
    VisionDataset,
)

NS = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"'


def _listing(prefixes: list[str], keys: list[str], truncated: bool, marker: str = "") -> str:
    p = "".join(f"<CommonPrefixes><Prefix>{x}</Prefix></CommonPrefixes>" for x in prefixes)
    k = "".join(f"<Contents><Key>{x}</Key></Contents>" for x in keys)
    nm = f"<NextMarker>{marker}</NextMarker>" if marker else ""
    return (
        f"<ListBucketResult {NS}><IsTruncated>{str(truncated).lower()}</IsTruncated>{nm}{p}{k}"
        "</ListBucketResult>"
    )


@respx.mock
async def test_list_symbols_follows_pagination() -> None:
    root = "data/futures/um/monthly/klines/"
    route = respx.get(DEFAULT_LISTING_URL)
    route.side_effect = [
        httpx.Response(200, text=_listing([f"{root}AUSDT/"], [], True, f"{root}AUSDT/")),
        httpx.Response(200, text=_listing([f"{root}BUSDT/"], [], False)),
    ]
    async with httpx.AsyncClient() as http:
        symbols = await BinanceVisionClient(http).list_symbols()
    assert symbols == ["AUSDT", "BUSDT"]
    assert route.calls[1].request.url.params["marker"] == f"{root}AUSDT/"


@respx.mock
async def test_list_monthly_files_parses_periods() -> None:
    base = "data/futures/um/monthly/fundingRate/XUSDT/"
    keys = [f"{base}XUSDT-fundingRate-2021-02.zip", f"{base}XUSDT-fundingRate-2021-02.zip.CHECKSUM"]
    respx.get(DEFAULT_LISTING_URL).mock(
        return_value=httpx.Response(200, text=_listing([], keys, False))
    )
    async with httpx.AsyncClient() as http:
        files = await BinanceVisionClient(http).list_monthly_files("XUSDT", VisionDataset.FUNDING)
    assert [f.period for f in files] == ["2021-02"]


@respx.mock
async def test_download_verifies_checksum() -> None:
    url = "https://data.binance.vision/x.zip"
    payload = b"zipbytes"
    good = hashlib.sha256(payload).hexdigest()
    respx.get(url).mock(return_value=httpx.Response(200, content=payload))
    respx.get(f"{url}.CHECKSUM").mock(return_value=httpx.Response(200, text=f"{good}  x.zip"))
    async with httpx.AsyncClient() as http:
        assert await BinanceVisionClient(http).download_verified(url) == payload

    respx.get(f"{url}.CHECKSUM").mock(return_value=httpx.Response(200, text=f"{'0' * 64}  x.zip"))
    async with httpx.AsyncClient() as http:
        with pytest.raises(ChecksumMismatchError):
            await BinanceVisionClient(http).download_verified(url)
