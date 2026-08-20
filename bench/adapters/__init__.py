"""Adapter registry.

``build_adapter`` imports the relevant driver lazily so a dry-run against the
mock adapter works without any of the database drivers installed.
"""
from __future__ import annotations

from .base import DatabaseAdapter
from .mock import MockAdapter

# name -> (module, class) resolved lazily
_REGISTRY = {
    "mock": ("bench.adapters.mock", "MockAdapter"),
    "cognodb": ("bench.adapters.neo4j_based", "CognoDBAdapter"),
    "neo4j": ("bench.adapters.neo4j_based", "Neo4jAuraAdapter"),
    "memgraph": ("bench.adapters.neo4j_based", "MemgraphAdapter"),
    "falkordb": ("bench.adapters.falkordb", "FalkorDBAdapter"),
    "arangodb": ("bench.adapters.arangodb", "ArangoDBAdapter"),
}

AVAILABLE = sorted(_REGISTRY)


def build_adapter(name: str, connection: dict[str, str] | None = None) -> DatabaseAdapter:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown database: {name!r}. Available: {AVAILABLE}")
    module_name, class_name = _REGISTRY[name]
    import importlib

    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    return cls(connection or {})
