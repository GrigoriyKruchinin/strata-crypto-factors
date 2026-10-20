"""Append-only experiment log.

Every backtest variation is recorded, including failures and robustness reruns, so the final
report can state how many configurations were tried and correct for multiple testing.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExperimentRecord:
    spec_id: str
    spec_name: str
    period_label: str  # e.g. "train", "walk_forward", "holdout", "random_signal"
    period_start: str
    period_end: str
    config: dict[str, Any]
    metrics: dict[str, float]
    data_version: str
    code_version: str
    kind: str = "candidate"  # candidate | robustness | benchmark
    notes: str = ""
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class IExperimentLog(ABC):
    @abstractmethod
    def append(self, record: ExperimentRecord) -> None: ...

    @abstractmethod
    def records(self) -> list[ExperimentRecord]: ...

    def distinct_variations(self, kind: str = "candidate") -> int:
        """Number of distinct configurations tested (the multiple-testing count)."""
        return len({r.spec_id for r in self.records() if r.kind == kind})


class JsonlExperimentLog(IExperimentLog):
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: ExperimentRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(record), sort_keys=True) + "\n")

    def records(self) -> list[ExperimentRecord]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [ExperimentRecord(**json.loads(line)) for line in lines if line.strip()]


def git_version(cwd: Path | None = None) -> str:
    """Short SHA plus a dirty marker, so results are tied to exact code."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha
