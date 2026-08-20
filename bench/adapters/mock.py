"""Mock adapter — exercises the full runner→report pipeline with no cloud.

Latencies are simulated with tiny sleeps so a dry-run produces a plausible
(and obviously fake) results matrix without touching any database.
"""
from __future__ import annotations

import time
from pathlib import Path

from .base import (
    DatabaseAdapter,
    FootprintResult,
    IngestResult,
    iter_edges,
    iter_nodes,
)


class MockAdapter(DatabaseAdapter):
    name = "mock"
    label = "Mock (dry-run, fake latencies)"

    def __init__(self, connection: dict | None = None):
        super().__init__(connection or {})
        self._nodes = 0
        self._edges = 0

    def connect(self) -> None:
        return None

    def close(self) -> None:
        return None

    def create_schema(self) -> None:
        return None

    def reset(self) -> None:
        self._nodes = 0
        self._edges = 0

    def load(self, nodes_path: str | Path, edges_path: str | Path) -> IngestResult:
        t0 = time.perf_counter()
        self._nodes = sum(1 for _ in iter_nodes(nodes_path))
        self._edges = sum(1 for _ in iter_edges(edges_path))
        dt = time.perf_counter() - t0
        return IngestResult(
            label="ingest",
            nodes=self._nodes,
            relationships=self._edges,
            wall_seconds=dt,
            nodes_per_second=self._nodes / dt if dt else 0.0,
            rels_per_second=self._edges / dt if dt else 0.0,
            notes="simulated",
        )

    def q_point(self, node_id: int) -> object:
        time.sleep(0.0004)
        return node_id

    def q_filter(self, age: int) -> object:
        time.sleep(0.0008)
        return age

    def q_traversal(self, depth: int, node_id: int) -> object:
        time.sleep(0.0005 * depth)
        return (node_id, depth)

    def q_aggregate(self) -> object:
        time.sleep(0.001)
        return {"0": 26395, "1": 23288}

    def q_read(self, node_id: int) -> object:
        time.sleep(0.0003)
        return node_id

    def q_write(self, node_id: int) -> object:
        time.sleep(0.001)
        return node_id

    def counts(self) -> tuple[int, int]:
        return (self._nodes, self._edges)

    def footprint(self) -> FootprintResult:
        return FootprintResult(label="footprint", observables={"note": "not observable"}, notes="mock")
