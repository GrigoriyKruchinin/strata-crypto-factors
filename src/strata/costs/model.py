"""Conservative transaction cost and funding model, shared by backtest, paper and live checks."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd

from strata.domain.interfaces import FillCostEstimate, ICostModel

_BPS = Decimal(10_000)


class SquareRootImpactCostModel(ICostModel):
    """fee + slippage, with slippage = base + k * sqrt(order notional / ADV).

    Defaults assume every order is a taker order. ``cost_multiplier`` scales fees and slippage
    (used for the 2x-costs robustness check); funding is market data and is never scaled.
    """

    def __init__(
        self,
        *,
        taker_fee: Decimal = Decimal("0.0005"),
        maker_fee: Decimal = Decimal("0.0002"),
        base_slippage_bps: Decimal = Decimal(5),
        impact_coefficient: Decimal = Decimal("0.1"),
        cost_multiplier: Decimal = Decimal(1),
        max_slippage: Decimal = Decimal("0.05"),
    ) -> None:
        self.taker_fee = taker_fee
        self.maker_fee = maker_fee
        self.base_slippage = base_slippage_bps / _BPS
        self.impact_coefficient = impact_coefficient
        self.cost_multiplier = cost_multiplier
        self.max_slippage = max_slippage

    def with_multiplier(self, multiplier: Decimal) -> SquareRootImpactCostModel:
        return SquareRootImpactCostModel(
            taker_fee=self.taker_fee,
            maker_fee=self.maker_fee,
            base_slippage_bps=self.base_slippage * _BPS,
            impact_coefficient=self.impact_coefficient,
            cost_multiplier=multiplier,
            max_slippage=self.max_slippage,
        )

    # ------------------------------------------------------------------ vectorised
    def trading_cost(
        self, trade_weights: pd.Series, equity: float, adv_quote: pd.Series
    ) -> pd.Series:
        traded = trade_weights.abs()
        notional = traded * equity
        adv = adv_quote.reindex(traded.index)
        # Unknown or zero ADV: charge the maximum slippage rather than nothing.
        participation = (notional / adv.where(adv > 0)).fillna(np.inf)
        impact = participation.pow(0.5) * float(self.impact_coefficient)
        slip = (impact + float(self.base_slippage)).clip(upper=float(self.max_slippage))
        rate = (slip + float(self.taker_fee)) * float(self.cost_multiplier)
        return traded * rate

    def funding_pnl(self, weights: pd.Series, funding_rates: pd.Series) -> pd.Series:
        rates = funding_rates.reindex(weights.index).fillna(0.0)
        return -weights * rates

    # ------------------------------------------------------------------ per order
    def estimate_fill(
        self, notional: Decimal, adv_quote: Decimal, *, is_maker: bool = False
    ) -> FillCostEstimate:
        size = abs(notional)
        fee_rate = self.maker_fee if is_maker else self.taker_fee
        if adv_quote > 0:
            participation = size / adv_quote
            slip_rate = self.base_slippage + self.impact_coefficient * participation.sqrt()
        else:
            slip_rate = self.max_slippage
        slip_rate = min(slip_rate, self.max_slippage)
        return FillCostEstimate(
            fee=size * fee_rate * self.cost_multiplier,
            slippage=size * slip_rate * self.cost_multiplier,
        )
