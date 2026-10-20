"""Performance metrics for daily net return series (365-day annualisation, crypto trades 24/7)."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from strata.backtest.engine import BacktestResult

ANNUALISATION = 365


def growth(returns: pd.Series) -> float:
    """Compounded growth factor of a simple-return series."""
    return float(np.prod(1.0 + returns.to_numpy(dtype=float)))


def sharpe(returns: pd.Series) -> float:
    std = float(returns.std(ddof=1))
    if len(returns) < 2 or math.isnan(std) or std < 1e-12:
        return 0.0
    return float(returns.mean()) / std * math.sqrt(ANNUALISATION)


def max_drawdown(returns: pd.Series) -> float:
    """Largest peak-to-trough loss as a positive fraction."""
    curve = (1.0 + returns).cumprod()
    peak = curve.cummax().clip(lower=1.0)
    return float(-(curve / peak - 1.0).min()) if len(curve) else 0.0


def cagr(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    g = growth(returns)
    years = len(returns) / ANNUALISATION
    return g ** (1.0 / years) - 1.0 if g > 0 else -1.0


@dataclass(frozen=True)
class Metrics:
    days: int
    total_return: float
    annual_return: float
    annual_vol: float
    sharpe: float
    max_drawdown: float
    annual_turnover: float
    annual_cost: float
    annual_funding: float
    cost_share_of_gross: float
    hit_rate: float
    max_coin_profit_share: float
    positive_6m_windows: float

    def as_dict(self) -> dict[str, float]:
        return {k: float(v) for k, v in asdict(self).items()}


def coin_profit_shares(result: BacktestResult) -> pd.Series:
    """Each coin's share of total *positive* PnL (robust when total PnL is near zero)."""
    pnl = result.contributions.sum()
    positive = pnl[pnl > 0]
    total = float(positive.sum())
    if total <= 0:
        return pd.Series(dtype=float)
    shares: pd.Series = (positive / total).sort_values(ascending=False)
    return shares


def rolling_window_returns(returns: pd.Series, window_days: int = 182) -> pd.Series:
    log_growth = np.log1p(returns).rolling(window_days).sum()
    rolled: pd.Series = np.expm1(log_growth).dropna()
    return rolled


def compute_metrics(result: BacktestResult) -> Metrics:
    d = result.daily
    r = result.returns
    years = max(len(r) / ANNUALISATION, 1e-9)
    gross_abs = float(d["gross_return"].abs().sum())
    windows = rolling_window_returns(r)
    shares = coin_profit_shares(result)
    return Metrics(
        days=len(r),
        total_return=growth(r) - 1.0,
        annual_return=cagr(r),
        annual_vol=float(r.std(ddof=1) * math.sqrt(ANNUALISATION)) if len(r) > 1 else 0.0,
        sharpe=sharpe(r),
        max_drawdown=max_drawdown(r),
        annual_turnover=float(d["turnover"].sum()) / years,
        annual_cost=float(-d["cost_return"].sum()) / years,
        annual_funding=float(d["funding_return"].sum()) / years,
        cost_share_of_gross=float(-d["cost_return"].sum()) / gross_abs if gross_abs else 0.0,
        hit_rate=float((r > 0).mean()) if len(r) else 0.0,
        max_coin_profit_share=float(shares.iloc[0]) if len(shares) else 0.0,
        positive_6m_windows=float((windows > 0).mean()) if len(windows) else 0.0,
    )


def yearly_returns(returns: pd.Series) -> pd.Series:
    grouped = (1.0 + returns).groupby(pd.DatetimeIndex(returns.index).year).prod() - 1.0
    out: pd.Series = grouped
    return out
