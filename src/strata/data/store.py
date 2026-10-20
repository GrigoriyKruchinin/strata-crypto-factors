"""Local file store: raw archive cache (checkpoints) and per-symbol parquet tables."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


class Table:
    KLINES_1D = "klines_1d"
    FUNDING = "funding"


@dataclass(frozen=True)
class ParquetStore:
    root: Path

    # ------------------------------------------------------------------ raw cache
    def raw_path(self, dataset: str, symbol: str, period: str) -> Path:
        return self.root / "raw" / dataset / symbol / f"{period}.zip"

    def read_raw(self, dataset: str, symbol: str, period: str) -> bytes | None:
        path = self.raw_path(dataset, symbol, period)
        return path.read_bytes() if path.exists() else None

    def write_raw(self, dataset: str, symbol: str, period: str, payload: bytes) -> None:
        _atomic_write(self.raw_path(dataset, symbol, period), payload)

    # ------------------------------------------------------------------ tables
    def table_path(self, table: str, symbol: str) -> Path:
        return self.root / "parquet" / table / f"{symbol}.parquet"

    def write_table(self, table: str, symbol: str, frame: pd.DataFrame) -> None:
        path = self.table_path(table, symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        frame.to_parquet(tmp, index=False)
        tmp.replace(path)

    def read_table(self, table: str, symbol: str) -> pd.DataFrame | None:
        path = self.table_path(table, symbol)
        return pd.read_parquet(path) if path.exists() else None

    def symbols(self, table: str) -> list[str]:
        directory = self.root / "parquet" / table
        return sorted(p.stem for p in directory.glob("*.parquet")) if directory.exists() else []

    # ------------------------------------------------------------------ metadata
    @property
    def instruments_path(self) -> Path:
        return self.root / "parquet" / "instruments.parquet"

    def write_instruments(self, frame: pd.DataFrame) -> None:
        self.instruments_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(self.instruments_path, index=False)

    def read_instruments(self) -> pd.DataFrame:
        return pd.read_parquet(self.instruments_path)

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def write_manifest(self, manifest: dict[str, Any]) -> None:
        _atomic_write(self.manifest_path, json.dumps(manifest, indent=2, default=str).encode())

    def read_manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {}
        data: dict[str, Any] = json.loads(self.manifest_path.read_text())
        return data

    def data_version(self) -> str:
        """Content hash of all tables: stamps every experiment with the exact data used."""
        digest = hashlib.sha256()
        for table in (Table.KLINES_1D, Table.FUNDING):
            for symbol in self.symbols(table):
                digest.update(f"{table}/{symbol}:".encode())
                digest.update(hashlib.sha256(self.table_path(table, symbol).read_bytes()).digest())
        return digest.hexdigest()[:16]


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(payload)
    tmp.replace(path)
