"""Adapter interface and result types.

Every database exposes the same narrow interface. The shared runner drives
all platforms through this interface, which is what keeps the methodology
identical: the same warm-up, the same iteration count, the same percentile
math, and the same logical queries (translated per platform).
"""
from __future__ import annotations

import math
import statistics
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


def percentile(sorted_vals: list[float], p: float) -> float:
    """Linear-interpolated percentile (numpy 'linear' / type-7 semantics)."""
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(f)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


@dataclass
class LatencyResult:
    label: str
    unit: str = "ms"
    values: list[float] = field(default_factory=list)
    failures: int = 0
    notes: str = ""

    def _sorted(self) -> list[float]:
        return sorted(self.values)

    @property
    def count(self) -> int:
        return len(self.values)

    @property
    def p50(self) -> float:
        return percentile(self._sorted(), 0.50)

    @property
    def p95(self) -> float:
        return percentile(self._sorted(), 0.95)

    @property
    def mean(self) -> float:
        return statistics.mean(self.values) if self.values else float("nan")

    @property
    def std(self) -> float:
        return statistics.stdev(self.values) if len(self.values) > 1 else 0.0

    @property
    def vmin(self) -> float:
        return min(self.values) if self.values else float("nan")

    @property
    def vmax(self) -> float:
        return max(self.values) if self.values else float("nan")

    def summary(self) -> dict:
        return {
            "label": self.label,
            "unit": self.unit,
            "iterations": self.count,
            "failures": self.failures,
            "p50": round(self.p50, 3),
            "p95": round(self.p95, 3),
            "mean": round(self.mean, 3),
            "std": round(self.std, 3),
            "min": round(self.vmin, 3),
            "max": round(self.vmax, 3),
            "notes": self.notes,
        }


@dataclass
class IngestResult:
    label: str
    nodes: int = 0
    relationships: int = 0
    wall_seconds: float = 0.0
    nodes_per_second: float = 0.0
    rels_per_second: float = 0.0
    notes: str = ""

    def summary(self) -> dict:
        return {
            "label": self.label,
            "nodes": self.nodes,
            "relationships": self.relationships,
            "wall_seconds": round(self.wall_seconds, 3),
            "nodes_per_second": round(self.nodes_per_second, 1),
            "rels_per_second": round(self.rels_per_second, 1),
            "notes": self.notes,
        }


@dataclass
class MixedResult:
    label: str
    clients: int = 0
    read_ratio: float = 0.0
    write_ratio: float = 0.0
    duration_seconds: float = 0.0
    total_ops: int = 0
    ops_per_second: float = 0.0
    failures: int = 0

    def summary(self) -> dict:
        return {
            "label": self.label,
            "clients": self.clients,
            "read_ratio": round(self.read_ratio, 2),
            "write_ratio": round(self.write_ratio, 2),
            "duration_seconds": round(self.duration_seconds, 3),
            "total_ops": self.total_ops,
            "ops_per_second": round(self.ops_per_second, 1),
            "failures": self.failures,
        }


@dataclass
class FootprintResult:
    label: str
    observables: dict = field(default_factory=dict)
    notes: str = ""

    def summary(self) -> dict:
        return {"label": self.label, "observables": self.observables, "notes": self.notes}


class DatabaseAdapter(ABC):
    """Uniform interface implemented by every platform adapter.

    The ``q_*`` methods each execute exactly one logical operation and
    return; the runner owns timing, warm-up, iteration counts and
    concurrency. Implementations must be safe to call from multiple
    threads (the mixed-workload runner uses one thread per client), which
    adapters achieve with per-thread sessions/connections.
    """

    name: str = ""
    label: str = ""

    def __init__(self, connection: dict[str, str]):
        self.connection = connection

    # -- lifecycle ---------------------------------------------------------
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    # -- schema ------------------------------------------------------------
    @abstractmethod
    def reset(self) -> None:
        """Clear all benchmark data so a fresh load starts clean."""

    @abstractmethod
    def create_schema(self) -> None:
        """Create the same indexes everywhere (idempotent): index(id), index(age), index(gender)."""

    # -- ingest ------------------------------------------------------------
    @abstractmethod
    def load(self, nodes_path: str | Path, edges_path: str | Path) -> IngestResult:
        """Reset, create schema, and ingest; return throughput timings."""

    # -- queries (one logical operation each) ------------------------------
    @abstractmethod
    def q_point(self, node_id: int) -> object:
        """Point lookup of a single node by unique id."""

    @abstractmethod
    def q_filter(self, age: int) -> object:
        """Filtered lookup on the indexed `age` property (age > threshold)."""

    @abstractmethod
    def q_traversal(self, depth: int, node_id: int) -> object:
        """Return distinct nodes exactly `depth` hops from `node_id`."""

    @abstractmethod
    def q_aggregate(self) -> object:
        """Group-by aggregation (count nodes per gender)."""

    @abstractmethod
    def q_read(self, node_id: int) -> object:
        """Lightweight read used by the mixed workload."""

    @abstractmethod
    def q_write(self, node_id: int) -> object:
        """Bounded write (update a property) used by the mixed workload."""

    # -- validation / footprint -------------------------------------------
    @abstractmethod
    def counts(self) -> tuple[int, int]:
        """Return (node_count, relationship_count) for post-load validation."""

    @abstractmethod
    def footprint(self) -> FootprintResult: ...


def iter_nodes(path: str | Path) -> Iterator[dict]:
    import csv

    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            yield {
                "id": int(row["id"]),
                "gender": int(row["gender"]) if row["gender"] else None,
                "region": row["region"] or None,
                "age": int(row["age"]) if row["age"] else None,
            }


def iter_edges(path: str | Path) -> Iterator[tuple[int, int]]:
    import csv

    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            yield (int(row["src"]), int(row["dst"]))
