"""Tests for the harness core: percentile math, start-node selection, and the
dry-run pipeline. These run with no database credentials (mock adapter only)."""
from __future__ import annotations

import json
from pathlib import Path

from bench.adapters.base import LatencyResult, iter_edges, iter_nodes, percentile
from bench.adapters.mock import MockAdapter
from bench.dataset import pick_start_nodes, pick_traversal_start_nodes
from bench.runner import benchmark

DATA = Path("data")


def test_percentile_interpolation():
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert percentile([1, 2, 3, 4], 0.0) == 1.0
    assert percentile([1, 2, 3, 4], 1.0) == 4.0
    assert percentile([1, 2, 3, 4, 5], 0.5) == 3.0
    assert percentile([1, 2, 3, 4, 5], 0.95) == 4.8
    assert percentile([], 0.5) != percentile([], 0.5)  # NaN


def test_latency_result_summary():
    r = LatencyResult(label="x", values=[1.0, 2.0, 3.0, 4.0, 5.0], failures=0)
    s = r.summary()
    assert s["p50"] == 3.0
    assert s["p95"] == 4.8
    assert s["iterations"] == 5
    assert s["failures"] == 0


def test_pick_start_nodes_deterministic():
    ids = list(range(1000))
    assert pick_start_nodes(ids, 20, 42) == pick_start_nodes(ids, 20, 42)
    assert len(set(pick_start_nodes(ids, 20, 42))) == 20


def test_traversal_start_nodes_respect_degree_band():
    ids = [1, 2, 3, 4, 5, 6]
    edges = [(1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7)]
    picked = pick_traversal_start_nodes(ids, edges, n=10, seed=42, min_deg=5, max_deg=30)
    assert picked == [1]  # only node 1 has out-degree in [5, 30]


def test_dataset_counts_match_metadata():
    meta = json.loads((DATA / "dataset.json").read_text())
    nodes = list(iter_nodes(DATA / "nodes.csv"))
    edges = list(iter_edges(DATA / "edges.csv"))
    assert len(nodes) == meta["sampled_nodes"]
    assert len(edges) == meta["sampled_edges"]
    assert meta["sampled_edges"] >= 100_000


def test_dry_run_pipeline():
    nodes = list(iter_nodes(DATA / "nodes.csv"))
    edges = list(iter_edges(DATA / "edges.csv"))
    adapter = MockAdapter({})
    adapter.connect()
    adapter.create_schema()
    adapter.load(DATA / "nodes.csv", DATA / "edges.csv")
    result = benchmark(
        adapter, nodes=nodes, edges=edges,
        warmup=2, iterations=10, mixed_clients=2, mixed_duration_s=0.5,
    )
    adapter.close()

    assert result["database"] == "mock"
    assert result["lookups"]["point"]["iterations"] == 10
    assert result["lookups"]["point"]["failures"] == 0
    assert set(result["traversals"].keys()) == {1, 2, 3}
    assert result["mixed"]["ops_per_second"] > 0
    assert adapter.counts() == (len(nodes), len(edges))
