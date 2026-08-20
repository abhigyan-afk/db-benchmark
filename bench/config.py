"""Environment / secret handling.

Credentials are read from a gitignored ``.env`` file (see ``.env.example``)
so that no connection URI or password ever lands in the repository.
"""
from __future__ import annotations

import os
from pathlib import Path

# Environment variables that must be present (and non-empty) to connect.
REQUIRED_KEYS: dict[str, list[str]] = {
    "cognodb": ["COGNODB_URI", "COGNODB_USERNAME", "COGNODB_PASSWORD", "COGNODB_DATABASE"],
    "neo4j": ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE"],
    "memgraph": ["MEMGRAPH_HOST", "MEMGRAPH_PORT", "MEMGRAPH_USERNAME", "MEMGRAPH_PASSWORD", "MEMGRAPH_DATABASE"],
    "falkordb": ["FALKORDB_HOST", "FALKORDB_PORT", "FALKORDB_USERNAME", "FALKORDB_PASSWORD", "FALKORDB_GRAPH"],
    "arangodb": ["ARANGO_URL", "ARANGO_USERNAME", "ARANGO_PASSWORD", "ARANGO_DATABASE"],
}

# Optional settings with sensible defaults applied by the adapters.
OPTIONAL_KEYS: dict[str, list[str]] = {
    "memgraph": ["MEMGRAPH_TLS"],
    "falkordb": ["FALKORDB_TLS"],
}


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader (avoids a python-dotenv dependency)."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def connection(name: str) -> dict[str, str]:
    """Return the connection settings for a database, or raise with a clear
    message listing any missing required secret."""
    if name not in REQUIRED_KEYS:
        raise KeyError(f"Unknown database: {name!r}. Known: {sorted(REQUIRED_KEYS)}")
    load_dotenv()
    required = REQUIRED_KEYS[name]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing required env var(s) for '{name}': {', '.join(missing)}. "
            "Copy .env.example to .env and fill them in."
        )
    keys = required + OPTIONAL_KEYS.get(name, [])
    return {k: os.environ.get(k, "") for k in keys}
