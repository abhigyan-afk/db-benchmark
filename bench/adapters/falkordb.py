"""FalkorDB Cloud adapter (official falkordb-py client, RESP protocol)."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from falkordb import FalkorDB

from .base import (
    REQUIRED_INDEXES,
    DatabaseAdapter,
    FootprintResult,
    IngestResult,
    iter_edges,
    iter_nodes,
)

BATCH = 1000


def _node_row(n: dict) -> dict:
    return {
        "id": n["id"],
        "gender": 0 if n["gender"] is None else n["gender"],
        "region": n["region"] or "",
        "age": 0 if n["age"] is None else n["age"],
    }


class FalkorDBAdapter(DatabaseAdapter):
    name = "falkordb"
    label = "FalkorDB Cloud"

    def __init__(self, connection: dict[str, str]):
        super().__init__(connection)
        self._local = threading.local()

    def _graph(self):
        """Thread-local graph handle (FalkorDB client is not thread-safe)."""
        g = getattr(self._local, "graph", None)
        if g is None:
            c = self.connection
            client = FalkorDB(
                host=c["FALKORDB_HOST"],
                port=int(c["FALKORDB_PORT"]),
                username=c["FALKORDB_USERNAME"],
                password=c["FALKORDB_PASSWORD"],
                ssl=(c.get("FALKORDB_TLS", "false").lower() == "true"),
                socket_connect_timeout=15,
                socket_timeout=30,
            )
            self._local.client = client
            g = client.select_graph(c["FALKORDB_GRAPH"])
            self._local.graph = g
        return g

    def connect(self) -> None:
        # FalkorDB(...) performs an INFO round-trip on construction, which
        # verifies connectivity and authentication eagerly.
        self._graph()

    def close(self) -> None:
        client = getattr(self._local, "client", None)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    # -- schema ------------------------------------------------------------
    def reset(self) -> None:
        try:
            self._graph().delete()
        except Exception:
            pass
        # clear thread-local handle so the graph is re-selected on next use
        self._local.graph = None

    def create_schema(self) -> None:
        g = self._graph()
        for prop in REQUIRED_INDEXES:
            try:
                g.create_node_range_index("User", prop)
            except Exception as exc:
                print(f"  note: index statement skipped ({exc}): User({prop})", file=sys.stderr)

    def verify_indexes(self) -> None:
        g = self._graph()
        try:
            rows = g.query("CALL db.indexes()").result_set
        except Exception as exc:
            raise RuntimeError(f"{self.name}: could not list indexes ({exc})") from exc
        indexed: set[tuple[str, str]] = set()
        for row in rows:
            label = row[0] if len(row) > 0 else None
            props = row[1] if len(row) > 1 else []
            if isinstance(label, str) and isinstance(props, list):
                for prop in props:
                    indexed.add((label, prop))
        for prop in REQUIRED_INDEXES:
            if ("User", prop) not in indexed:
                raise RuntimeError(f"{self.name}: missing required index on User({prop})")

    # -- ingest ------------------------------------------------------------
    def load(self, nodes_path: str | Path, edges_path: str | Path) -> IngestResult:
        self.reset()
        nodes = list(iter_nodes(nodes_path))
        edges = list(iter_edges(edges_path))
        g = self._graph()

        t0 = time.perf_counter()
        for i in range(0, len(nodes), BATCH):
            rows = [_node_row(n) for n in nodes[i : i + BATCH]]
            g.query(
                "UNWIND $rows AS r "
                "CREATE (n:User {id: r.id, gender: r.gender, region: r.region, age: r.age})",
                params={"rows": rows},
            )
        node_wall = time.perf_counter() - t0

        t0 = time.perf_counter()
        self.create_schema()
        index_wall = time.perf_counter() - t0

        self.verify_indexes()  # fail rather than silently run a full scan

        t0 = time.perf_counter()
        for i in range(0, len(edges), BATCH):
            rows = [{"src": a, "dst": b} for a, b in edges[i : i + BATCH]]
            g.query(
                "UNWIND $rows AS r "
                "MATCH (a:User {id: r.src}), (b:User {id: r.dst}) "
                "CREATE (a)-[:KNOWS]->(b)",
                params={"rows": rows},
            )
        edge_wall = time.perf_counter() - t0

        return IngestResult(
            label="ingest",
            nodes=len(nodes),
            relationships=len(edges),
            node_load_seconds=node_wall,
            index_creation_seconds=index_wall,
            relationship_load_seconds=edge_wall,
            notes=f"batched UNWIND, batch={BATCH}",
        )

    # -- queries -----------------------------------------------------------
    def q_point(self, node_id: int) -> object:
        return self._graph().ro_query(
            "MATCH (n:User {id: $id}) RETURN n.id AS id", params={"id": node_id}
        ).result_set

    def q_filter(self, age: int) -> object:
        return self._graph().ro_query(
            "MATCH (n:User) WHERE n.age > $age RETURN n.id AS id LIMIT 50", params={"age": age}
        ).result_set

    def q_traversal(self, depth: int, node_id: int) -> object:
        # "N-hop traversal" = distinct nodes within N hops, start excluded.
        # FalkorDB cannot filter the end node `b` directly in WHERE, so we
        # `WITH DISTINCT b` first (matches the other engines' `count(DISTINCT b)`).
        return self._graph().ro_query(
            f"MATCH (a:User {{id: $id}})-[:KNOWS*1..{depth}]->(b) "
            "WITH DISTINCT b AS b WHERE b.id <> $id RETURN count(b) AS c",
            params={"id": node_id},
        ).result_set

    def q_aggregate(self) -> object:
        return self._graph().ro_query(
            "MATCH (n:User) RETURN n.gender AS g, count(*) AS c ORDER BY g"
        ).result_set

    def q_aggregate_rels(self) -> object:
        return self._graph().ro_query(
            "MATCH ()-[r:KNOWS]->() RETURN type(r) AS t, count(*) AS c ORDER BY t"
        ).result_set

    def q_read(self, node_id: int) -> object:
        return self.q_point(node_id)

    def q_write(self, node_id: int) -> object:
        ts = int(time.time() * 1000)
        return self._graph().query(
            "MATCH (n:User {id: $id}) SET n.bench_ts = $ts RETURN n.id AS id",
            params={"id": node_id, "ts": ts},
        ).result_set

    # -- correctness probes (deterministic counts) -------------------------
    def probe_point(self, node_id: int) -> int:
        rs = self._graph().ro_query(
            "MATCH (n:User {id: $id}) RETURN count(n) AS c", params={"id": node_id}
        ).result_set
        return int(rs[0][0])

    def probe_filter(self, age: int) -> int:
        rs = self._graph().ro_query(
            "MATCH (n:User) WHERE n.age > $age RETURN count(n) AS c", params={"age": age}
        ).result_set
        return int(rs[0][0])

    def probe_traversal(self, depth: int, node_id: int) -> int:
        rs = self._graph().ro_query(
            f"MATCH (a:User {{id: $id}})-[:KNOWS*1..{depth}]->(b) "
            "WITH DISTINCT b AS b WHERE b.id <> $id RETURN count(b) AS c",
            params={"id": node_id},
        ).result_set
        return int(rs[0][0])

    def probe_aggregate(self) -> dict:
        rows = self._graph().ro_query(
            "MATCH (n:User) RETURN n.gender AS g, count(*) AS c ORDER BY g"
        ).result_set
        return {str(r[0]): int(r[1]) for r in rows}

    # -- validation / footprint -------------------------------------------
    def counts(self) -> tuple[int, int]:
        g = self._graph()
        n = g.ro_query("MATCH (n:User) RETURN count(n) AS c").result_set[0][0]
        e = g.ro_query("MATCH ()-[r:KNOWS]->() RETURN count(r) AS c").result_set[0][0]
        return (int(n), int(e))

    def footprint(self) -> FootprintResult:
        obs: dict = {}
        try:
            n, e = self.counts()
            obs = {"nodes": n, "relationships": e}
        except Exception:
            pass
        return FootprintResult(
            label="footprint",
            observables=obs,
            notes="instance specs recorded from the console (see README); storage/memory not observable via driver on this tier",
        )
