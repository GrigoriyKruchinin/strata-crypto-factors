# Strata — Crypto Factor Research Toolkit — todo

Legend: `[x]` done and verified · `[ ]` open (partial work noted inline).
Train period: 2020-01-01 – 2023-12-31 · Holdout: 2024-01-01 – present (open once).

## Stage 0 — Infrastructure

- [x] Clarifying questions asked and answered (exchange, capital, rebalance frequency, leverage/drawdown, Go/No-Go, VPS budget)
- [x] Train / holdout boundaries fixed in `CLAUDE.md`
- [x] `CLAUDE.md` (commands, style, workflow, branches, compaction block, post-Stage-1 fork protocol)
- [x] `.claude/agents/`: implementation-agent, security-trading-risk-critic
- [x] `.claude/skills/`: check-code-quality, run-tests, audit-risks, run-backtest
- [x] `todo.md`
- [x] Git: `.gitignore`, `.env.example`, `origin`, first commit + push
- [x] `README.md` header + `docs/assets/logo.svg`
- [x] `docs/guides/stage-1-user-guide.md`
- [x] Wait for "Start Implementation"

## Stage 1 — MVP + research (no real money) · branch `stage-1-mvp`

### Foundation
- [x] `pyproject.toml` (uv, Python 3.12), `uv.lock`, `Makefile` (lint, typecheck, test, check, backtest)
- [x] ruff + mypy strict + pytest (+ pytest-asyncio, hypothesis) configured; empty package passes `make check`
- [x] Package layout (`src/strata/...`): domain, data, universe, factors, portfolio, costs, backtest, research, paper, notify, infra
- [x] Modular Pydantic Settings: `AppSettings`, `DatabaseSettings`, `ExchangeSettings`, `DataSettings`, `FactorSettings`, `PortfolioSettings`, `CostSettings`, `TelegramSettings`, `ResearchSettings`, `PaperSettings`
- [x] Core interfaces: `IMarketDataSource`, `IUniverseProvider`, `IFactor`, `IPortfolioConstructor`, `ICostModel`, `IOrderGateway` (simulation), `BaseExchangeAdapter`
- [x] DI container / factories wiring the backtest simulator and the paper simulator (`strata.infra.container`)

### Storage
- [x] SQLAlchemy async models: instruments (listing/delisting dates), candles, funding rates, universe snapshots, factor values, target portfolios, actual portfolios, trades, equity curve, experiment log
- [x] Alembic setup + initial migration (applied automatically to the local SQLite database)
- [x] DB ingest: candles/funding (incremental after each refresh), experiment log (`strata ingest-db`), universe + factor values per paper rebalance (separate migrations container)
- [x] Daily paper run as a CLI command (`strata paper-cycle`, schedulable with cron)
- [x] Local stack was validated in Stage 1 and later replaced by a local SQLite + CLI setup

### Data
- [x] Binance USDT-M adapter (public endpoints, httpx REST behind own interface, weight-based rate limiter)
- [x] Bulk history loader from `data.binance.vision`: 1d (and 1h if needed) klines, funding history, all perpetuals including delisted; checkpoints, resume, gap detection
- [x] Instrument metadata with listing/delisting dates; data version stamp
- [x] Data quality report (gaps, zero volume, outliers) saved to file

### Universe and factors
- [x] Point-in-time Universe Builder: top-N by trailing 30d quote volume, min age, min liquidity; delisted kept historically
- [x] Factors (`IFactor`): momentum (several windows, skip window), short-term reversal, volatility, liquidity/size (volume proxy), funding carry, beta to BTC
- [x] Cross-sectional normalization (rank / z-score, winsorization) and factor combination
- [x] No-look-ahead tests for universe and every factor (perturb future data → signal unchanged)

### Portfolio and costs
- [x] Portfolio Constructor: top/bottom quantile, dollar-neutral, equal weight and inverse-vol weight, per-coin weight cap, portfolio vol targeting, turnover limit, gross leverage ≤ 2x
- [x] Compact-book mode for $1k–$5k capital (~8–10 per side) respecting `minNotional`, `stepSize`
- [x] Cost Model (`ICostModel`): maker/taker fees, size-to-volume slippage (conservative), funding per position over actual holding time, rebalance turnover; costs ×2 switch
- [x] Property-based tests for money math (Decimal rounding, tick/step, neutrality)

### Backtest and validation
- [x] Backtester (signal at close `t`, fill at `t+1`), daily and weekly rebalance
- [x] Metrics: net/annual return, vol, Sharpe, max drawdown, turnover, cost and funding share, yearly and rolling returns, per-coin contribution (per-factor attribution: in research runner)
- [x] Experiment Log (params, git SHA, data version, period, metrics) + variation counter
- [x] Walk-forward evaluation
- [x] Sub-period stability (bull / bear / sideways)
- [x] Costs ×2 sensitivity (run for every grid spec on train; for primary on holdout)
- [x] Random-signal benchmark (≥ 1000 shuffled-rank runs, fixed seed)
- [x] Top-coin exclusion test
- [x] Benchmarks: BTC buy-and-hold, equal-weight long-only
- [x] Multiple-testing correction (e.g. deflated Sharpe) in conclusions
- [x] Freeze candidate set in the log → **one-time holdout evaluation** (frozen and opened 2026-10-20; holdout is now burned)

### Paper trading and notifications
- [x] Paper Trader: live public data, virtual orders via simulator `IOrderGateway`, same cost model, persisted to DB
- [x] Paper vs backtest reconciliation on the same dates
- [x] Telegram notifier (HTML formatting): new target portfolio, daily/weekly virtual PnL digest, warnings
- [ ] Paper trading runs ≥ 28 days — not completed: stopped after 1 day following the holdout evaluation (2026-10-20)

### Go / No-Go criteria (agreed 2026-10-19, fixed before holdout)
- [x] **Mandatory "plus to deposit"** (added 2026-10-20, before holdout was opened): net return on deposit after all costs and funding on unseen data is positive; reported as average net % per month; 1.5%/month is the reference level, final decision discussed with the user. Without this criterion the verdict cannot be Go — evaluated 2026-10-20: **FAIL −1.15%/month**
- [x] Holdout net annual return ≥ 20% with max drawdown ≤ 25% (gross leverage ≤ 2x) — evaluated 2026-10-20: **FAIL −12.9%, max DD 63.2%**
- [x] Holdout Sharpe ≥ 1.0 after costs and funding — evaluated 2026-10-20: **FAIL −0.12**
- [x] Costs ×2: Sharpe ≥ 0.5 — evaluated 2026-10-20: **FAIL −0.21**
- [x] Real result > 95th percentile of random signals — evaluated 2026-10-20: **FAIL 60.7th**
- [x] No single coin > 15% of total profit — evaluated 2026-10-20: **PASS 8.7%**
- [x] Positive in ≥ 60% of rolling 6-month windows — evaluated 2026-10-20: **FAIL 44.4%**
- [x] Paper trading ≥ 28 days, deviation from backtest on the same dates ≤ 25% — evaluated 2026-10-20: **not evaluated (stopped after No-Go)**


### Stage close
- [x] `docs/reports/stage-1-go-no-go.md` (metrics, equity vs BTC chart, best configs, variation count, validity checks, risks, recommendation, "Простыми словами" block)
- [x] `/audit-risks` clean (no BLOCKER/HIGH; 1 MEDIUM + 3 LOW fixed, documented in the report)
- [x] README updated (features, quick start, architecture, configuration, status badge)
- [x] `chore: complete stage 1`, tag `v0.1.0`, merge to `main`, push

## Outcome of Stage 1 — research toolkit

- [x] Discuss `docs/reports/stage-1-go-no-go.md` with the owner (2026-10-20)
- [x] Reposition as "Crypto Factor Research Toolkit": README, CLAUDE.md, `.claude/`, todo
- [x] Remove live-execution plans and trading-only settings (no exchange keys, no risk-limit settings)
- [x] Replace the container stack with local SQLite + CLI (`uv run strata ...`, `Makefile`)
- [x] CI for code quality only (ruff, mypy, pytest)
- [x] Clean install and tests verified on a fresh clone
- [x] `CHANGELOG.md`, tag `v1.0.0`

## Polish & docs (optional)

- [ ] Usage examples: adding a new `IFactor`, running a custom grid, reading results
- [ ] `strata report` command: markdown/SVG summary for any logged run
- [ ] Hourly-bar support in the loader and panel
- [ ] Re-run the full study after the audit fixes on fresh, unseen data and compare
- [ ] Raise test coverage of `strata.data.loader` error paths and the CLI
