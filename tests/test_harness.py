"""Tests for the harness core: percentile math, start-node selection, the
dry-run pipeline, warm-up handling, mixed accounting, and environment helpers.
These run with no database credentials (mock adapter only)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.adapters.base import IngestResult, LatencyResult, MixedResult, iter_edges, iter_nodes, percentile
from bench.adapters.mock import MockAdapter
from bench.dataset import pick_start_nodes, pick_traversal_start_nodes
from bench.environment import dataset_checksums, machine_info, sha256
from bench.runner import benchmark, run_correctness_probes, run_latency

DATA = Path("data")


def test_percentile_interpolation():
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    assert percentile([1, 2, 3, 4], 0.0) == 1.0
    assert percentile([1, 2, 3, 4], 1.0) == 4.0
    assert percentile([1, 2, 3, 4, 5], 0.5) == 3.0
    assert percentile([1, 2, 3, 4, 5], 0.95) == 4.8
    assert percentile([1, 2, 3, 4, 5], 0.99) == 4.96
    assert percentile([], 0.5) != percentile([], 0.5)  # NaN


def test_latency_result_summary():
    r = LatencyResult(label="x", values=[1.0, 2.0, 3.0, 4.0, 5.0], failures=0)
    s = r.summary()
    assert s["p50"] == 3.0
    assert s["p95"] == 4.8
    assert s["p99"] == 4.96
    assert s["iterations"] == 5
    assert s["failures"] == 0
    assert s["samples_ms"] == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_ingest_result_phases():
    r = IngestResult(
        label="ingest", nodes=100, relationships=50,
        node_load_seconds=2.0, index_creation_seconds=1.0, relationship_load_seconds=5.0,
    )
    assert r.total_seconds == 8.0
    assert r.nodes_per_second == 50.0
    assert r.rels_per_second == 10.0
    s = r.summary()
    assert s["total_load_seconds"] == 8.0
    assert s["nodes_per_second"] == 50.0


def test_mixed_result_ratios():
    r = MixedResult(
        label="mixed", clients=2, read_ratio=0.9, write_ratio=0.1,
        duration_seconds=10.0, total_ops=100, read_ops=90, write_ops=10, failures=0,
    )
    assert r.actual_read_ratio == 0.9
    assert r.actual_write_ratio == 0.1
    s = r.summary()
    assert s["actual_read_ops"] == 90
    assert s["actual_write_ops"] == 10
    assert s["ops_per_second"] == 10.0


def test_warmup_all_failures_abort():
    def boom():
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        run_latency(boom, warmup=3, iterations=5, label="x")


def test_warmup_partial_failures_recorded():
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("first warmup fails")

    r = run_latency(flaky, warmup=3, iterations=5, label="x")
    assert r.warmup_failures == 1
    assert r.count == 5
    assert r.failures == 0


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
    assert "nodes_csv_sha256" in meta  # checksums recorded in the dataset manifest


def test_environment_helpers():
    info = machine_info()
    assert info["python"]
    assert info["os"]
    assert sha256(DATA / "nodes.csv") == dataset_checksums()["nodes_csv_sha256"]


def test_dry_run_pipeline():
    nodes = list(iter_nodes(DATA / "nodes.csv"))
    edges = list(iter_edges(DATA / "edges.csv"))
    adapter = MockAdapter({})
    adapter.connect()
    adapter.create_schema()
    adapter.verify_indexes()
    adapter.load(DATA / "nodes.csv", DATA / "edges.csv")
    result = benchmark(
        adapter, nodes=nodes, edges=edges,
        warmup=2, iterations=10, mixed_clients=2, mixed_duration_s=0.5,
    )
    adapter.close()

    assert result["database"] == "mock"
    assert result["lookups"]["point"]["iterations"] == 10
    assert result["lookups"]["point"]["failures"] == 0
    assert result["lookups"]["point"]["samples_ms"]  # raw samples preserved
    assert set(result["traversals"].keys()) == {1, 2, 3}
    assert set(result["aggregations"].keys()) == {"gender", "relationship_type"}
    assert result["mixed"]["actual_read_ops"] + result["mixed"]["actual_write_ops"] == result["mixed"]["total_ops"]
    assert result["mixed"]["ops_per_second"] > 0
    assert adapter.counts() == (len(nodes), len(edges))


def test_correctness_probes_structure():
    nodes = list(iter_nodes(DATA / "nodes.csv"))
    edges = list(iter_edges(DATA / "edges.csv"))
    adapter = MockAdapter({})
    adapter.connect()
    adapter.load(DATA / "nodes.csv", DATA / "edges.csv")
    from bench.runner import pick_probe_nodes

    probe_ids = pick_probe_nodes([n["id"] for n in nodes], edges)
    probes = run_correctness_probes(adapter, probe_ids)
    adapter.close()

    assert len(probes["point_lookup"]) == len(probe_ids)
    assert isinstance(probes["filtered_count_age"], int)
    assert set(probes["traversals"].keys()) == {str(n) for n in probe_ids}
    assert isinstance(probes["aggregate_gender"], dict)
