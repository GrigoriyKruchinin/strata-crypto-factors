# CLAUDE.md — Strata (strata-crypto-factors)

Systematic, market-neutral cross-sectional factor portfolio on Binance USDT-M perpetual futures.
Full spec of stages lives in `todo.md` and `docs/`; this file holds only what every session needs.

## Session start protocol

1. Read `CLAUDE.md` and `todo.md`.
2. Find the first unchecked `- [ ]` task in the current stage and continue from it.
3. State of the project = files (`todo.md`, git history, `docs/reports/`, experiment log), not chat memory.

## Language policy

- Code, comments, docstrings, prompts, architecture docs, `README.md`: **English**.
- Communication with the user, user guides (`docs/guides/`), the "Простыми словами" report block: **Russian**, plain language (explain jargon at first mention).
- User guides are written to files only; chat gets a one-line pointer.

## Agreed parameters (Stage 0, 2026-10-19)

| Parameter | Value |
|---|---|
| Exchange (V1, V2) | Binance USDT-M Futures |
| Planned live capital (Stage 2) | $1,000–$5,000 → compact book, ~8–10 longs + ~8–10 shorts |
| Default rebalance | weekly (daily is also tested in Stage 1) |
| Max gross leverage | 2x |
| Max drawdown (auto-stop) | 25% |
| VPS budget (Stage 2) | ≤ $10/month |
| Go/No-Go thresholds | defaults, see `todo.md` → "Go / No-Go criteria" |
| "Plus to deposit" (mandatory) | net monthly return on unseen data > 0 (hard); 1.5%/month is the reference level, final call discussed with the user (agreed 2026-10-20) |

## Research discipline (non-negotiable)

- **Train / selection period:** 2020-01-01 – 2023-12-31.
- **Holdout:** 2024-01-01 – present. Opened **once**, after the candidate set is frozen and logged. No tuning after viewing it. If reopened for a new iteration, it is "burned"; use a fresh unseen segment.
- Every backtest includes fees, slippage, funding for actual holding time, and rebalance turnover.
- No look-ahead: signal at close of `t`, execution at next bar. Enforced by tests.
- No survivorship: point-in-time universe, delisted symbols kept.
- Every tested variation is written to the experiment log; report the count and correct for multiple testing.
- Go/No-Go thresholds are fixed before the holdout is opened and never moved afterwards.

## Commands

```bash
uv sync                      # install deps
make lint                    # ruff check + ruff format --check
make typecheck               # mypy --strict
make test                    # pytest
make check                   # lint + typecheck + test
docker compose -f docker-compose.local.yml config   # validate local stack
docker compose -f docker-compose.local.yml up -d    # run Stage 1 stack
```

## Code style

- Python 3.12, `uv`, `pyproject.toml` + `uv.lock`.
- `mypy --strict` clean, `ruff` clean. No `Any` without justification.
- SOLID: narrow interfaces (`IMarketDataSource`, `IUniverseProvider`, `IFactor`, `IPortfolioConstructor`, `ICostModel`, `IOrderGateway`, `IRiskRule`); DI via factories/containers. Signal and portfolio logic are identical across simulator / paper / live gateways.
- `Decimal` for prices, quantities and PnL in accounting/execution layers; respect `tickSize`, `stepSize`, `minNotional`. pandas/numpy allowed in research/backtest layers.
- Pydantic v2 + pydantic-settings, modular settings groups; each container gets only the env vars it needs. Trading keys visible only to the trading worker.
- Fixed seeds, data-version stamps for reproducibility.
- Never print large dumps (logs, candles, result tables) into chat: save to file, show summary + path.

## Git workflow

- `main` is stable. Stage branches: `stage-1-mvp`, `stage-2-prod`, `stage-3-dashboard`; merge into `main` after all stage checks pass.
- Per task: implement → `make check` (+ `docker compose config` for infra) → tick `todo.md` → commit → push.
- Conventional Commits in English (`feat(factors): ...`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`); `todo.md` updates go into the same commit. Small atomic commits.
- Before every commit: `git diff --staged` reviewed for secrets. Never commit `.env`, keys, DB dumps.
- Forbidden without explicit user permission: `git push --force` to `main`, history rewrites, branch deletion.
- Push failure: one attempt to fix (`git pull --rebase`, check remote), then report to the user.
- Stage end: all stage items ticked → `chore: complete stage N` → tag (`v0.1.0` / `v0.2.0` / `v0.3.0`) → push commits and tags → short Russian summary → update README status badge → recommend `/clear`.
- **Stage transitions always need explicit user confirmation** (especially Stage 2: real money).

## Context management

- After a large task is committed and pushed, tell the user (in Russian): "Задача закоммичена, `todo.md` актуален. Если контекст разросся, можно сделать `/clear` и написать "продолжай": я продолжу по `todo.md`".
- Delegate heavy reading (exchange API docs, big dumps, wide code search) to subagents; keep only conclusions.

**When compacting context, always preserve:** current stage and current task from `todo.md`, list of modified files, verification commands (`make lint`, `make typecheck`, `make test`), decisions taken, train/holdout boundaries (train 2020-01-01–2023-12-31, holdout 2024-01-01–present), open questions to the user.

## Protocol: fork after Stage 1 (Go / Iterate / Research toolkit)

After Stage 1 do **not** proceed automatically. Open `docs/reports/stage-1-go-no-go.md`, discuss results honestly with the user in plain Russian, propose one outcome:

1. **Go** — all criteria met → write `docs/guides/stage-2-user-guide.md`, wait for user confirmation, start Stage 2.
2. **Iterate** — borderline → at most 1–2 iterations; goals and criteria recorded in `todo.md`; viewed holdout is burned, use a fresh unseen segment (newer data + continued paper trading).
3. **No-Go** → only after the user explicitly confirms "we won't develop it as an income source": reposition as **"Crypto Factor Research Toolkit"**. Rewrite `README.md` (neutral tone, exact Stage 1 results, no "pet"/"No-Go" wording; header style kept, status badge e.g. "research toolkit"), `CLAUDE.md` and `.claude/` (critic becomes "Security & Code Quality Critic", remove execution/live-trading skills and any mention of later stages), `todo.md` (drop Stages 2–3, add "Polish & docs"), remove live-execution code and trading env vars. **Remove all Docker infrastructure without asking**: compose files, Dockerfiles, `.dockerignore`, deploy/image workflows, Docker Makefile targets and every Docker mention in docs/guides/`.env.example`; drop server-only services (Redis/Celery, long-running workers); storage becomes local (SQLite or Parquet/CSV), run via `uv run ...` and `Makefile`; keep `.github/workflows/ci.yml` for ruff/mypy/pytest only; verify install + tests on a clean machine without Docker; no "Deployment" section in README. Neutral `CHANGELOG.md` entry, atomic commits (`docs: reposition project as research toolkit`, `chore: remove execution plans`, `chore: remove docker infrastructure`), tag `v1.0.0`, push, summarize in Russian. Nothing is deleted before the user's explicit confirmation of No-Go.

## Safety

- No secrets in the repo; `.env` (ignored) + `.env.example`.
- API keys: futures trading only, **no withdrawal permission**, IP-whitelisted. Stage 1 needs no keys.
- Logs never contain keys or private data.
- Before each release: `make lint`, `make typecheck`, `make test`, `/audit-risks`.
- Reports label results as historical/simulated, never as forecasts.
