from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import respx
from pydantic import SecretStr

from strata.config import TelegramSettings
from strata.domain.models import Fill, Side
from strata.notify.messages import daily_message, rebalance_message, warning_message
from strata.notify.telegram import TelegramNotifier, _chunks
from strata.paper.trader import CycleReport

D = Decimal


def _report() -> CycleReport:
    return CycleReport(
        account="paper",
        processed=[date(2026, 10, 18)],
        equity=D("3012.5"),
        previous_equity=D(3000),
        funding=D("-1.2"),
        costs=D("2.4"),
        fills=[
            Fill("ETHUSDT", Side.BUY, D(1), D(2400), D("1.2"), D("0.5"), "x", datetime.now(UTC))
        ],
        target={"ETHUSDT": 0.1, "SOLUSDT": 0.1, "DOGEUSDT": -0.2},
        signal_date=date(2026, 10, 18),
        dropped=["PEPEUSDT"],
        warnings=["late <rebalance>"],
    )


def test_messages_are_html_safe_and_readable() -> None:
    msg = rebalance_message(_report(), "all_six")
    assert "<b>Лонг</b>" in msg and "DOGE" in msg and "PEPE" in msg
    assert "&lt;rebalance&gt;" in msg  # escaped
    day = daily_message(_report(), D(3000))
    assert "+12.50 $" in day and "+0.42%" in day
    assert "&amp;" in warning_message("A & B", "x")


@respx.mock
async def test_telegram_send_uses_html_and_hides_token() -> None:
    route = respx.post("https://api.telegram.org/botSECRET/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    settings = TelegramSettings(_env_file=None, bot_token=SecretStr("SECRET"), chat_id="42")
    async with httpx.AsyncClient() as client:
        assert await TelegramNotifier(client, settings).send("<b>hi</b>")
    body = route.calls[0].request.content.decode()
    assert '"parse_mode":"HTML"' in body and '"chat_id":"42"' in body
    assert "SECRET" not in repr(settings)


def test_long_messages_are_chunked() -> None:
    text = ("x" * 100 + "\n") * 100
    chunks = _chunks(text)
    assert len(chunks) == 3 and "".join(chunks) == text
