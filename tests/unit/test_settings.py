from datetime import date

import pytest
from pydantic import ValidationError

from strata.config import DatabaseSettings, ResearchSettings, TelegramSettings


def test_research_periods_defaults() -> None:
    s = ResearchSettings(_env_file=None)
    assert s.train_end < s.holdout_start == date(2024, 1, 1)


def test_research_periods_must_not_overlap() -> None:
    with pytest.raises(ValidationError):
        ResearchSettings(_env_file=None, train_end=date(2024, 6, 1))


def test_secrets_not_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "super-secret-value")
    s = TelegramSettings(_env_file=None)
    assert "super-secret-value" not in repr(s)
    assert s.bot_token.get_secret_value() == "super-secret-value"


def test_database_defaults_to_local_sqlite() -> None:
    assert DatabaseSettings(_env_file=None).url.startswith("sqlite+aiosqlite:///")


def test_telegram_disabled_without_token() -> None:
    assert not TelegramSettings(_env_file=None).enabled
