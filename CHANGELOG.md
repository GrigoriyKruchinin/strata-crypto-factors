# Changelog

## [1.0.0] — 2026-10-20

### Changed
- Project focus clarified as a research and simulation toolkit: "Crypto Factor Research Toolkit".
- Storage is a local SQLite database (created automatically); everything runs via `uv run strata ...`
  and the `Makefile`. The daily paper simulation is a CLI command that can be scheduled with cron.
- README now documents the October 2026 study (methodology, results, limitations).
- CI runs code-quality checks only (ruff, mypy --strict, pytest).

### Removed
- Container stack and background workers (Redis/Celery), PostgreSQL driver.
- Exchange-credential and risk-limit settings that were only needed for order execution.

### Fixed
- Relisted contracts keep their first listing period in the point-in-time universe.
- Portfolio eligibility uses only signal-time information.
- Holdout runs require an explicitly opened holdout; S3 listings are parsed with `defusedxml`.

## [0.1.0] — 2026-10-20

### Added
- Survivorship-free Binance USDT-M data loader, point-in-time universe, factor library,
  dollar-neutral portfolio construction, conservative cost model, daily backtester.
- Validation suite, experiment log, holdout guard, pre-registered research pipeline.
- Paper simulation with `Decimal` accounting and Telegram reports.
- Study report `docs/reports/stage-1-go-no-go.md`.
