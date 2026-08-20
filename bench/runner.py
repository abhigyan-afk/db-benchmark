"""Shared benchmark runner.

This module owns the methodology so every platform is measured identically:
the same warm-up count, the same iteration count, the same start-node seed,
and the same percentile math. Adapters only translate logical operations to
their native query language.
"""
from __future__ import annotations

import random
import threading
import time
from typing import Callable, Sequence

from .adapters.base import DatabaseAdapter, LatencyResult, MixedResult
from .dataset import pick_start_nodes, pick_traversal_start_nodes

# Methodology defaults (documented in the README).
WARMUP = 20
ITERATIONS = 100          # >= 100 per the assignment
MIXED_CLIENTS = 10
MIXED_DURATION_S = 30.0
READ_RATIO = 0.9
WRITE_RATIO = 1.0 - READ_RATIO
AGE_THRESHOLD = 25
START_NODES = 20
WRITE_NODES = 50
PROBE_NODES = 10
SEED = 42


def run_latency(
    call: Callable[[], object],
    *,
    warmup: int = WARMUP,
    iterations: int = ITERATIONS,
    label: str = "",
) -> LatencyResult:
    """Time `call` for `iterations` runs after `warmup` discarded runs.

    Warm-up failures are counted, and if *every* warm-up iteration fails the
    workload is aborted rather than measured against a broken query.
    """
    warmup_failures = 0
    for _ in range(warmup):
        try:
            call()
        except Exception:
            warmup_failures += 1
    if warmup_failures == warmup:
        raise RuntimeError(f"{label}: all {warmup} warm-up iterations failed")

    values: list[float] = []
    failures = 0
    for _ in range(iterations):
        t0 = time.perf_counter()
        try:
            call()
            values.append((time.perf_counter() - t0) * 1000.0)
        except Exception:
            failures += 1
    return LatencyResult(
        label=label, values=values, failures=failures, warmup_failures=warmup_failures
    )


def _rotating(fn: Callable[[int], object], ids: Sequence[int]) -> Callable[[], object]:
    i = 0
    n = len(ids)

    def call() -> object:
        nonlocal i
        r = fn(ids[i % n])
        i += 1
        return r

    return call


def run_mixed(
    adapter: DatabaseAdapter,
    read_ids: Sequence[int],
    write_ids: Sequence[int],
    *,
    clients: int = MIXED_CLIENTS,
    duration_s: float = MIXED_DURATION_S,
    read_ratio: float = READ_RATIO,
    seed: int = SEED,
) -> MixedResult:
    """Concurrent read/write throughput, tracking actual read vs write counts."""
    stop_at = time.time() + duration_s
    reads = [0] * clients
    writes = [0] * clients
    failures = [0] * clients
    barrier = threading.Barrier(clients)

    def worker(idx: int) -> None:
        rng = random.Random(seed + idx)
        barrier.wait()  # synchronised start
        while time.time() < stop_at:
            if rng.random() < read_ratio:
                node = rng.choice(read_ids)
                try:
                    adapter.q_read(node)
                    reads[idx] += 1
                except Exception:
                    failures[idx] += 1
            else:
                node = rng.choice(write_ids)
                try:
                    adapter.q_write(node)
                    writes[idx] += 1
                except Exception:
                    failures[idx] += 1

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(clients)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    actual = time.perf_counter() - t0

    total_reads = sum(reads)
    total_writes = sum(writes)
    return MixedResult(
        label="mixed",
        clients=clients,
        read_ratio=read_ratio,
        write_ratio=1.0 - read_ratio,
        duration_seconds=actual,
        total_ops=total_reads + total_writes,
        read_ops=total_reads,
        write_ops=total_writes,
        failures=sum(failures),
    )


def benchmark(
    adapter: DatabaseAdapter,
    *,
    nodes: list[dict],
    edges: list[tuple[int, int]],
    warmup: int = WARMUP,
    iterations: int = ITERATIONS,
    mixed_clients: int = MIXED_CLIENTS,
    mixed_duration_s: float = MIXED_DURATION_S,
    read_ratio: float = READ_RATIO,
    seed: int = SEED,
) -> dict:
    """Run the full read/mixed workload suite and return a summary dict."""
    ids = [n["id"] for n in nodes]
    traversal_ids = pick_traversal_start_nodes(ids, edges, START_NODES, seed)
    point_ids = pick_start_nodes(ids, START_NODES, seed + 1)
    write_ids = pick_start_nodes(ids, WRITE_NODES, seed + 2)

    results: dict = {
        "database": adapter.name,
        "label": adapter.label,
        "params": {
            "warmup": warmup,
            "iterations": iterations,
            "mixed_clients": mixed_clients,
            "mixed_duration_s": mixed_duration_s,
            "read_ratio": read_ratio,
            "write_ratio": 1.0 - read_ratio,
            "age_threshold": AGE_THRESHOLD,
            "start_nodes": START_NODES,
            "seed": seed,
        },
        "lookups": {
            "point": run_latency(
                _rotating(adapter.q_point, point_ids),
                warmup=warmup, iterations=iterations, label="point_lookup",
            ).summary(),
            "filter": run_latency(
                lambda: adapter.q_filter(AGE_THRESHOLD),
                warmup=warmup, iterations=iterations, label="filtered_lookup_age",
            ).summary(),
        },
        "traversals": {
            depth: run_latency(
                _rotating(lambda nid, d=depth: adapter.q_traversal(d, nid), traversal_ids),
                warmup=warmup, iterations=iterations, label=f"traversal_{depth}_hop",
            ).summary()
            for depth in (1, 2, 3)
        },
        "aggregations": {
            "gender": run_latency(
                adapter.q_aggregate, warmup=warmup, iterations=iterations, label="aggregation_gender"
            ).summary(),
            "relationship_type": run_latency(
                adapter.q_aggregate_rels, warmup=warmup, iterations=iterations, label="aggregation_rel_type"
            ).summary(),
        },
        "mixed": run_mixed(
            adapter, ids, write_ids,
            clients=mixed_clients, duration_s=mixed_duration_s,
            read_ratio=read_ratio, seed=seed,
        ).summary(),
    }
    return results


def run_correctness_probes(
    adapter: DatabaseAdapter,
    probe_ids: Sequence[int],
    *,
    age_threshold: int = AGE_THRESHOLD,
) -> dict:
    """Deterministic, count-based probes used to cross-check platforms.

    Every probe returns a stable number (not an ordered list), so the same
    dataset must yield identical values on every platform.
    """
    return {
        "point_lookup": {str(n): adapter.probe_point(n) for n in probe_ids},
        "filtered_count_age": adapter.probe_filter(age_threshold),
        "traversals": {
            str(n): {str(d): adapter.probe_traversal(d, n) for d in (1, 2, 3)}
            for n in probe_ids
        },
        "aggregate_gender": adapter.probe_aggregate(),
    }


def pick_probe_nodes(ids: list[int], edges: list[tuple[int, int]], n: int = PROBE_NODES, seed: int = SEED + 10) -> list[int]:
    return pick_traversal_start_nodes(ids, edges, n, seed)
