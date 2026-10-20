"""Daily paper-trading run (CLI-driven): refresh data -> DB ingest -> paper cycle -> report."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx
import pandas as pd

from strata.config import ExchangeSettings, PaperSettings
from strata.data.panel_builder import build_panel
from strata.infra import container
from strata.infra.ingest import ingest_market, record_signal
from strata.notify.messages import (
    daily_message,
    data_refresh_failed,
    data_refresh_partial,
    paper_stale,
    rebalance_message,
    reconciliation_message,
    weekly_message,
)
from strata.notify.telegram import INotifier
from strata.paper.trader import StaleDataError, reconcile

logger = logging.getLogger(__name__)


async def refresh_market_data(notifier: INotifier) -> dict[str, int]:
    exchange = ExchangeSettings()
    timeout = httpx.Timeout(exchange.request_timeout_s)
    try:
        async with (
            httpx.AsyncClient(timeout=timeout) as vh,
            httpx.AsyncClient(timeout=timeout) as rh,
        ):
            result = await container.history_loader(vh, rh).refresh()
        rows = await ingest_market(container.sessions(), container.store())
    except Exception as exc:
        await notifier.send(data_refresh_failed(f"{type(exc).__name__}: {exc}"))
        raise
    if result.failed:
        await notifier.send(data_refresh_partial(len(result.failed)))
    return {"symbols": result.symbols, "failed": len(result.failed), "db_rows": rows}


async def paper_cycle(today: date, notifier: INotifier) -> dict[str, Any]:
    settings = PaperSettings()
    trader, spec = container.paper_trader()
    try:
        report = await trader.cycle(today)
    except StaleDataError as exc:
        await notifier.send(paper_stale(str(exc)))
        return {"status": "stale"}
    if not report.processed:
        return {"status": "noop"}
    await notifier.send(daily_message(report, settings.initial_equity))
    if report.rebalanced and report.signal_date is not None:
        await notifier.send(rebalance_message(report, spec.name))
        adv, scores = container.signal_snapshot(
            spec, build_panel(container.store()), pd.Timestamp(report.signal_date, tz="UTC")
        )
        await record_signal(
            container.sessions(),
            strategy=spec.name,
            signal_date=report.signal_date,
            universe_adv=adv,
            factor_scores=scores,
        )
    curve = await trader.repository.equity_curve(settings.account)
    if today.weekday() == 0 and len(curve) >= 8:
        await notifier.send(weekly_message(curve, settings.initial_equity))
        rec = reconcile(
            spec.build_backtester(), build_panel(container.store()), curve, settings.initial_equity
        )
        if rec is not None:
            await notifier.send(reconciliation_message(rec, settings.reconcile_tolerance))
    return {
        "status": "ok",
        "equity": str(report.equity),
        "rebalanced": report.rebalanced,
        "days": len(curve),
    }
