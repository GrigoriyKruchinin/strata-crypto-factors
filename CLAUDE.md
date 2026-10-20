# CLAUDE.md — Strata: Crypto Factor Research Toolkit

Research toolkit for cross-sectional factor strategies on crypto perpetual futures: survivorship-free
Binance USDT-M data, cost- and funding-aware backtesting, validation (walk-forward, random signals,
coin exclusion, regimes, deflated Sharpe), an append-only experiment log and a paper simulation on
live public data. No real trading. Goals: correct and reproducible analysis, code quality, clear docs.

## Session start protocol

1. Read `CLAUDE.md` and `todo.md`.
2. Pick the first unchecked `- [ ]` item (or the user's request) and continue.
3. State of the project = files (`todo.md`, git history, `docs/reports/`, `docs/research/`), not chat memory.

## Language policy

- Code, comments, docstrings, prompts, architecture docs, `README.md`: **English**.
- Communication with the user, user guides (`docs/guides/`), "Простыми словами" blocks, Telegram
  texts: **Russian**, plain language (explain jargon at first mention).

## Research discipline (non-negotiable)

- Every backtest includes fees, slippage, funding over actual holding time and turnover.
- No look-ahead: signal at close of `t`, fill at the next bar. Enforced by tests.
- No survivorship: point-in-time universe, delisted contracts kept, zero-volume bars dropped.
- Every tested variation goes to `docs/research/experiment-log.jsonl`; report the count and correct
  for multiple testing (deflated Sharpe).
- The 2024-01-01+ holdout of the 2026-10 study is **burned**. Any new hypothesis is pre-registered
  and judged on a segment that was never looked at (e.g. data after the last run date).
- Thresholds and selection rules are fixed before the evaluation segment is opened.

## Commands

```bash
uv sync                          # install deps (Python 3.12)
make check                       # ruff + mypy --strict + pytest
make download-history            # data.binance.vision archive + public REST tail -> data/
make research STEP=train         # steps: train | robustness | freeze | holdout | charts
make backtest ARGS="--spec all_six"
make paper ARGS="--no-refresh"   # paper simulation cycle (SQLite in data/strata.db)
```

## Code style

- Python 3.12, `uv`, `pyproject.toml` + `uv.lock`; `mypy --strict` and `ruff` clean.
- Narrow interfaces (`IMarketDataSource`, `IUniverseProvider`, `IFactor`, `IPortfolioConstructor`,
  `ICostModel`, `IOrderGateway`); new factors/constructors/cost models are new implementations,
  wired in `strata.infra.container` / `strata.research.spec`.
- `Decimal` for money in the paper accounting layer; pandas/numpy in research and backtest.
- Fixed seeds and data-version stamps for reproducibility.
- Never print large dumps into chat: save to file, show a summary and the path.

## Git workflow

- `main` is stable; work in short feature branches merged after `make check` passes.
- Per task: implement → `make check` → tick `todo.md` → commit → push.
- Conventional Commits in English; `todo.md` updates go into the same commit. Small atomic commits.
- Before every commit: review `git diff --staged` for secrets. Never commit `.env`, tokens, data dumps.
- Forbidden without explicit user permission: `git push --force` to `main`, history rewrites, branch deletion.
- Push failure: one attempt to fix (`git pull --rebase`, check remote), then report to the user.

## Context management

- After a large task is committed and pushed, tell the user (in Russian): "Задача закоммичена, `todo.md` актуален. Если контекст разросся, можно сделать `/clear` и написать "продолжай": я продолжу по `todo.md`".
- Delegate heavy reading (API docs, big dumps, wide code search) to subagents; keep only conclusions.

**When compacting context, always preserve:** current task from `todo.md`, list of modified files,
verification commands (`make lint`, `make typecheck`, `make test`), decisions taken, research
periods (train 2020-01-01–2023-12-31; holdout 2024-01-01+ burned), open questions to the user.

## Safety

- No secrets in the repo; `.env` (ignored) + `.env.example`. Only public market data: no exchange keys.
- Logs never contain tokens or private data.
- Before each release: `make check` and `/audit-risks`.
- Reports label results as historical/simulated, never as forecasts or advice.
