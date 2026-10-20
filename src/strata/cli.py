"""Command-line entry point: ``strata <command>``."""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path

import httpx

from strata.config import DataSettings, ExchangeSettings, ResearchSettings
from strata.data.binance_rest import BinanceUsdmAdapter
from strata.data.binance_vision import BinanceVisionClient
from strata.data.loader import HistoryLoader
from strata.data.store import ParquetStore
from strata.research.pipeline import TRAIN_END, TRAIN_START, ResearchPipeline

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


RESEARCH_DIR = Path("docs/research")


def _pipeline(random_runs: int | None = None) -> ResearchPipeline:
    data = DataSettings()
    research = ResearchSettings()
    return ResearchPipeline(
        data.root_dir,
        RESEARCH_DIR,
        research.artifacts_dir,
        random_runs=random_runs or research.random_signal_runs,
        seed=research.seed,
        workers=research.workers,
    )


def _research(step: str, random_runs: int | None) -> int:
    pipeline = _pipeline(random_runs)
    steps = {
        "train": pipeline.train,
        "robustness": pipeline.robustness,
        "freeze": pipeline.freeze,
        "holdout": pipeline.holdout,
    }
    path = steps[step]()
    logger.info("research %s done: %s", step, path)
    return 0


def _backtest(spec_name: str) -> int:
    pipeline = _pipeline()
    spec = next((s for s in pipeline.grid if s.name == spec_name), None)
    if spec is None:
        logger.error("unknown spec %r; choose from %s", spec_name, [s.name for s in pipeline.grid])
        return 2
    out = pipeline.runner().run(spec, TRAIN_START, TRAIN_END, label="train")
    logger.info("%s train metrics: %s", spec.name, out.metrics.as_dict())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="strata")
    parser.add_argument("--log-level", default="INFO")
    sub = parser.add_subparsers(dest="command", required=True)
    dl = sub.add_parser("download-history", help="download/refresh klines and funding history")
    dl.add_argument("--symbols", nargs="*", default=None, help="limit to these symbols")
    rs = sub.add_parser("research", help="run a step of the pre-registered research protocol")
    rs.add_argument("step", choices=["train", "robustness", "freeze", "holdout"])
    rs.add_argument("--random-runs", type=int, default=None)
    bt = sub.add_parser("backtest", help="backtest one grid spec on the train period (logged)")
    bt.add_argument("--spec", default="all_six")
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
    if args.command == "research":
        return _research(args.step, args.random_runs)
    if args.command == "backtest":
        return _backtest(args.spec)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
