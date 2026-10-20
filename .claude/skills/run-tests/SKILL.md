---
name: run-tests
description: Run the Strata pytest suite (unit, property-based, no-look-ahead tests) and fix failures. Use after any code change and before commits.
---

1. Run `make test` (optionally narrow with `uv run pytest tests/<path> -q` while iterating).
2. On failure, find the root cause. Fix the code, not the test, unless the test is wrong; explain which in the report.
3. Never weaken or delete a no-look-ahead or money-math test to make the suite pass.
4. Re-run the full suite once green locally.
5. Report: pass/fail counts, what was fixed. Summaries only; no full logs in chat.
