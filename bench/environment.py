"""Benchmark environment + reproducibility helpers.

Collects everything needed to reproduce a run: the git commit, the dataset
checksums, the client machine specs, and the installed driver versions. None
of this touches credentials.
"""
from __future__ import annotations

import hashlib
import os
import platform
import subprocess
from pathlib import Path

DATA_DIR = Path("data")


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except Exception:
        pass
    return None


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dataset_checksums() -> dict[str, str]:
    return {
        "nodes_csv_sha256": sha256(DATA_DIR / "nodes.csv"),
        "edges_csv_sha256": sha256(DATA_DIR / "edges.csv"),
    }


def _linux_ram_gb() -> str | None:
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return f"{kb / 1024 / 1024:.1f} GB"
    except Exception:
        pass
    return None


def machine_info() -> dict[str, str]:
    info = {
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": str(os.cpu_count() or "unknown"),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
    }
    ram = _linux_ram_gb()
    if ram:
        info["ram"] = ram
    return info


def driver_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name, attr in (
        ("neo4j", "neo4j"),
        ("falkordb", "falkordb"),
        ("python-arango", "arango"),
    ):
        try:
            mod = __import__(attr)
            versions[name] = getattr(mod, "__version__", "unknown")
        except Exception:
            versions[name] = "not installed"
    return versions


def build_manifest(params: dict, results: dict[str, dict]) -> dict:
    """Assemble a reproducibility manifest for the current run."""
    return {
        "git_commit": git_commit(),
        "dataset": {
            **dataset_checksums(),
            "nodes": params.get("nodes"),
            "relationships": params.get("relationships"),
        },
        "methodology": {
            "warmup_iterations": params.get("warmup"),
            "measurement_iterations": params.get("iterations"),
            "mixed_clients": params.get("mixed_clients"),
            "mixed_duration_seconds": params.get("mixed_duration_s"),
            "read_ratio": params.get("read_ratio"),
            "write_ratio": params.get("write_ratio"),
        },
        "environment": machine_info(),
        "drivers": driver_versions(),
        "databases": {
            name: r.get("label", name) for name, r in sorted(results.items())
        },
    }
