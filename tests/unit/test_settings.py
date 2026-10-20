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
    monkeypatch.setenv("DB_PASSWORD", "super-secret-value")
    s = DatabaseSettings(_env_file=None)
    assert "super-secret-value" not in repr(s)
    assert "super-secret-value" in s.async_url


def test_telegram_disabled_without_token() -> None:
    assert not TelegramSettings(_env_file=None).enabled
