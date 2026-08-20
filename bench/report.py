"""Aggregate per-platform result JSON into a results matrix.

Produces Markdown tables (for the README) and flat CSVs for every metric.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

LATENCY_COLS = ["platform", "workload", "p50_ms", "p95_ms", "p99_ms", "mean_ms", "min_ms", "max_ms", "iterations", "failures"]
INGEST_COLS = ["platform", "nodes", "relationships", "node_load_s", "index_s", "rel_load_s", "total_s", "nodes_per_s", "rels_per_s", "notes"]
MIXED_COLS = ["platform", "clients", "cfg_read_ratio", "cfg_write_ratio", "actual_read_ratio", "actual_write_ratio", "duration_s", "ops_per_s", "total_ops", "read_ops", "write_ops", "failures"]

# Preferred display order (matches the README TL;DR table).
PLATFORM_ORDER = ["cognodb", "neo4j", "memgraph", "falkordb", "arangodb"]


def _ordered(results: dict[str, dict]):
    for name in PLATFORM_ORDER:
        if name in results:
            yield name, results[name]
    for name, r in results.items():
        if name not in PLATFORM_ORDER:
            yield name, r


def load_results(results_dir: str | Path) -> dict[str, dict]:
    results: dict[str, dict] = {}
    d = Path(results_dir)
    if not d.exists():
        return results
    for p in sorted(d.glob("*.json")):
        if p.name.endswith(".ingest.json") or p.name in ("manifest.json", "correctness.json", "mock.json"):
            continue
        results[p.stem] = json.loads(p.read_text())
        ingest = d / f"{p.stem}.ingest.json"
        if ingest.exists():
            results[p.stem]["ingest"] = json.loads(ingest.read_text())
    return results


def _latency_metrics(result: dict) -> list[tuple[str, dict]]:
    metrics: list[tuple[str, dict]] = []
    metrics.append(("point_lookup", result["lookups"]["point"]))
    metrics.append(("filtered_lookup_age", result["lookups"]["filter"]))
    for depth in (1, 2, 3):
        metrics.append((f"traversal_{depth}_hop", result["traversals"][str(depth)]))
    metrics.append(("aggregation_gender", result["aggregations"]["gender"]))
    metrics.append(("aggregation_rel_type", result["aggregations"]["relationship_type"]))
    return metrics


def render_markdown(results: dict[str, dict]) -> str:
    out: list[str] = []

    out.append("## Latency (milliseconds)\n")
    out.append("| Platform | Workload | p50 | p95 | p99 | mean | min | max | iters | failures |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for name, r in _ordered(results):
        for workload, m in _latency_metrics(r):
            out.append(
                f"| {name} | {workload} | {m['p50']} | {m['p95']} | {m['p99']} | {m['mean']} | "
                f"{m['min']} | {m['max']} | {m['iterations']} | {m['failures']} |"
            )

    out.append("\n## Data loading\n")
    out.append("| Platform | nodes | relationships | node load (s) | index (s) | rel load (s) | total (s) | nodes/s | rels/s | notes |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for name, r in _ordered(results):
        if "ingest" not in r:
            continue
        m = r["ingest"]
        out.append(
            f"| {name} | {m['nodes']} | {m['relationships']} | {m['node_load_seconds']} | "
            f"{m['index_creation_seconds']} | {m['relationship_load_seconds']} | {m['total_load_seconds']} | "
            f"{m['nodes_per_second']} | {m['rels_per_second']} | {m['notes']} |"
        )

    out.append("\n## Mixed workload (concurrent read/write)\n")
    out.append("| Platform | clients | cfg read:write | actual read:write | duration (s) | ops/s | total ops | read ops | write ops | failures |")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for name, r in _ordered(results):
        if "mixed" not in r:
            continue
        m = r["mixed"]
        cfg = f"{m['configured_read_ratio']}:{m['configured_write_ratio']}"
        actual = f"{m['actual_read_ratio']}:{m['actual_write_ratio']}"
        out.append(
            f"| {name} | {m['clients']} | {cfg} | {actual} | {m['duration_seconds']} | "
            f"{m['ops_per_second']} | {m['total_ops']} | {m['actual_read_ops']} | {m['actual_write_ops']} | {m['failures']} |"
        )

    out.append("\n## Footprint (where observable)\n")
    out.append("| Platform | observables | notes |")
    out.append("|---|---|---|")
    for name, r in _ordered(results):
        if "footprint" not in r:
            continue
        f = r["footprint"]
        obs = "; ".join(f"{k}={v}" for k, v in f["observables"].items()) or "not observable"
        out.append(f"| {name} | {obs} | {f['notes']} |")

    return "\n".join(out) + "\n"


def inject_readme(results: dict[str, dict], readme_path: str | Path = "README.md") -> None:
    """Replace the README's `## Results` section with freshly rendered tables."""
    path = Path(readme_path)
    text = path.read_text()
    start = text.index("## Results")
    end = text.index("## Methodology")
    new_section = "## Results\n\n" + render_markdown(results) + "\n---\n\n"
    path.write_text(text[:start] + new_section + text[end:])


def write_csvs(results: dict[str, dict], out_dir: str | Path) -> None:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)

    with (d / "matrix.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(LATENCY_COLS)
        for name, r in _ordered(results):
            for workload, m in _latency_metrics(r):
                w.writerow([name, workload, m["p50"], m["p95"], m["p99"], m["mean"], m["min"], m["max"], m["iterations"], m["failures"]])

    with (d / "ingest.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(INGEST_COLS)
        for name, r in _ordered(results):
            if "ingest" in r:
                m = r["ingest"]
                w.writerow([name, m["nodes"], m["relationships"], m["node_load_seconds"], m["index_creation_seconds"], m["relationship_load_seconds"], m["total_load_seconds"], m["nodes_per_second"], m["rels_per_second"], m["notes"]])

    with (d / "mixed.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(MIXED_COLS)
        for name, r in _ordered(results):
            if "mixed" in r:
                m = r["mixed"]
                w.writerow([name, m["clients"], m["configured_read_ratio"], m["configured_write_ratio"], m["actual_read_ratio"], m["actual_write_ratio"], m["duration_seconds"], m["ops_per_second"], m["total_ops"], m["actual_read_ops"], m["actual_write_ops"], m["failures"]])
