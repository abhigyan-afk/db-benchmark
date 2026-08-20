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

# Properties that must be indexed on every platform for the workloads to be
# a fair "indexed" comparison rather than a full-scan comparison.
REQUIRED_INDEXES = ("id", "age", "gender")


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
    warmup_failures: int = 0
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
    def p99(self) -> float:
        return percentile(self._sorted(), 0.99)

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
            "warmup_failures": self.warmup_failures,
            "p50": round(self.p50, 3),
            "p95": round(self.p95, 3),
            "p99": round(self.p99, 3),
            "mean": round(self.mean, 3),
            "std": round(self.std, 3),
            "min": round(self.vmin, 3),
            "max": round(self.vmax, 3),
            "samples_ms": [round(v, 3) for v in self.values],
            "notes": self.notes,
        }


@dataclass
class IngestResult:
    label: str
    nodes: int = 0
    relationships: int = 0
    node_load_seconds: float = 0.0
    index_creation_seconds: float = 0.0
    relationship_load_seconds: float = 0.0
    notes: str = ""

    @property
    def total_seconds(self) -> float:
        return (
            self.node_load_seconds
            + self.index_creation_seconds
            + self.relationship_load_seconds
        )

    @property
    def nodes_per_second(self) -> float:
        return self.nodes / self.node_load_seconds if self.node_load_seconds else 0.0

    @property
    def rels_per_second(self) -> float:
        return self.relationships / self.relationship_load_seconds if self.relationship_load_seconds else 0.0

    def summary(self) -> dict:
        return {
            "label": self.label,
            "nodes": self.nodes,
            "relationships": self.relationships,
            "node_load_seconds": round(self.node_load_seconds, 3),
            "index_creation_seconds": round(self.index_creation_seconds, 3),
            "relationship_load_seconds": round(self.relationship_load_seconds, 3),
            "total_load_seconds": round(self.total_seconds, 3),
            "nodes_per_second": round(self.nodes_per_second, 1),
            "rels_per_second": round(self.rels_per_second, 1),
            "notes": self.notes,
        }


@dataclass
class MixedResult:
    label: str
    clients: int = 0
    read_ratio: float = 0.0      # configured
    write_ratio: float = 0.0     # configured
    duration_seconds: float = 0.0
    total_ops: int = 0
    read_ops: int = 0            # actual
    write_ops: int = 0           # actual
    failures: int = 0

    @property
    def ops_per_second(self) -> float:
        return self.total_ops / self.duration_seconds if self.duration_seconds else 0.0

    @property
    def actual_read_ratio(self) -> float:
        return self.read_ops / self.total_ops if self.total_ops else 0.0

    @property
    def actual_write_ratio(self) -> float:
        return self.write_ops / self.total_ops if self.total_ops else 0.0

    def summary(self) -> dict:
        return {
            "label": self.label,
            "clients": self.clients,
            "configured_read_ratio": round(self.read_ratio, 2),
            "configured_write_ratio": round(self.write_ratio, 2),
            "actual_read_ops": self.read_ops,
            "actual_write_ops": self.write_ops,
            "actual_read_ratio": round(self.actual_read_ratio, 4),
            "actual_write_ratio": round(self.actual_write_ratio, 4),
            "total_ops": self.total_ops,
            "ops_per_second": round(self.ops_per_second, 1),
            "duration_seconds": round(self.duration_seconds, 3),
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
        """Create the indexes used by the workloads (id, age, gender)."""

    @abstractmethod
    def verify_indexes(self) -> None:
        """Raise if any required index (id/age/gender) is missing.

        The benchmark must never silently fall back to a full scan for a
        workload that is supposed to be index-assisted.
        """

    # -- ingest ------------------------------------------------------------
    @abstractmethod
    def load(self, nodes_path: str | Path, edges_path: str | Path) -> IngestResult:
        """Reset, create schema, and ingest; return per-phase timings."""

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
    def q_aggregate_rels(self) -> object:
        """Group-by aggregation over relationship types (count per type)."""

    @abstractmethod
    def q_read(self, node_id: int) -> object:
        """Lightweight read used by the mixed workload."""

    @abstractmethod
    def q_write(self, node_id: int) -> object:
        """Bounded write (update a property) used by the mixed workload."""

    # -- correctness probes (deterministic, comparable across platforms) ---
    @abstractmethod
    def probe_point(self, node_id: int) -> int:
        """Return count of nodes with the given id (0 or 1)."""

    @abstractmethod
    def probe_filter(self, age: int) -> int:
        """Return total count of nodes with age > threshold (no LIMIT)."""

    @abstractmethod
    def probe_traversal(self, depth: int, node_id: int) -> int:
        """Return distinct-node count at exactly `depth` hops."""

    @abstractmethod
    def probe_aggregate(self) -> dict:
        """Return {gender: count} totals."""

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
