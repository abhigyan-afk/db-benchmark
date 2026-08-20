"""Dataset helpers: node lists and deterministic start-node selection.

Start nodes are chosen with a fixed seed so every platform runs the exact
same traversal/lookup inputs. Traversal start nodes are restricted to a
moderate out-degree band so 2/3-hop queries stay bounded and comparable on
tiny free tiers (documented in the README).
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Iterable


def node_ids(path: str | Path) -> list[int]:
    import csv

    with open(path, newline="") as fh:
        return [int(row["id"]) for row in csv.DictReader(fh)]


def out_degree(edges: Iterable[tuple[int, int]]) -> dict[int, int]:
    deg: dict[int, int] = {}
    for src, _dst in edges:
        deg[src] = deg.get(src, 0) + 1
    return deg


def pick_start_nodes(ids: list[int], n: int, seed: int) -> list[int]:
    """Uniform random sample (fixed seed) — used for point lookup and mixed workloads."""
    rng = random.Random(seed)
    return rng.sample(ids, min(n, len(ids)))


def pick_traversal_start_nodes(
    ids: list[int],
    edges: Iterable[tuple[int, int]],
    n: int,
    seed: int,
    min_deg: int = 5,
    max_deg: int = 30,
) -> list[int]:
    """Sample nodes whose out-degree is in [min_deg, max_deg] (fixed seed)."""
    deg = out_degree(edges)
    candidates = [u for u in ids if min_deg <= deg.get(u, 0) <= max_deg]
    rng = random.Random(seed)
    return rng.sample(candidates, min(n, len(candidates)))
