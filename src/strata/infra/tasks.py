"""Celery tasks. Pipeline: refresh_data (data) -> paper_cycle (paper) -> notify (notify)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

import httpx

from strata.config import ExchangeSettings, PaperSettings, TelegramSettings
from strata.data.panel_builder import build_panel
from strata.infra import container
from strata.infra.celery_app import app
from strata.notify.messages import (
    daily_message,
    data_refresh_failed,
    data_refresh_partial,
    paper_stale,
    rebalance_message,
    reconciliation_message,
    weekly_message,
)
from strata.notify.telegram import TelegramNotifier
from strata.paper.trader import StaleDataError, reconcile

logger = logging.getLogger(__name__)


def _today() -> date:
    return datetime.now(UTC).date()


def _notify(html: str) -> None:
    notify.delay(html)


@app.task(name="strata.notify", autoretry_for=(RuntimeError,), retry_backoff=True, max_retries=5)
def notify(html: str) -> bool:
    settings = TelegramSettings()
    if not settings.enabled:
        logger.info("telegram disabled; message dropped")
        return False

    async def _send() -> bool:
        async with httpx.AsyncClient(timeout=20) as client:
            return await TelegramNotifier(client, settings).send(html)

    if not asyncio.run(_send()):
        raise RuntimeError("telegram send failed")
    return True


@app.task(name="strata.refresh_data", bind=True, max_retries=3, default_retry_delay=600)
def refresh_data(self: object, run_paper: bool = True) -> dict[str, int]:
    exchange = ExchangeSettings()

    async def _run() -> dict[str, int]:
        timeout = httpx.Timeout(exchange.request_timeout_s)
        async with (
            httpx.AsyncClient(timeout=timeout) as vh,
            httpx.AsyncClient(timeout=timeout) as rh,
        ):
            result = await container.history_loader(vh, rh).refresh()
        return {"symbols": result.symbols, "failed": len(result.failed)}

    try:
        summary = asyncio.run(_run())
    except Exception as exc:
        _notify(data_refresh_failed(f"{type(exc).__name__}: {exc}"))
        raise
    if summary["failed"]:
        _notify(data_refresh_partial(summary["failed"]))
    if run_paper:
        paper_cycle.delay(_today().isoformat())
    return summary


@app.task(name="strata.paper_cycle")
def paper_cycle(today_iso: str | None = None) -> dict[str, object]:
    today = date.fromisoformat(today_iso) if today_iso else _today()
    settings = PaperSettings()
    trader, spec = container.paper_trader()

    async def _run() -> dict[str, object]:
        try:
            report = await trader.cycle(today)
        except StaleDataError as exc:
            _notify(paper_stale(str(exc)))
            return {"status": "stale"}
        if not report.processed:
            return {"status": "noop"}
        _notify(daily_message(report, settings.initial_equity))
        if report.rebalanced:
            _notify(rebalance_message(report, spec.name))
        curve = await trader.repository.equity_curve(settings.account)
        if today.weekday() == 0 and len(curve) >= 8:
            _notify(weekly_message(curve, settings.initial_equity))
            panel = build_panel(container.store())
            rec = reconcile(spec.build_backtester(), panel, curve, settings.initial_equity)
            if rec is not None:
                _notify(reconciliation_message(rec, settings.reconcile_tolerance))
        return {
            "status": "ok",
            "equity": str(report.equity),
            "rebalanced": report.rebalanced,
            "days": len(curve),
        }

    return asyncio.run(_run())


def backfill_days(start: date, end: date) -> list[str]:
    """Dates to replay with ``paper_cycle`` (inclusive), e.g. after downtime."""
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
