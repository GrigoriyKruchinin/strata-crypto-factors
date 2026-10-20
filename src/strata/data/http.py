"""Shared HTTP helpers: retrying GET with exponential backoff and a weight-based rate limiter."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({418, 429, 500, 502, 503, 504})


class RateLimiter:
    """Sliding one-minute budget of request weight (Binance ``REQUEST_WEIGHT`` semantics)."""

    def __init__(self, weight_per_minute: int) -> None:
        if weight_per_minute <= 0:
            raise ValueError("weight_per_minute must be positive")
        self._capacity = weight_per_minute
        self._events: list[tuple[float, int]] = []
        self._lock = asyncio.Lock()

    async def acquire(self, weight: int = 1) -> None:
        weight = min(weight, self._capacity)
        async with self._lock:
            while True:
                now = time.monotonic()
                self._events = [(t, w) for t, w in self._events if now - t < 60.0]
                used = sum(w for _, w in self._events)
                if used + weight <= self._capacity:
                    self._events.append((now, weight))
                    return
                await asyncio.sleep(max(0.05, 60.0 - (now - self._events[0][0])))


async def _get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    attempts: int = 5,
    base_delay_s: float = 1.0,
    allow_404: bool = False,
) -> httpx.Response | None:
    """GET ``url``; retry transient failures. Returns ``None`` on 404 when ``allow_404``."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = await client.get(url, params=params)
        except httpx.TransportError as exc:
            last_error = exc
        else:
            if response.status_code == 404 and allow_404:
                return None
            if response.status_code not in RETRYABLE_STATUS:
                response.raise_for_status()
                return response
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                await asyncio.sleep(float(retry_after))
            last_error = httpx.HTTPStatusError(
                f"retryable status {response.status_code}",
                request=response.request,
                response=response,
            )
        delay = base_delay_s * 2**attempt
        logger.warning(
            "GET %s failed (attempt %d/%d), retry in %.1fs", url, attempt + 1, attempts, delay
        )
        await asyncio.sleep(delay)
    raise last_error or RuntimeError(f"GET {url} failed")


async def get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    attempts: int = 5,
    base_delay_s: float = 1.0,
) -> httpx.Response:
    response = await _get(client, url, params=params, attempts=attempts, base_delay_s=base_delay_s)
    if response is None:  # unreachable: 404 raises when allow_404 is False
        raise RuntimeError(f"GET {url} returned no response")
    return response


async def get_optional(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    attempts: int = 5,
    base_delay_s: float = 1.0,
) -> httpx.Response | None:
    """Like ``get_with_retry`` but returns ``None`` on 404."""
    return await _get(
        client, url, params=params, attempts=attempts, base_delay_s=base_delay_s, allow_404=True
    )
