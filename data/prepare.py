#!/usr/bin/env python3
"""Prepare the benchmark dataset.

Downloads the SNAP soc-Pokec network, samples the first ``N`` directed edges
(in file order), collects every incident node, and joins their profile
properties. Emits:

- ``data/nodes.csv``   columns: id,gender,region,age
- ``data/edges.csv``   columns: src,dst
- ``data/dataset.json``  recorded counts + provenance

The full network is 1,632,803 nodes / 30,622,564 edges; this samples a
small, reproducible slice that fits the free tier of every platform.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

REL_URL = "https://snap.stanford.edu/data/soc-pokec-relationships.txt.gz"
PROF_URL = "https://snap.stanford.edu/data/soc-pokec-profiles.txt.gz"

# 0-indexed column positions in soc-pokec-profiles.txt (tab-separated).
# user_id=0, public=1, completion_percentage=2, gender=3, region=4,
# last_login=5, registration=6, AGE=7 (per the official soc-pokec-readme.txt).
COL_GENDER = 3
COL_REGION = 4
COL_AGE = 7


def _open_gz_stream(url: str) -> gzip.GzipFile:
    resp = urllib.request.urlopen(url, timeout=120)
    return gzip.GzipFile(fileobj=resp)


def _field(cols: list[str], i: int) -> str | None:
    if i >= len(cols):
        return None
    v = cols[i].strip()
    return None if v in ("", "null") else v


def _int_field(cols: list[str], i: int) -> int | None:
    v = _field(cols, i)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def load_profiles() -> dict[int, tuple[int | None, str | None, int | None]]:
    """Return {user_id: (gender, region, age)} for every profile."""
    print(f"Downloading profiles: {PROF_URL}", file=sys.stderr)
    profiles: dict[int, tuple[int | None, str | None, int | None]] = {}
    with _open_gz_stream(PROF_URL) as fh:
        for raw in fh:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            cols = line.split("\t")
            if not cols or cols[0] == "":
                continue
            try:
                uid = int(cols[0])
            except ValueError:
                continue
            profiles[uid] = (
                _int_field(cols, COL_GENDER),
                _field(cols, COL_REGION),
                _int_field(cols, COL_AGE),
            )
    return profiles


def sample_edges(n: int) -> list[tuple[int, int]]:
    """Read the first ``n`` directed edges from the (streamed) relationships file."""
    print(f"Streaming relationships (first {n} edges): {REL_URL}", file=sys.stderr)
    edges: list[tuple[int, int]] = []
    with _open_gz_stream(REL_URL) as fh:
        for raw in fh:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            try:
                src, dst = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            edges.append((src, dst))
            if len(edges) >= n:
                break
    return edges


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edges", type=int, default=100_000, help="number of relationships to sample")
    parser.add_argument("--out-dir", type=Path, default=Path("data"))
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    edges = sample_edges(args.edges)
    if len(edges) < args.edges:
        print(f"WARNING: only {len(edges)} edges available", file=sys.stderr)

    node_ids = set()
    for src, dst in edges:
        node_ids.add(src)
        node_ids.add(dst)

    profiles = load_profiles()

    nodes_path = args.out_dir / "nodes.csv"
    edges_path = args.out_dir / "edges.csv"
    meta_path = args.out_dir / "dataset.json"

    missing_profiles = 0
    with nodes_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "gender", "region", "age"])
        for uid in sorted(node_ids):
            gender, region, age = profiles.get(uid, (None, None, None))
            if uid not in profiles:
                missing_profiles += 1
            writer.writerow([uid, "" if gender is None else gender,
                             "" if region is None else region,
                             "" if age is None else age])

    with edges_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["src", "dst"])
        writer.writerows(edges)

    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    meta = {
        "source": "SNAP soc-Pokec (https://snap.stanford.edu/data/soc-Pokec.html)",
        "full_nodes": 1_632_803,
        "full_edges": 30_622_564,
        "selection_method": "first N directed edges in file order, all incident nodes, profile properties joined",
        "seed": None,
        "sampled_edges": len(edges),
        "sampled_nodes": len(node_ids),
        "nodes_missing_profiles": missing_profiles,
        "relationships_file": REL_URL,
        "profiles_file": PROF_URL,
        "nodes_csv_sha256": _sha256(nodes_path),
        "edges_csv_sha256": _sha256(edges_path),
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")

    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
