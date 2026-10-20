<div align="center">

<img src="docs/assets/logo.svg" alt="Strata logo" width="180">

# Strata

**Crypto Factor Research Toolkit — cross-sectional factor research and simulation for crypto perpetual futures.**

Built on free public Binance USDT-M Futures data (daily klines, funding history, full contract list including delisted ones).
Backtests dollar-neutral long/short factor portfolios net of fees, slippage and funding, validates them with walk-forward,
random-signal and coin-exclusion tests, logs every experiment, and simulates a portfolio on live data. Results go to local SQLite, JSON/SVG reports and Telegram.

[![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![mypy](https://img.shields.io/badge/mypy-strict-2A6DB2)](https://mypy-lang.org/)
[![ruff](https://img.shields.io/badge/lint-ruff-D7FF64?logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![CI](https://github.com/GrigoriyKruchinin/strata-crypto-factors/actions/workflows/ci.yml/badge.svg)](https://github.com/GrigoriyKruchinin/strata-crypto-factors/actions/workflows/ci.yml)
[![status](https://img.shields.io/badge/status-research%20toolkit-6B7280)](docs/reports/stage-1-go-no-go.md)

</div>

## What it is for

Strata answers one question with as little self-deception as possible: *does a cross-sectional
factor (momentum, carry, size, ...) earn money on crypto perpetuals after every cost, on data that
was not used to choose it?* The value is in the testing discipline: point-in-time data, a
conservative cost model, pre-registration, an append-only experiment log and a one-time holdout.

## Features

- **Survivorship-free data** — daily klines and funding for every Binance USDT-M perpetual since 2020,
  including delisted contracts, from the free `data.binance.vision` archive (SHA-256 verified,
  resumable cache) plus the public REST API for the current month. Post-delisting zero-volume bars
  are dropped; relisted contracts keep their first life.
- **Point-in-time universe** — top-N by trailing 30-day quote volume, minimum listing age and liquidity.
- **Factor library** (`IFactor`) — momentum (with skip window), short-term reversal, low volatility,
  small size, funding carry, low beta to BTC; signs fixed a priori; rank composites.
- **Dollar-neutral portfolio construction** — quantile long/short, equal or inverse-vol weights,
  per-coin cap, gross-leverage cap, optional vol targeting and turnover limit.
- **Conservative cost model** — taker fees, square-root market-impact slippage, funding over the
  actual holding period, forced exits on delisting; 2x-cost sensitivity.
- **Validation suite** — pre-registered candidate grid, holdout guard (opens once, frozen candidates
  only), walk-forward, bull/bear/sideways breakdown, 1000-run random-signal test, top-coin exclusion,
  BTC / equal-weight benchmarks, deflated Sharpe, SVG equity charts.
- **Experiment log** — every run with parameters, git SHA, data version, period and metrics
  (`docs/research/experiment-log.jsonl`, optionally copied to SQLite).
- **Paper simulation** — the same signals and cost model on live public data, `Decimal`
  accounting, exchange step-size / min-notional sizing, reconciliation against a backtest of the
  same days, optional Telegram reports.
- **No-look-ahead tests** — every factor, the universe and the full backtest are checked by
  truncation and future-scrambling tests.

## Quick start

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/). No database server and no exchange keys.

```bash
git clone https://github.com/GrigoriyKruchinin/strata-crypto-factors.git
cd strata-crypto-factors
cp .env.example .env              # optional: Telegram token/chat id for reports
uv sync
make check                        # ruff + mypy --strict + pytest

make download-history             # ~1-2 h first time (687 contracts), incremental afterwards
make backtest ARGS="--spec funding_carry_14"   # one logged train-period backtest
make research STEP=train          # full pre-registered grid on 2020-04-01..2023-12-31
make research STEP=robustness     # random signals, coin exclusion, regimes, benchmarks
make research STEP=charts         # SVG equity charts into docs/reports/assets/
make paper ARGS="--no-refresh"    # one paper-simulation cycle (local SQLite)
```

To run the paper simulation daily, schedule `uv run strata paper-cycle` shortly after 00:00 UTC
(e.g. with cron). The holdout step of the 2026 study has already been used and is locked by
`docs/research/holdout-opened.json`; new hypotheses need a new, never-viewed evaluation segment.

## Study results (October 2026)

A pre-registered grid of 18 strategies was evaluated on 2020-04 – 2023-12 (110 logged runs in total).
The best train-period strategy was **funding carry** (short coins with high positive funding, long
coins with negative funding): Sharpe 1.12, +27% per year, max drawdown 24%, Sharpe 0.92 at 2x costs,
above the 99.9th percentile of 1000 random-signal portfolios. Warning signs already on train: deflated
Sharpe 0.22 for 18 trials and a walk-forward out-of-sample Sharpe of 0.40. Classic momentum,
reversal and low-volatility factors did not survive costs; daily rebalancing cost 18–24% per year.

On the untouched holdout (2024-01-01 – 2026-10-18) the frozen strategy at its train-derived 0.83x
leverage returned **−32.1% in total (−1.15% per month, Sharpe −0.12, max drawdown 63%)**. Funding
income stayed positive (+41% per year), but short positions in strongly rallying, crowded coins
dominated the result. It ranked at the 61st percentile of random signals. Over the same period BTC
buy-and-hold returned +60% and an equal-weight long portfolio −70%.

Conclusion from the data: no durable, cost-robust cross-sectional edge was found with this factor
set. Full report with methodology, tables, charts and a post-hoc audit:
[full study report](docs/reports/stage-1-go-no-go.md).

![Holdout equity](docs/reports/assets/equity-holdout.svg)

> All results are historical simulations, not forecasts or financial advice.

## Architecture

```
data.binance.vision ─┐                                       ┌─> IUniverseProvider ─┐
Binance public REST ─┴─> HistoryLoader ─> ParquetStore ─> MarketPanel ─> IFactor ─────┼─> IPortfolioConstructor ─> target weights
                                │                                                      │             │
                                └─> SQLite (candles, funding, experiments, paper state)  ICostModel ──┤
                                                                                                      ├─> Backtester ─> ResearchRunner ─> experiment log, reports
                                                                                                      └─> PaperTrader ─> SimulatedGateway (IOrderGateway) ─> Telegram
```

| Package | Responsibility |
|---|---|
| `strata.domain` | entities (`Decimal`), `MarketPanel`, interfaces |
| `strata.data` | archive/REST clients, loader, parquet store, quality report |
| `strata.universe`, `strata.factors`, `strata.portfolio`, `strata.costs` | signal and book construction |
| `strata.backtest` | event-ordered daily simulator and metrics |
| `strata.research` | specs, grid, experiment log, holdout guard, validation, pipeline, charts |
| `strata.paper` | order sizing, simulated gateway, paper trader, reconciliation, daily run |
| `strata.notify` | Telegram notifier and messages |
| `strata.infra` | SQLAlchemy models, Alembic, composition root, DB ingest |

**Timing contract.** Bar `d` is known after `d+1 00:00 UTC`. Signals use rows `<= d`, trades fill at
`open[d+1]`, positions held over bar `d` pay the funding settled in `(d, d+1]`.

**Extending.** Add a factor by implementing `IFactor.compute(panel) -> DataFrame` (rows `<= d` only)
and registering it in `strata.research.spec.FACTOR_CLASSES`; add it to a grid in
`strata.research.grid`; the no-look-ahead helper `tests/lookahead.py` checks it.

## Configuration

Environment variables grouped by prefix (`APP_`, `DB_`, `EXCHANGE_`, `DATA_`, `RESEARCH_`,
`UNIVERSE_`, `FACTOR_`, `PORTFOLIO_`, `COST_`, `PAPER_`, `TELEGRAM_`); see [.env.example](.env.example)
and `src/strata/config/settings.py`. Only public market data is used.

## Project status

Research toolkit. See [CHANGELOG.md](CHANGELOG.md) and [todo.md](todo.md).
