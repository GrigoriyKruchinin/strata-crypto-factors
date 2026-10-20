# Stage 1 research protocol (pre-registered)

Committed before any backtest on real data was run. Deviations must be logged and justified.

## Periods

| Segment | Dates | Use |
|---|---|---|
| Warm-up | 2020-01-01 – 2020-03-31 | factor/universe history only, no PnL |
| Train / selection | 2020-04-01 – 2023-12-31 | grid evaluation, walk-forward, robustness |
| Holdout | 2024-01-01 – latest closed bar | opened **once**, primary candidate only for Go/No-Go |

## Candidate grid

`src/strata/research/grid.py`: 18 specifications — 8 single factors with literature-fixed signs,
4 composites, 6 variations (daily rebalance, inverse-vol weighting, top-30 universe). Defaults:
weekly rebalance (Sunday close signal, Monday open execution), top-50 point-in-time universe,
10 longs / 10 shorts, equal weight, gross leverage 1.0, 15% max coin weight, taker fees +
square-root impact slippage, funding over actual holding time.

## Selection (train only)

1. Run every grid spec on train. Log all of them.
2. Walk-forward over the grid: expanding window, test years 2021, 2022, 2023; report OOS Sharpe.
3. **Primary** = highest train Sharpe among specs whose costs ×2 Sharpe ≥ 0.5 on train.
   Up to two more finalists = next best by the same rule.
4. Robustness on train for finalists: costs ×2, random signal (1000 runs), top-1/2/3 coin
   exclusion, bull/bear/sideways regimes, benchmarks.
5. Leverage for the primary is fixed from train only: `L = clip(0.20 / train_annual_vol, 0.5, 2.0)`
   (targets ~20% annual vol, never above the agreed 2x cap).
6. Deflated Sharpe uses the number of distinct candidate specs in the experiment log.

## Holdout (once)

Freeze finalists (`docs/research/frozen-candidates.json`), then evaluate the primary at leverage
`L` on the holdout. Go/No-Go criteria from `todo.md` are evaluated on these holdout results
(random-signal percentile and coin concentration also on the holdout). No parameter changes
after the holdout is opened; any further iteration uses a new unseen segment.

## Amendments

- **2026-10-20 (before the holdout was opened):** added the mandatory "plus to deposit" criterion
  from the revised project brief: average net monthly return on the holdout must be > 0 (hard
  gate); 1.5%/month is the reference level and the final call is discussed with the owner.
  Train results had been computed at this point; the holdout had not been touched.
