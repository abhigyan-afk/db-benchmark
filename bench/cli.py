"""Command-line interface: prepare / load / run / report."""
from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path

from .adapters import build_adapter
from .adapters.base import iter_edges, iter_nodes
from .config import connection
from .report import load_results, render_markdown, write_csvs
from .runner import benchmark

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
    for db in _resolve_dbs(args.db):
        adapter = build_adapter(db, connection(db))
        print(f"== {adapter.label} ({db}): loading ...", file=sys.stderr)
        try:
            adapter.connect()
            ingest = adapter.load(DATA_DIR / "nodes.csv", DATA_DIR / "edges.csv")
            got = adapter.counts()
        finally:
            adapter.close()

        ok = got[0] == exp_nodes and got[1] == exp_edges
        print(json.dumps(ingest.summary(), indent=2))
        if not ok:
            print(f"WARNING: count mismatch for {db}: expected ({exp_nodes}, {exp_edges}), got {got}", file=sys.stderr)
        else:
            print(f"validated: {db} has {got[0]} nodes, {got[1]} relationships ✓", file=sys.stderr)

        RESULTS_DIR.mkdir(exist_ok=True)
        (RESULTS_DIR / f"{db}.ingest.json").write_text(json.dumps(ingest.summary(), indent=2) + "\n")
    return 0


def _run_one(db: str, conn: dict | None, args: argparse.Namespace) -> int:
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
    print(json.dumps(result, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if args.dry_run:
        return _run_one("mock", None, args)
    for db in _resolve_dbs(args.db):
        rc = _run_one(db, connection(db), args)
        if rc != 0:
            return rc
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    results = load_results(RESULTS_DIR)
    if not results:
        print("No results found. Run `python -m bench run --all` first.", file=sys.stderr)
        return 1
    md = render_markdown(results)
    write_csvs(results, RESULTS_DIR)
    (RESULTS_DIR / "matrix.md").write_text(md)
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

    sr = sub.add_parser("run", help="run workloads and emit results")
    sr.add_argument("--db", default="all")
    sr.add_argument("--load", action="store_true", help="also ingest before benchmarking")
    sr.add_argument("--dry-run", action="store_true", help="use the mock adapter (no cloud)")
    sr.add_argument("--warmup", type=int, default=5)
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
    handlers = {"prepare": cmd_prepare, "smoke": cmd_smoke, "load": cmd_load, "run": cmd_run, "report": cmd_report}
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
