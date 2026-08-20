"""Command-line interface: prepare / load / verify / run / report / smoke."""
from __future__ import annotations

import argparse
import json
import runpy
import shutil
import sys
from pathlib import Path

from .adapters import build_adapter
from .adapters.base import iter_edges, iter_nodes
from .config import connection
from .environment import build_manifest
from .report import inject_readme, load_results, render_markdown, write_csvs
from .runner import benchmark, pick_probe_nodes, run_correctness_probes

REAL_DBS = ["cognodb", "neo4j", "memgraph", "falkordb", "arangodb"]
DATA_DIR = Path("data")
RESULTS_DIR = Path("results")


def _resolve_dbs(arg: str | None) -> list[str]:
    if arg == "all":
        return REAL_DBS
    return [arg]


def _expected_counts() -> tuple[int, int]:
    meta = json.loads((DATA_DIR / "dataset.json").read_text())
    return meta["sampled_nodes"], meta["sampled_edges"]


def _read_dataset() -> tuple[list[dict], list[tuple[int, int]]]:
    nodes = list(iter_nodes(DATA_DIR / "nodes.csv"))
    edges = list(iter_edges(DATA_DIR / "edges.csv"))
    return nodes, edges


def cmd_load(args: argparse.Namespace) -> int:
    nodes, edges = _read_dataset()
    exp_nodes, exp_edges = _expected_counts()
    failures: dict[str, str] = {}
    for db in _resolve_dbs(args.db):
        adapter = build_adapter(db, connection(db))
        print(f"== {adapter.label} ({db}): loading ...", file=sys.stderr)
        try:
            adapter.connect()
            ingest = adapter.load(DATA_DIR / "nodes.csv", DATA_DIR / "edges.csv")
            adapter.verify_indexes()
            got = adapter.counts()
        except Exception as exc:
            failures[db] = str(exc)
            print(f"FAILED {db}: {exc}", file=sys.stderr)
            continue
        finally:
            adapter.close()

        ok = got[0] == exp_nodes and got[1] == exp_edges
        print(json.dumps(ingest.summary(), indent=2))
        if not ok:
            failures[db] = f"count mismatch: expected ({exp_nodes}, {exp_edges}), got {got}"
            print(f"WARNING: {failures[db]}", file=sys.stderr)
        else:
            print(f"validated: {db} has {got[0]} nodes, {got[1]} relationships ✓", file=sys.stderr)

        RESULTS_DIR.mkdir(exist_ok=True)
        (RESULTS_DIR / f"{db}.ingest.json").write_text(json.dumps(ingest.summary(), indent=2) + "\n")

    if failures:
        print("\nLoad failures:", file=sys.stderr)
        for db, reason in failures.items():
            print(f"  {db}: {reason}", file=sys.stderr)
        return 1
    return 0


def _run_one(db: str, conn: dict | None, args: argparse.Namespace) -> dict:
    """Run the workload suite for one database; raises on failure."""
    nodes, edges = _read_dataset()
    adapter = build_adapter(db, conn or {})
    print(f"== {adapter.label} ({db})", file=sys.stderr)
    try:
        adapter.connect()
        if args.load or db == "mock":
            ingest = adapter.load(DATA_DIR / "nodes.csv", DATA_DIR / "edges.csv")
            (RESULTS_DIR / f"{db}.ingest.json").write_text(json.dumps(ingest.summary(), indent=2) + "\n")
        else:
            adapter.create_schema()
        adapter.verify_indexes()  # never time a full-scan as "indexed"
        result = benchmark(
            adapter,
            nodes=nodes,
            edges=edges,
            warmup=args.warmup,
            iterations=args.iterations,
            mixed_clients=args.mixed_clients,
            mixed_duration_s=args.mixed_duration,
            read_ratio=args.read_ratio,
        )
        fp = adapter.footprint()
        result["footprint"] = fp.summary()
    finally:
        adapter.close()

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / f"{db}.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def _next_run_dir(results_dir: Path) -> Path:
    nums = []
    for d in results_dir.iterdir() if results_dir.exists() else []:
        if d.is_dir() and d.name.startswith("run-"):
            try:
                nums.append(int(d.name.split("-")[1]))
            except (IndexError, ValueError):
                pass
    return results_dir / f"run-{max(nums, default=0) + 1:03d}"


def _snapshot(results_dir: Path, results: dict[str, dict], manifest: dict) -> Path:
    run_dir = _next_run_dir(results_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for db, result in results.items():
        (run_dir / f"{db}.json").write_text(json.dumps(result, indent=2) + "\n")
        ingest = results_dir / f"{db}.ingest.json"
        if ingest.exists():
            shutil.copy(ingest, run_dir / f"{db}.ingest.json")
    return run_dir


def cmd_run(args: argparse.Namespace) -> int:
    if args.dry_run:
        result = _run_one("mock", None, args)
        print(json.dumps(result, indent=2))
        return 0

    exp_nodes, exp_edges = _expected_counts()
    results: dict[str, dict] = {}
    failures: dict[str, str] = {}
    for db in _resolve_dbs(args.db):
        try:
            results[db] = _run_one(db, connection(db), args)
            print(f"PASS {db}", file=sys.stderr)
        except Exception as exc:
            failures[db] = str(exc)
            print(f"FAIL {db}: {exc}", file=sys.stderr)

    manifest = build_manifest(
        {
            "nodes": exp_nodes,
            "relationships": exp_edges,
            "warmup": args.warmup,
            "iterations": args.iterations,
            "mixed_clients": args.mixed_clients,
            "mixed_duration_s": args.mixed_duration,
            "read_ratio": args.read_ratio,
            "write_ratio": 1.0 - args.read_ratio,
        },
        results,
    )
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    run_dir = _snapshot(RESULTS_DIR, results, manifest)

    print("\n== Run summary", file=sys.stderr)
    for db in results:
        print(f"  PASS {db}", file=sys.stderr)
    for db, reason in failures.items():
        print(f"  FAIL {db}: {reason}", file=sys.stderr)
    print(f"  snapshot: {run_dir}", file=sys.stderr)

    return 1 if failures else 0


def _flatten(obj: object, prefix: str = "") -> list[tuple[str, object]]:
    items: list[tuple[str, object]] = []
    if isinstance(obj, dict):
        for k in sorted(obj, key=str):
            v = obj[k]
            key = f"{prefix}.{k}" if prefix else str(k)
            items.extend(_flatten(v, key))
    else:
        items.append((prefix, obj))
    return items


def cmd_verify(args: argparse.Namespace) -> int:
    """Cross-database correctness: run deterministic probes and compare."""
    nodes, edges = _read_dataset()
    exp_nodes, exp_edges = _expected_counts()
    probe_ids = pick_probe_nodes([n["id"] for n in nodes], edges)

    probes: dict[str, dict] = {}
    failures: dict[str, str] = {}
    for db in _resolve_dbs(args.db):
        adapter = build_adapter(db, connection(db))
        print(f"== {adapter.label} ({db}): verifying", file=sys.stderr)
        try:
            adapter.connect()
            got = adapter.counts()
            if got != (exp_nodes, exp_edges):
                raise RuntimeError(f"count mismatch: expected ({exp_nodes}, {exp_edges}), got {got}")
            adapter.verify_indexes()
            probes[db] = run_correctness_probes(adapter, probe_ids)
            print(f"  counts + indexes OK", file=sys.stderr)
        except Exception as exc:
            failures[db] = str(exc)
            print(f"  FAIL: {exc}", file=sys.stderr)
        finally:
            adapter.close()

    if failures:
        print("\nCorrectness verification FAILED (could not probe):", file=sys.stderr)
        for db, reason in failures.items():
            print(f"  {db}: {reason}", file=sys.stderr)
        return 1

    # Flatten each platform's probe results and compare value-by-value.
    flat = {db: dict(_flatten(p)) for db, p in probes.items()}
    all_paths = {path for vals in flat.values() for path in vals}
    mismatches = 0
    print("\n== Correctness cross-check", file=sys.stderr)
    for path in sorted(all_paths):
        vals = {db: flat[db].get(path) for db in flat if path in flat[db]}
        ok = len(set(vals.values())) == 1 and len(vals) == len(flat)
        if not ok:
            mismatches += 1
            print(f"  MISMATCH {path}: {vals}", file=sys.stderr)

    RESULTS_DIR.mkdir(exist_ok=True)
    payload = {"probes": probes, "failures": failures, "mismatches": mismatches}
    (RESULTS_DIR / "correctness.json").write_text(json.dumps(payload, indent=2) + "\n")

    if mismatches:
        print(f"\n{len(flat)} platforms probed, {mismatches} mismatching values", file=sys.stderr)
        return 1
    print(f"\nAll {len(flat)} platforms agree on every probe ✓", file=sys.stderr)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    results = load_results(RESULTS_DIR)
    if not results:
        print("No results found. Run `python -m bench run --all` first.", file=sys.stderr)
        return 1
    md = render_markdown(results)
    write_csvs(results, RESULTS_DIR)
    (RESULTS_DIR / "matrix.md").write_text(md)
    inject_readme(results, "README.md")
    print(md)
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    db = args.db
    adapter = build_adapter(db, connection(db))
    print(f"== {adapter.label} ({db}): smoke test", file=sys.stderr)
    try:
        adapter.connect()
        print("  connected OK", file=sys.stderr)
        adapter.create_schema()
        adapter.verify_indexes()
        print("  schema (indexes) OK", file=sys.stderr)
        adapter.q_aggregate()
        print("  trivial query OK", file=sys.stderr)
        print("  counts:", adapter.counts(), file=sys.stderr)
        print(json.dumps(adapter.footprint().summary(), indent=2))
    finally:
        adapter.close()
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    old_argv = sys.argv
    sys.argv = ["prepare.py", "--edges", str(args.edges)]
    try:
        runpy.run_path("data/prepare.py", run_name="__main__")
    finally:
        sys.argv = old_argv
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bench", description="Graph database cloud benchmarking harness")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("prepare", help="download + sample the soc-Pokec dataset")
    sp.add_argument("--edges", type=int, default=100_000)

    sl = sub.add_parser("load", help="load data into one or all databases")
    sl.add_argument("--db", default="all", help="database name or 'all'")

    sv = sub.add_parser("verify", help="cross-database correctness probes")
    sv.add_argument("--db", default="all", help="database name or 'all'")

    sr = sub.add_parser("run", help="run workloads and emit results")
    sr.add_argument("--db", default="all")
    sr.add_argument("--load", action="store_true", help="also ingest before benchmarking")
    sr.add_argument("--dry-run", action="store_true", help="use the mock adapter (no cloud)")
    sr.add_argument("--warmup", type=int, default=20)
    sr.add_argument("--iterations", type=int, default=100)
    sr.add_argument("--mixed-clients", type=int, default=10)
    sr.add_argument("--mixed-duration", type=float, default=30.0)
    sr.add_argument("--read-ratio", type=float, default=0.9)

    ss = sub.add_parser("smoke", help="test connection + schema + a trivial query")
    ss.add_argument("--db", required=True)

    srep = sub.add_parser("report", help="aggregate results into CSV + Markdown")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "prepare": cmd_prepare,
        "smoke": cmd_smoke,
        "load": cmd_load,
        "verify": cmd_verify,
        "run": cmd_run,
        "report": cmd_report,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
