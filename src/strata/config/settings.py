"""Modular application settings.

Each group reads only its own env prefix, so a container can be given exactly the
variables it needs. Secrets are typed as ``SecretStr`` and never rendered in reprs or logs.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = ".env"


class _Base(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", frozen=True)


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


class RebalanceFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


class AppSettings(_Base):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=_ENV_FILE, extra="ignore")

    env: Environment = Environment.LOCAL
    log_level: str = "INFO"
    timezone: str = "UTC"


class DatabaseSettings(_Base):
    """Local SQLite database (paper account state, candles/funding copy, experiments)."""

    model_config = SettingsConfigDict(env_prefix="DB_", env_file=_ENV_FILE, extra="ignore")

    url: str = "sqlite+aiosqlite:///data/strata.db"


class ExchangeSettings(_Base):
    """Exchange connectivity. API keys are only needed by the live trading worker (Stage 2)."""

    model_config = SettingsConfigDict(env_prefix="EXCHANGE_", env_file=_ENV_FILE, extra="ignore")

    name: str = "binance_usdm"
    testnet: bool = False
    rest_base_url: str = "https://fapi.binance.com"
    vision_base_url: str = "https://data.binance.vision"
    request_timeout_s: float = 30.0
    max_requests_per_minute: int = 1200


class DataSettings(_Base):
    model_config = SettingsConfigDict(env_prefix="DATA_", env_file=_ENV_FILE, extra="ignore")

    root_dir: Path = Path("data")
    history_start: date = date(2020, 1, 1)
    quote_asset: str = "USDT"
    download_concurrency: int = 8


class ResearchSettings(_Base):
    model_config = SettingsConfigDict(env_prefix="RESEARCH_", env_file=_ENV_FILE, extra="ignore")

    train_start: date = date(2020, 1, 1)
    train_end: date = date(2023, 12, 31)
    holdout_start: date = date(2024, 1, 1)
    random_signal_runs: int = 1000
    workers: int = 6
    seed: int = 42
    artifacts_dir: Path = Path("artifacts")

    @model_validator(mode="after")
    def _periods_do_not_overlap(self) -> Self:
        if not self.train_start < self.train_end < self.holdout_start:
            raise ValueError("Require train_start < train_end < holdout_start")
        return self


class UniverseSettings(_Base):
    model_config = SettingsConfigDict(env_prefix="UNIVERSE_", env_file=_ENV_FILE, extra="ignore")

    top_n: int = Field(default=50, ge=4)
    volume_lookback_days: int = Field(default=30, ge=1)
    min_age_days: int = Field(default=60, ge=0)
    min_avg_quote_volume: Decimal = Decimal(5_000_000)
    exclude_symbols: tuple[str, ...] = ("USDCUSDT", "BTCDOMUSDT", "DEFIUSDT")


class FactorSettings(_Base):
    model_config = SettingsConfigDict(env_prefix="FACTOR_", env_file=_ENV_FILE, extra="ignore")

    momentum_windows: tuple[int, ...] = (28, 56, 84)
    momentum_skip_days: int = 7
    reversal_window: int = 7
    volatility_window: int = 30
    liquidity_window: int = 30
    funding_window: int = 14
    beta_window: int = 60
    winsor_quantile: float = Field(default=0.05, ge=0.0, lt=0.5)


class PortfolioSettings(_Base):
    model_config = SettingsConfigDict(env_prefix="PORTFOLIO_", env_file=_ENV_FILE, extra="ignore")

    rebalance: RebalanceFrequency = RebalanceFrequency.WEEKLY
    positions_per_side: int = Field(default=10, ge=1)
    capital_usdt: Decimal = Decimal(3000)
    gross_leverage: Decimal = Decimal("1.0")
    max_coin_weight: Decimal = Decimal("0.15")
    target_annual_vol: float | None = None
    max_turnover: float | None = None


class CostSettings(_Base):
    """Binance USDT-M VIP0 fees by default; slippage is deliberately conservative."""

    model_config = SettingsConfigDict(env_prefix="COST_", env_file=_ENV_FILE, extra="ignore")

    maker_fee: Decimal = Decimal("0.0002")
    taker_fee: Decimal = Decimal("0.0005")
    base_slippage_bps: Decimal = Decimal(5)
    impact_coefficient: Decimal = Decimal("0.1")
    cost_multiplier: Decimal = Decimal(1)


class TelegramSettings(_Base):
    model_config = SettingsConfigDict(env_prefix="TELEGRAM_", env_file=_ENV_FILE, extra="ignore")

    bot_token: SecretStr = SecretStr("")
    chat_id: str = ""
    api_base_url: str = "https://api.telegram.org"

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token.get_secret_value() and self.chat_id)


class PaperSettings(_Base):
    """Paper trading account. The strategy comes from the frozen research candidates."""

    model_config = SettingsConfigDict(env_prefix="PAPER_", env_file=_ENV_FILE, extra="ignore")

    account: str = "paper"
    frozen_candidates_path: Path = Path("docs/research/frozen-candidates.json")
    initial_equity: Decimal = Decimal(3000)
    reconcile_tolerance: float = 0.25
    min_days: int = 28
