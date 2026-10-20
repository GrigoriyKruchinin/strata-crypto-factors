---
name: run-backtest
description: Run a Strata backtest with the full cost model and record it in the experiment log. Use for any research run; never run ad-hoc backtests outside this flow.
---

1. Confirm the period. Selection/tuning uses the train period (2020-01-01 – 2023-12-31). The
   2024-01-01+ holdout is burned: it may be shown for context, never used to select or tune. A new
   hypothesis needs a pre-registered evaluation segment that has never been looked at.
2. Run through the project CLI (`make backtest ARGS="--spec <name>"` or `make research STEP=...`).
   Costs must be on: fees, slippage, funding, turnover.
3. Ensure the run is in `docs/research/experiment-log.jsonl` (params, git SHA, data version, period,
   metrics). A run that is not logged did not happen; re-run it logged.
4. For a candidate also run: costs x2, random signal (>= 1000 runs), top-coin exclusion,
   walk-forward, regime breakdown.
5. Save full outputs to `artifacts/` (git-ignored); show only a compact summary and the path in chat.
6. Report the running count of tested variations.
