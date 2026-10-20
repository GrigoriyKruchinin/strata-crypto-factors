"""Command-line entry point: ``strata <command>``."""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence

import httpx

from strata.config import DataSettings, ExchangeSettings
from strata.data.binance_rest import BinanceUsdmAdapter
from strata.data.binance_vision import BinanceVisionClient
from strata.data.loader import HistoryLoader
from strata.data.store import ParquetStore

logger = logging.getLogger("strata")


async def _download_history(symbols: Sequence[str] | None) -> int:
    data = DataSettings()
    exchange = ExchangeSettings()
    store = ParquetStore(data.root_dir)
    timeout = httpx.Timeout(exchange.request_timeout_s)
    async with (
        httpx.AsyncClient(timeout=timeout) as vision_http,
        httpx.AsyncClient(timeout=timeout) as rest_http,
    ):
        loader = HistoryLoader(
            BinanceVisionClient(vision_http, exchange.vision_base_url),
            BinanceUsdmAdapter(rest_http, exchange.rest_base_url, exchange.max_requests_per_minute),
            store,
            history_start=data.history_start,
            quote_asset=data.quote_asset,
            concurrency=data.download_concurrency,
        )
        result = await loader.run(only=symbols)
    report_path = data.root_dir / "quality_report.json"
    result.quality.save(report_path)
    logger.info(
        "symbols=%d downloaded=%d cached=%d failed=%d quality=%s report=%s",
        result.symbols,
        result.downloaded_files,
        result.cached_files,
        len(result.failed),
        result.quality.summary(),
        report_path,
    )
    return 1 if result.failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="strata")
    parser.add_argument("--log-level", default="INFO")
    sub = parser.add_subparsers(dest="command", required=True)
    dl = sub.add_parser("download-history", help="download/refresh klines and funding history")
    dl.add_argument("--symbols", nargs="*", default=None, help="limit to these symbols")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.command == "download-history":
        return asyncio.run(_download_history(args.symbols))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
