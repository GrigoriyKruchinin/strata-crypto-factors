"""Celery application: queues per role and the daily schedule (UTC)."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from strata.config import RedisSettings

QUEUE_DATA = "data"
QUEUE_PAPER = "paper"
QUEUE_NOTIFY = "notify"

app = Celery("strata", broker=RedisSettings().url, include=["strata.infra.tasks"])
app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue=QUEUE_DATA,
    task_routes={
        "strata.refresh_data": {"queue": QUEUE_DATA},
        "strata.paper_cycle": {"queue": QUEUE_PAPER},
        "strata.notify": {"queue": QUEUE_NOTIFY},
    },
    # Daily bars close at 00:00 UTC; give the exchange a few minutes to publish them.
    beat_schedule={
        "daily-refresh-and-paper-cycle": {
            "task": "strata.refresh_data",
            "schedule": crontab(hour=0, minute=15),
        },
    },
)
