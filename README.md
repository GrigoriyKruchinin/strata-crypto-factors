<div align="center">

<img src="docs/assets/logo.svg" alt="Strata logo" width="180">

# Strata

**Systematic market-neutral factor portfolio for crypto perpetual futures — research, backtesting and paper trading.**

Built on free public Binance USDT-M Futures data (klines, funding history, full instrument list including delisted contracts).
Ranks a point-in-time liquid universe by momentum, reversal, volatility, liquidity, funding carry and BTC beta, and evaluates
dollar-neutral long/short books net of fees, slippage, funding and turnover. Results go to PostgreSQL and Telegram.

[![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![mypy](https://img.shields.io/badge/mypy-strict-2A6DB2)](https://mypy-lang.org/)
[![ruff](https://img.shields.io/badge/lint-ruff-D7FF64?logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![docker compose](https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![status](https://img.shields.io/badge/status-V1%20research%20complete-6B7280)](todo.md)

</div>

## Features

- **Survivorship-free data** — daily klines and funding for every Binance USDT-M perpetual since 2020,
  including delisted contracts, from the free `data.binance.vision` archive (SHA-256 verified,
  resumable) plus the public REST API for the current month. Zero-volume post-delisting bars are dropped.
- **Point-in-time universe** — top-N by trailing 30-day quote volume, minimum listing age and liquidity.
- **Factor library** (`IFactor`) — momentum (with skip window), short-term reversal, low volatility,
  small size, funding carry, low beta to BTC; signs fixed a priori; cross-sectional rank composites.
- **Dollar-neutral portfolio construction** — quantile long/short, equal or inverse-vol weights,
  per-coin cap, gross-leverage cap, optional vol targeting and turnover limit.
- **Conservative cost model** — taker fees, square-root market-impact slippage, funding over the
  actual holding period, forced exits on delisting; 2x-cost sensitivity.
- **Research discipline built in** — pre-registered candidate grid, append-only experiment log,
  holdout guard (holdout can be opened once, for frozen candidates only), walk-forward, regime
  breakdown, 1000-run random-signal test, top-coin exclusion, BTC / equal-weight benchmarks,
  deflated Sharpe.
- **Paper trading** — same signals and cost model on live public data, `Decimal` accounting,
  step-size / min-notional order sizing, reconciliation against a backtest of the same days.
- **Telegram reports** — new target book, daily and weekly results, reconciliation, warnings.
- **No-look-ahead tests** — every factor, the universe and the full backtest are checked by
  truncation and future-scrambling tests.

## Quick start

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Docker with Compose v2.

```bash
cp .env.example .env            # set DB_PASSWORD, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
uv sync
make check                      # ruff + mypy --strict + pytest
make download-history           # ~1-2 h first time, incremental afterwards
make research STEP=train        # pre-registered grid on 2020-04-01..2023-12-31
make research STEP=robustness
make research STEP=freeze
docker compose -f docker-compose.local.yml up -d --build   # paper trading + Telegram
make research STEP=holdout      # once: 2024-01-01..latest
```

## Architecture

```
data.binance.vision ─┐                 ┌─> IUniverseProvider ─┐
Binance public REST ─┴─> HistoryLoader ─> ParquetStore ─> MarketPanel ─> IFactor ───────────┼─> IPortfolioConstructor ─> target weights
                                │                                                           │            │
                                └─> PostgreSQL (candles, funding, experiments, paper state)  ICostModel ─┤
                                                                                                         ├─> Backtester (research)
                                                                                                         └─> PaperTrader -> SimulatedGateway (IOrderGateway)
Celery beat 00:15 UTC: refresh_data [data] -> paper_cycle [paper] -> notify [notify] -> Telegram
```

| Package | Responsibility |
|---|---|
| `strata.domain` | entities (`Decimal`), `MarketPanel`, interfaces |
| `strata.data` | archive/REST clients, loader, parquet store, quality report |
| `strata.universe`, `strata.factors`, `strata.portfolio`, `strata.costs` | signal and book construction |
| `strata.backtest` | event-ordered daily simulator and metrics |
| `strata.research` | specs, grid, experiment log, holdout guard, validation, pipeline |
| `strata.paper` | order sizing, simulated gateway, paper trader, reconciliation |
| `strata.notify` | Telegram notifier and messages |
| `strata.infra` | SQLAlchemy models, Alembic, Celery, composition root, DB ingest |

**Timing contract.** Bar `d` is known after `d+1 00:00 UTC`. Signals use rows `<= d`, trades fill at
`open[d+1]`, positions held over bar `d` pay the funding settled in `(d, d+1]`.

Local stack (`docker-compose.local.yml`): `postgres`, `redis`, `migrations`, `data-loader`,
`paper-trader`, `telegram-worker`, `beat`, plus a `backtester` tool profile. Every service has a
healthcheck; each role receives only the environment it needs (the Telegram token lives only in
`telegram-worker`; there are no exchange keys in Stage 1).

## Configuration

All settings are environment variables grouped by prefix (`APP_`, `DB_`, `REDIS_`, `EXCHANGE_`,
`DATA_`, `RESEARCH_`, `UNIVERSE_`, `FACTOR_`, `PORTFOLIO_`, `COST_`, `RISK_`, `TELEGRAM_`, `PAPER_`);
see [.env.example](.env.example) and `src/strata/config/settings.py`.

Research periods: train/selection 2020-01-01 – 2023-12-31, holdout 2024-01-01 – present (opened once).

## Roadmap

1. **Stage 1 — MVP + research:** data, factors, cost-aware backtester, validity checks, experiment log, paper trading, Telegram. Go/No-Go report in `docs/reports/`.
2. **Stage 2 — Production:** live execution, risk manager and kill-switch, CI/CD deploy to VPS. Only if Stage 1 passes Go/No-Go.
3. **Stage 3 — Analytics:** owner-only dashboard, factor attribution, backtest-vs-live tracking.

> All results are historical or simulated and are not a forecast or financial advice.
