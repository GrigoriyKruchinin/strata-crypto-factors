"""Holdout guard: the holdout period can be evaluated exactly once, on a frozen candidate set."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


class HoldoutViolationError(RuntimeError):
    pass


@dataclass(frozen=True)
class HoldoutGuard:
    holdout_start: date
    state_dir: Path

    @property
    def freeze_path(self) -> Path:
        return self.state_dir / "frozen-candidates.json"

    @property
    def opened_path(self) -> Path:
        return self.state_dir / "holdout-opened.json"

    @property
    def start_ts(self) -> pd.Timestamp:
        return pd.Timestamp(self.holdout_start, tz="UTC")

    def check_research_period(self, end: pd.Timestamp) -> None:
        """Research (selection) runs must end before the holdout starts."""
        if end >= self.start_ts:
            raise HoldoutViolationError(
                f"research run ends {end.date()} inside holdout (starts {self.holdout_start})"
            )

    def is_frozen(self) -> bool:
        return self.freeze_path.exists()

    def is_opened(self) -> bool:
        return self.opened_path.exists()

    def freeze(self, spec_ids: list[str], details: dict[str, Any]) -> None:
        if self.is_frozen():
            raise HoldoutViolationError("candidate set is already frozen")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "frozen_at": datetime.now(UTC).isoformat(),
            "spec_ids": spec_ids,
            "details": details,
        }
        self.freeze_path.write_text(json.dumps(payload, indent=2))

    def frozen_spec_ids(self) -> list[str]:
        if not self.is_frozen():
            raise HoldoutViolationError("freeze the candidate set before opening the holdout")
        ids: list[str] = json.loads(self.freeze_path.read_text())["spec_ids"]
        return ids

    def open_once(self, spec_ids: list[str]) -> None:
        """Mark the holdout as opened; any later opening is refused (the holdout is burned)."""
        frozen = set(self.frozen_spec_ids())
        if self.is_opened():
            raise HoldoutViolationError(
                "holdout already opened: it is burned; use a new unseen segment for iterations"
            )
        if not set(spec_ids) <= frozen:
            raise HoldoutViolationError("only frozen candidates may be evaluated on the holdout")
        payload = {"opened_at": datetime.now(UTC).isoformat(), "spec_ids": spec_ids}
        self.opened_path.write_text(json.dumps(payload, indent=2))
