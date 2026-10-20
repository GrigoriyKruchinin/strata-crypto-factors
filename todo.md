# Strata — todo

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
- [ ] Admin dashboard credentials: user sets them in `.env` before Stage 3 (never in chat)
- [x] Wait for "Start Implementation"

## Stage 1 — MVP + research (no real money) · branch `stage-1-mvp`

### Foundation
- [x] `pyproject.toml` (uv, Python 3.12), `uv.lock`, `Makefile` (lint, typecheck, test, check, backtest)
- [x] ruff + mypy strict + pytest (+ pytest-asyncio, hypothesis) configured; empty package passes `make check`
- [x] Package layout (`src/strata/...`): domain, data, universe, factors, portfolio, costs, backtest, research, paper, notify, infra
- [x] Modular Pydantic Settings: `AppSettings`, `DatabaseSettings`, `RedisSettings`, `ExchangeSettings`, `DataSettings`, `FactorSettings`, `PortfolioSettings`, `CostSettings`, `RiskSettings`, `TelegramSettings`, `ResearchSettings`
- [x] Core interfaces: `IMarketDataSource`, `IUniverseProvider`, `IFactor`, `IPortfolioConstructor`, `ICostModel`, `IOrderGateway`, `IRiskRule`, `BaseExchangeAdapter`
- [ ] DI container / factories wiring simulator, paper and (later) live gateways

### Storage and infra
- [x] SQLAlchemy async models: instruments (listing/delisting dates), candles, funding rates, universe snapshots, factor values, target portfolios, actual portfolios, trades, equity curve, experiment log
- [x] Alembic setup + initial migration (separate migrations container)
- [x] Redis + Celery app, beat schedule (daily refresh 00:15 UTC -> paper cycle -> notify; weekly rebalance inside cycle)
- [x] `docker-compose.local.yml`: postgres, redis, migrations, celery-beat, worker, data-loader, backtester, paper-trader, telegram-worker; healthchecks + `depends_on: service_healthy`; per-role env subsets
- [x] `docker compose -f docker-compose.local.yml config` passes; stack starts healthy

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
- [ ] Costs ×2 sensitivity (cost_multiplier in spec; run in research batch)
- [x] Random-signal benchmark (≥ 1000 shuffled-rank runs, fixed seed)
- [x] Top-coin exclusion test
- [x] Benchmarks: BTC buy-and-hold, equal-weight long-only
- [x] Multiple-testing correction (e.g. deflated Sharpe) in conclusions
- [ ] Freeze candidate set in the log → **one-time holdout evaluation**

### Paper trading and notifications
- [x] Paper Trader: live public data, virtual orders via simulator `IOrderGateway`, same cost model, persisted to DB
- [x] Paper vs backtest reconciliation on the same dates
- [x] Telegram notifier (HTML formatting): new target portfolio, daily/weekly virtual PnL digest, warnings
- [ ] Paper trading runs ≥ 28 days

### Go / No-Go criteria (agreed 2026-10-19, fixed before holdout)
- [ ] **Mandatory "plus to deposit"** (added 2026-10-20, before holdout was opened): net return on deposit after all costs and funding on unseen data is positive; reported as average net % per month; 1.5%/month is the reference level, final decision discussed with the user. Without this criterion the verdict cannot be Go
- [ ] Holdout net annual return ≥ 20% with max drawdown ≤ 25% (gross leverage ≤ 2x)
- [ ] Holdout Sharpe ≥ 1.0 after costs and funding
- [ ] Costs ×2: Sharpe ≥ 0.5
- [ ] Real result > 95th percentile of random signals
- [ ] No single coin > 15% of total profit
- [ ] Positive in ≥ 60% of rolling 6-month windows
- [ ] Paper trading ≥ 28 days, deviation from backtest on the same dates ≤ 25%

### Stage close
- [ ] `docs/reports/stage-1-go-no-go.md` (metrics, equity vs BTC chart, best configs, variation count, validity checks, risks, recommendation, "Простыми словами" block)
- [ ] `/audit-risks` clean
- [ ] README updated (features, quick start, architecture, configuration, status badge)
- [ ] `docs/guides/stage-2-user-guide.md` (only if Go)
- [ ] `chore: complete stage 1`, tag `v0.1.0`, merge to `main`, push

## Fork after Stage 1 — Go / Iterate / Research toolkit

- [ ] Discuss `docs/reports/stage-1-go-no-go.md` with the user (plain Russian, honest)
- [ ] Go → Stage 2 after explicit confirmation
- [ ] Iterate → ≤ 2 iterations, goals and criteria recorded here, fresh unseen segment
- [ ] No-Go (explicitly confirmed) → reposition as "Crypto Factor Research Toolkit" per `CLAUDE.md` protocol: README/CLAUDE.md/.claude/todo rewrite, remove execution code, **remove all Docker infrastructure** (compose, Dockerfile, Redis/Celery workers; local SQLite/Parquet storage, `uv run` + Makefile), CI for code quality only, verify clean install without Docker, tag `v1.0.0`

## Stage 2 — Production, real money (only on Go) · branch `stage-2-prod`

- [ ] Live `IOrderGateway` for Binance USDT-M: place/cancel, positions, account, idempotent `clientOrderId`, leverage and margin mode
- [ ] Rebalance Executor: target vs actual diff, limit orders with slippage cap + timeout, controlled fill-up, partial fills/rejects/retries
- [ ] Startup reconciliation with exchange state
- [ ] Rate limits, WebSocket auto-reconnect
- [ ] Risk Manager (`IRiskRule`s): gross leverage, per-coin weight, per-coin PnL share, daily loss, 25% drawdown stop, liquidation distance, delisting/abnormal funding exclusion, anomaly halt
- [ ] Kill-switch: Telegram command + automatic
- [ ] Execution vs cost-model reconciliation after each rebalance
- [ ] Prod `docker-compose.yml` with healthchecks and per-role secrets
- [ ] CI `.github/workflows/ci.yml`: ruff, mypy, pytest, compose config, image build; required for merge
- [ ] Image publishing to GHCR (version + SHA tags)
- [ ] CD `.github/workflows/deploy.yml`: SSH deploy, pull → Alembic migrations → up -d; `production` environment with required reviewer
- [ ] Healthcheck verification + automatic rollback + manual rollback via `workflow_dispatch`
- [ ] Telegram deploy notifications
- [ ] First successful automatic deploy to VPS (≤ $10/month)
- [ ] Telegram: rebalance report, warnings, daily/weekly/monthly digests
- [ ] Start with minimum capital; scale only after user confirmation
- [ ] `docs/guides/stage-3-user-guide.md`, `chore: complete stage 2`, tag `v0.2.0`

## Stage 3 — Growth and analytics (only on Go) · branch `stage-3-dashboard`

- [ ] FastAPI admin dashboard, owner-only auth (Basic/JWT)
- [ ] Analytics API: top profit by day/week/month/all-time, top trades/rebalances, top coins (profit and loss), top factors and sleeves
- [ ] Chart.js UI: cumulative PnL, equity vs BTC vs backtest, drawdown, turnover/costs, funding, leverage
- [ ] Tables: current book, recent rebalances, errors
- [ ] Factor attribution, backtest vs live decay tracking
- [ ] System health metrics (worker uptime, data lag, API errors, rate-limit headroom)
- [ ] Factor and exchange plugins; multiple portfolio sleeves with risk-based capital allocation
- [ ] Backups, monitoring, profiling
- [ ] `chore: complete stage 3`, tag `v0.3.0`
