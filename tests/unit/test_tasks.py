from datetime import date
from decimal import Decimal

import pytest

from strata.config import TelegramSettings
from strata.infra import tasks
from strata.infra.celery_app import QUEUE_NOTIFY, QUEUE_PAPER, app
from strata.notify.messages import weekly_message
from strata.paper.repository import EquityPoint

D = Decimal


def test_routes_and_schedule() -> None:
    routes = app.conf.task_routes
    assert routes["strata.paper_cycle"]["queue"] == QUEUE_PAPER
    assert routes["strata.notify"]["queue"] == QUEUE_NOTIFY
    assert "daily-refresh-and-paper-cycle" in app.conf.beat_schedule


def test_notify_is_noop_without_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    # Never read the developer's real .env token in tests.
    monkeypatch.setattr(tasks, "TelegramSettings", lambda: TelegramSettings(_env_file=None))
    assert tasks.notify.run("<b>x</b>") is False


def test_weekly_message() -> None:
    curve = [
        EquityPoint(date(2026, 10, d), D(3000 + 10 * d), D("-0.5"), D(0), D(3000))
        for d in range(1, 10)
    ]
    msg = weekly_message(curve, D(3000))
    assert "Итоги недели" in msg and "Дней paper-trading: 9" in msg


def test_backfill_days() -> None:
    assert tasks.backfill_days(date(2026, 1, 30), date(2026, 2, 1)) == [
        "2026-01-30",
        "2026-01-31",
        "2026-02-01",
    ]
