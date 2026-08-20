"""Aggregate per-platform result JSON into a results matrix.

Produces Markdown tables (for the README) and flat CSVs for every metric.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

LATENCY_COLS = ["platform", "workload", "p50_ms", "p95_ms", "mean_ms", "min_ms", "max_ms", "iterations", "failures"]
INGEST_COLS = ["platform", "nodes", "relationships", "wall_s", "nodes_per_s", "rels_per_s", "notes"]
MIXED_COLS = ["platform", "clients", "read_ratio", "write_ratio", "duration_s", "ops_per_s", "total_ops", "failures"]


def load_results(results_dir: str | Path) -> dict[str, dict]:
    results: dict[str, dict] = {}
    d = Path(results_dir)
    if not d.exists():
        return results
    for p in sorted(d.glob("*.json")):
        if p.name.endswith(".ingest.json"):
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
    for depth in ("1", "2", "3"):
        metrics.append((f"traversal_{depth}_hop", result["traversals"][depth]))
    metrics.append(("aggregation_gender", result["aggregation"]))
    return metrics


def render_markdown(results: dict[str, dict]) -> str:
    out: list[str] = []

    out.append("## Latency (milliseconds)\n")
    out.append("| Platform | Workload | p50 | p95 | mean | min | max | iters | failures |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for name, r in results.items():
        for workload, m in _latency_metrics(r):
            out.append(
                f"| {name} | {workload} | {m['p50']} | {m['p95']} | {m['mean']} | "
                f"{m['min']} | {m['max']} | {m['iterations']} | {m['failures']} |"
            )

    out.append("\n## Data loading\n")
    out.append("| Platform | nodes | relationships | wall (s) | nodes/s | rels/s | notes |")
    out.append("|---|---|---|---|---|---|---|")
    for name, r in results.items():
        if "ingest" not in r:
            continue
        m = r["ingest"]
        out.append(
            f"| {name} | {m['nodes']} | {m['relationships']} | {m['wall_seconds']} | "
            f"{m['nodes_per_second']} | {m['rels_per_second']} | {m['notes']} |"
        )

    out.append("\n## Mixed workload (concurrent read/write)\n")
    out.append("| Platform | clients | read:write | duration (s) | ops/s | total ops | failures |")
    out.append("|---|---|---|---|---|---|---|")
    for name, r in results.items():
        if "mixed" not in r:
            continue
        m = r["mixed"]
        out.append(
            f"| {name} | {m['clients']} | {m['read_ratio']}:{m['write_ratio']} | "
            f"{m['duration_seconds']} | {m['ops_per_second']} | {m['total_ops']} | {m['failures']} |"
        )

    out.append("\n## Footprint (where observable)\n")
    out.append("| Platform | observables | notes |")
    out.append("|---|---|---|")
    for name, r in results.items():
        if "footprint" not in r:
            continue
        f = r["footprint"]
        obs = "; ".join(f"{k}={v}" for k, v in f["observables"].items()) or "not observable"
        out.append(f"| {name} | {obs} | {f['notes']} |")

    return "\n".join(out) + "\n"


def write_csvs(results: dict[str, dict], out_dir: str | Path) -> None:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)

    with (d / "matrix.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(LATENCY_COLS)
        for name, r in results.items():
            for workload, m in _latency_metrics(r):
                w.writerow([name, workload, m["p50"], m["p95"], m["mean"], m["min"], m["max"], m["iterations"], m["failures"]])

    with (d / "ingest.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(INGEST_COLS)
        for name, r in results.items():
            if "ingest" in r:
                m = r["ingest"]
                w.writerow([name, m["nodes"], m["relationships"], m["wall_seconds"], m["nodes_per_second"], m["rels_per_second"], m["notes"]])

    with (d / "mixed.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(MIXED_COLS)
        for name, r in results.items():
            if "mixed" in r:
                m = r["mixed"]
                w.writerow([name, m["clients"], m["read_ratio"], m["write_ratio"], m["duration_seconds"], m["ops_per_second"], m["total_ops"], m["failures"]])
