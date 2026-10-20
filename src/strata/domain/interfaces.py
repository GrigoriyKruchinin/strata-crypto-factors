"""Narrow interfaces between layers (ISP/DIP).

Signal generation and portfolio construction depend only on these abstractions, so the
same logic runs on top of the backtest simulator, the paper trader and a live gateway.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

import pandas as pd

from strata.domain.models import (
    AccountState,
    Candle,
    Fill,
    FundingRate,
    Instrument,
    OrderRequest,
    Symbol,
)
from strata.domain.panel import MarketPanel

# --------------------------------------------------------------------------- market data


class IMarketDataSource(ABC):
    """Async source of instruments, candles and funding history."""

    @abstractmethod
    async def list_instruments(self) -> list[Instrument]: ...

    @abstractmethod
    async def fetch_candles(
        self, symbol: Symbol, interval: str, start: datetime, end: datetime
    ) -> list[Candle]: ...

    @abstractmethod
    async def fetch_funding_rates(
        self, symbol: Symbol, start: datetime, end: datetime
    ) -> list[FundingRate]: ...


class BaseExchangeAdapter(IMarketDataSource, ABC):
    """Base for exchange integrations; new venues subclass this without touching the core."""

    name: str

    @abstractmethod
    async def aclose(self) -> None:
        """Release network resources."""


# --------------------------------------------------------------------------- research


class IUniverseProvider(ABC):
    @abstractmethod
    def membership(self, panel: MarketPanel) -> pd.DataFrame:
        """Boolean date x symbol frame; row ``d`` may only use panel rows ``<= d``."""


class IFactor(ABC):
    """A cross-sectional signal. Higher score means higher expected relative return."""

    name: str

    @abstractmethod
    def compute(self, panel: MarketPanel) -> pd.DataFrame:
        """Date x symbol raw scores; row ``d`` may only use panel rows ``<= d``."""


@dataclass(frozen=True)
class PortfolioContext:
    date: pd.Timestamp
    volatility: pd.Series  # annualised per-symbol vol estimate known at ``date``
    previous_weights: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    portfolio_vol_estimate: float | None = None


class IPortfolioConstructor(ABC):
    @abstractmethod
    def construct(self, scores: pd.Series, context: PortfolioContext) -> pd.Series:
        """Target weights (fraction of equity, signed) from scores of eligible symbols."""


@dataclass(frozen=True, slots=True)
class FillCostEstimate:
    fee: Decimal
    slippage: Decimal

    @property
    def total(self) -> Decimal:
        return self.fee + self.slippage


class ICostModel(ABC):
    """Single source of truth for costs in backtest (vectorised) and paper/live (per order)."""

    @abstractmethod
    def trading_cost(
        self, trade_weights: pd.Series, equity: float, adv_quote: pd.Series
    ) -> pd.Series:
        """Cost per symbol as a fraction of equity for the given signed weight changes."""

    @abstractmethod
    def funding_pnl(self, weights: pd.Series, funding_rates: pd.Series) -> pd.Series:
        """Funding PnL as a fraction of equity (positive rate: longs pay)."""

    @abstractmethod
    def estimate_fill(
        self, notional: Decimal, adv_quote: Decimal, *, is_maker: bool = False
    ) -> FillCostEstimate:
        """Cost of a single order in quote currency."""


# --------------------------------------------------------------------------- execution


class IOrderGateway(ABC):
    """Order execution: simulator, paper trading or live exchange."""

    @abstractmethod
    async def account(self) -> AccountState: ...

    @abstractmethod
    async def submit(self, orders: Sequence[OrderRequest]) -> list[Fill]: ...


class RiskAction(StrEnum):
    ALLOW = "allow"
    SCALE_DOWN = "scale_down"
    HALT = "halt"


@dataclass(frozen=True, slots=True)
class RiskDecision:
    action: RiskAction
    rule: str
    reason: str = ""
    scale: Decimal = Decimal(1)


@dataclass(frozen=True)
class RiskState:
    equity: Decimal
    peak_equity: Decimal
    day_start_equity: Decimal
    target_weights: dict[Symbol, Decimal]
    funding_rates: dict[Symbol, Decimal] = field(default_factory=dict)
    blocked_symbols: frozenset[Symbol] = frozenset()


class IRiskRule(ABC):
    name: str

    @abstractmethod
    def evaluate(self, state: RiskState) -> RiskDecision: ...
