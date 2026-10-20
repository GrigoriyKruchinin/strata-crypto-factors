---
name: audit-risks
description: Run a security, code-quality and research-validity audit of the current branch using the security-code-quality-critic agent. Use before merging to main and before every release.
---

1. Determine scope: `git diff main...HEAD --stat` (or the whole repo before a release).
2. Delegate the review to the `security-code-quality-critic` agent with the scope and its checklist.
3. Quick secret scan: `git diff main...HEAD | grep -nEi '(api[_-]?key|secret|token|password)\s*[:=]\s*["'"'"']?[A-Za-z0-9]{12,}'` and confirm `.env` is not tracked (`git ls-files | grep -E '^\.env$'` must be empty).
4. Summarise findings by severity. Any BLOCKER stops the merge/release until fixed.
5. After fixes, re-run the relevant checks and record the outcome.
