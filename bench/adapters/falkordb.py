"""FalkorDB Cloud adapter (official falkordb-py client, RESP protocol)."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from falkordb import FalkorDB

from .base import (
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
                ssl=(c.get("FALKORDB_TLS", "true").lower() == "true"),
            )
            self._local.client = client
            g = client.select_graph(c["FALKORDB_GRAPH"])
            self._local.graph = g
        return g

    def connect(self) -> None:
        # forces connection + graph selection eagerly
        self._graph().ro_query("RETURN 1")

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
        for prop in ("id", "age", "gender"):
            try:
                g.create_node_range_index("User", prop)
            except Exception as exc:
                print(f"  note: index skipped ({exc}): User({prop})", file=sys.stderr)

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

        self.create_schema()

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
            wall_seconds=node_wall + edge_wall,
            nodes_per_second=len(nodes) / node_wall if node_wall else 0.0,
            rels_per_second=len(edges) / edge_wall if edge_wall else 0.0,
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
        return self._graph().ro_query(
            f"MATCH (a:User {{id: $id}})-[:KNOWS*{depth}..{depth}]->(b) RETURN count(DISTINCT b) AS c",
            params={"id": node_id},
        ).result_set

    def q_aggregate(self) -> object:
        return self._graph().ro_query(
            "MATCH (n:User) RETURN n.gender AS g, count(*) AS c ORDER BY g"
        ).result_set

    def q_read(self, node_id: int) -> object:
        return self.q_point(node_id)

    def q_write(self, node_id: int) -> object:
        ts = int(time.time() * 1000)
        return self._graph().query(
            "MATCH (n:User {id: $id}) SET n.bench_ts = $ts RETURN n.id AS id",
            params={"id": node_id, "ts": ts},
        ).result_set

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
