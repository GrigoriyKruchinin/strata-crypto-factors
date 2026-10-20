---
name: check-code-quality
description: Run ruff lint/format check and mypy --strict for Strata, then fix reported issues. Use before every commit.
---

1. Run `make lint` and `make typecheck`.
2. If either fails, fix the issues in the source (do not add blanket `# type: ignore` or `noqa`; a targeted ignore needs a one-line justification comment).
3. Re-run until both are clean.
4. Report: commands run, pass/fail, number of issues fixed. Do not paste full tool output if it is long; summarize and save to the scratchpad if needed.
