---
name: run-backtest
description: Run a Strata backtest with full cost model and record it in the Experiment Log. Use for any research run; never run ad-hoc backtests outside this flow.
---

1. Confirm the period: research runs use the train period only (2020-01-01 – 2023-12-31). The holdout (2024-01-01 onward) is evaluated **once**, only when the task explicitly says so and the candidate set is frozen.
2. Run the backtest via the project CLI (`make backtest ARGS="..."` once implemented). Costs must be on: fees, slippage, funding, turnover.
3. Ensure the run is written to the Experiment Log (params, code version / git SHA, data version, period, metrics). A run that is not logged did not happen; re-run it logged.
4. For a candidate configuration also run: costs x2, random-signal benchmark (≥ 1000 shuffles), top-coin exclusion, walk-forward, sub-period stability.
5. Save full outputs to `artifacts/` (git-ignored); show only a compact metrics summary and the file path in chat.
6. Report the running count of tested variations.
