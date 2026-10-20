"""Persistence for paper accounts (positions, cash, trades, equity, targets)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strata.domain.models import Fill, Position, Symbol
from strata.infra.db import AccountRow, EquityRow, PositionRow, TargetPortfolioRow, TradeRow


@dataclass
class AccountRecord:
    account: str
    cash: Decimal
    initial_equity: Decimal
    started_on: date
    last_processed: date | None = None


@dataclass(frozen=True)
class EquityPoint:
    bar_date: date
    equity: Decimal
    funding: Decimal
    costs: Decimal
    gross_exposure: Decimal


class IPaperRepository(ABC):
    @abstractmethod
    async def load_account(self, account: str) -> AccountRecord | None: ...

    @abstractmethod
    async def load_positions(self, account: str) -> dict[Symbol, Position]: ...

    @abstractmethod
    async def save_state(
        self,
        record: AccountRecord,
        positions: dict[Symbol, Position],
        fills: Sequence[Fill],
        equity: Sequence[EquityPoint],
        target: tuple[str, date, dict[str, float]] | None,
    ) -> None:
        """Persist one cycle atomically."""

    @abstractmethod
    async def equity_curve(self, account: str) -> list[EquityPoint]: ...


class InMemoryPaperRepository(IPaperRepository):
    def __init__(self) -> None:
        self.accounts: dict[str, AccountRecord] = {}
        self.positions: dict[str, dict[Symbol, Position]] = {}
        self.fills: dict[str, list[Fill]] = {}
        self.equity: dict[str, list[EquityPoint]] = {}
        self.targets: dict[str, list[tuple[str, date, dict[str, float]]]] = {}

    async def load_account(self, account: str) -> AccountRecord | None:
        rec = self.accounts.get(account)
        return AccountRecord(**vars(rec)) if rec else None

    async def load_positions(self, account: str) -> dict[Symbol, Position]:
        return {
            s: Position(p.symbol, p.quantity, p.entry_price)
            for s, p in self.positions.get(account, {}).items()
        }

    async def save_state(
        self,
        record: AccountRecord,
        positions: dict[Symbol, Position],
        fills: Sequence[Fill],
        equity: Sequence[EquityPoint],
        target: tuple[str, date, dict[str, float]] | None,
    ) -> None:
        self.accounts[record.account] = AccountRecord(**vars(record))
        self.positions[record.account] = {
            s: Position(p.symbol, p.quantity, p.entry_price) for s, p in positions.items()
        }
        self.fills.setdefault(record.account, []).extend(fills)
        self.equity.setdefault(record.account, []).extend(equity)
        if target is not None:
            self.targets.setdefault(record.account, []).append(target)

    async def equity_curve(self, account: str) -> list[EquityPoint]:
        return list(self.equity.get(account, []))


class SqlPaperRepository(IPaperRepository):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def load_account(self, account: str) -> AccountRecord | None:
        async with self.sessions() as session:
            row = await session.get(AccountRow, account)
            if row is None:
                return None
            return AccountRecord(
                row.account, row.cash, row.initial_equity, row.started_on, row.last_processed
            )

    async def load_positions(self, account: str) -> dict[Symbol, Position]:
        async with self.sessions() as session:
            rows = await session.scalars(select(PositionRow).where(PositionRow.account == account))
            return {r.symbol: Position(r.symbol, r.quantity, r.entry_price) for r in rows}

    async def save_state(
        self,
        record: AccountRecord,
        positions: dict[Symbol, Position],
        fills: Sequence[Fill],
        equity: Sequence[EquityPoint],
        target: tuple[str, date, dict[str, float]] | None,
    ) -> None:
        async with self.sessions() as session, session.begin():
            await session.merge(
                AccountRow(
                    account=record.account,
                    cash=record.cash,
                    initial_equity=record.initial_equity,
                    started_on=record.started_on,
                    last_processed=record.last_processed,
                )
            )
            await session.execute(delete(PositionRow).where(PositionRow.account == record.account))
            session.add_all(
                PositionRow(
                    account=record.account,
                    symbol=p.symbol,
                    quantity=p.quantity,
                    entry_price=p.entry_price,
                )
                for p in positions.values()
                if p.quantity != 0
            )
            for f in fills:
                # Idempotent on clientOrderId: a replayed cycle never duplicates trades.
                await session.merge(
                    TradeRow(
                        client_order_id=f.client_order_id,
                        account=record.account,
                        symbol=f.symbol,
                        side=f.side.value,
                        quantity=f.quantity,
                        price=f.price,
                        fee=f.fee,
                        slippage_cost=f.slippage_cost,
                        filled_at=f.filled_at,
                    )
                )
            for e in equity:
                await session.merge(
                    EquityRow(
                        account=record.account,
                        bar_date=e.bar_date,
                        equity=e.equity,
                        funding=e.funding,
                        costs=e.costs,
                        gross_exposure=e.gross_exposure,
                    )
                )
            if target is not None:
                strategy, signal_date, weights = target
                existing = await session.scalar(
                    select(TargetPortfolioRow).where(
                        TargetPortfolioRow.account == record.account,
                        TargetPortfolioRow.signal_date == signal_date,
                    )
                )
                if existing is None:
                    session.add(
                        TargetPortfolioRow(
                            account=record.account,
                            strategy=strategy,
                            signal_date=signal_date,
                            weights=weights,
                        )
                    )

    async def equity_curve(self, account: str) -> list[EquityPoint]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(EquityRow).where(EquityRow.account == account).order_by(EquityRow.bar_date)
            )
            return [
                EquityPoint(r.bar_date, r.equity, r.funding, r.costs, r.gross_exposure)
                for r in rows
            ]
