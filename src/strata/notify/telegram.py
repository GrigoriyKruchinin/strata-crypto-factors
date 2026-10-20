"""Telegram Bot API notifier (HTML parse mode). The token never appears in logs."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import httpx

from strata.config import TelegramSettings

logger = logging.getLogger(__name__)

MAX_MESSAGE = 4096


class INotifier(ABC):
    @abstractmethod
    async def send(self, html: str) -> bool: ...


class NullNotifier(INotifier):
    """Used when Telegram is not configured; keeps messages for inspection/tests."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, html: str) -> bool:
        self.sent.append(html)
        return True


class TelegramNotifier(INotifier):
    def __init__(self, client: httpx.AsyncClient, settings: TelegramSettings) -> None:
        self._client = client
        self._settings = settings

    async def send(self, html: str) -> bool:
        token = self._settings.bot_token.get_secret_value()
        url = f"{self._settings.api_base_url}/bot{token}/sendMessage"
        ok = True
        for chunk in _chunks(html):
            try:
                response = await self._client.post(
                    url,
                    json={
                        "chat_id": self._settings.chat_id,
                        "text": chunk,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                if response.status_code != 200:
                    ok = False
                    logger.error("telegram send failed: HTTP %s", response.status_code)
            except httpx.HTTPError as exc:  # never log the URL: it contains the token
                ok = False
                logger.error("telegram send failed: %s", type(exc).__name__)
        return ok


def _chunks(text: str) -> list[str]:
    if len(text) <= MAX_MESSAGE:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > MAX_MESSAGE:
            parts.append(current)
            current = ""
        current += line
    if current:
        parts.append(current)
    return parts
