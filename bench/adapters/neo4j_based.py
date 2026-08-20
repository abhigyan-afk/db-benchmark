"""Adapters for Bolt/Cypher databases (Neo4j official driver).

CognoDB Cloud, Neo4j AuraDB and Memgraph Cloud all speak Bolt + Cypher, so
they share one implementation. The only dialect difference is index DDL,
which each subclass supplies.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from neo4j import GraphDatabase

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


class Neo4jDriverAdapter(DatabaseAdapter):
    """Shared Bolt+Cypher implementation; subclasses set credentials + index DDL."""

    uri_key: str = ""
    user_key: str = ""
    password_key: str = ""
    database_key: str = ""

    def __init__(self, connection: dict[str, str]):
        super().__init__(connection)
        self._driver = None
        self._local = threading.local()

    # -- connection --------------------------------------------------------
    def _uri(self) -> str:
        return self.connection[self.uri_key]

    def _user(self) -> str:
        return self.connection[self.user_key]

    def _password(self) -> str:
        return self.connection[self.password_key]

    def _database(self) -> str:
        return self.connection.get(self.database_key, "neo4j")

    def connect(self) -> None:
        self._driver = GraphDatabase.driver(self._uri(), auth=(self._user(), self._password()))
        self._driver.verify_connectivity()

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def _session(self):
        # thread-local session (the mixed workload uses one thread per client)
        s = getattr(self._local, "session", None)
        if s is None or s.closed():
            s = self._driver.session(database=self._database())
            self._local.session = s
        return s

    # -- schema ------------------------------------------------------------
    def _index_statements(self) -> list[str]:
        return [
            "CREATE INDEX user_id IF NOT EXISTS FOR (n:User) ON (n.id)",
            "CREATE INDEX user_age IF NOT EXISTS FOR (n:User) ON (n.age)",
            "CREATE INDEX user_gender IF NOT EXISTS FOR (n:User) ON (n.gender)",
        ]

    def reset(self) -> None:
        self._session().run("MATCH (n) DETACH DELETE n").consume()

    def create_schema(self) -> None:
        s = self._session()
        for stmt in self._index_statements():
            try:
                s.run(stmt).consume()
            except Exception as exc:
                print(f"  note: index statement skipped ({exc}): {stmt}", file=sys.stderr)

    # -- ingest ------------------------------------------------------------
    def load(self, nodes_path: str | Path, edges_path: str | Path) -> IngestResult:
        self.reset()
        nodes = list(iter_nodes(nodes_path))
        edges = list(iter_edges(edges_path))

        t0 = time.perf_counter()
        self._load_nodes(nodes)
        node_wall = time.perf_counter() - t0

        self.create_schema()  # indexes after nodes, so edge MATCHes use them

        t0 = time.perf_counter()
        self._load_edges(edges)
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

    def _load_nodes(self, nodes: list[dict]) -> None:
        s = self._session()
        for i in range(0, len(nodes), BATCH):
            rows = [_node_row(n) for n in nodes[i : i + BATCH]]
            s.run(
                "UNWIND $rows AS r "
                "CREATE (n:User {id: r.id, gender: r.gender, region: r.region, age: r.age})",
                rows=rows,
            ).consume()

    def _load_edges(self, edges: list[tuple[int, int]]) -> None:
        s = self._session()
        for i in range(0, len(edges), BATCH):
            rows = [{"src": a, "dst": b} for a, b in edges[i : i + BATCH]]
            s.run(
                "UNWIND $rows AS r "
                "MATCH (a:User {id: r.src}), (b:User {id: r.dst}) "
                "CREATE (a)-[:KNOWS]->(b)",
                rows=rows,
            ).consume()

    # -- queries -----------------------------------------------------------
    def q_point(self, node_id: int) -> object:
        return self._session().run("MATCH (n:User {id: $id}) RETURN n.id AS id", id=node_id).data()

    def q_filter(self, age: int) -> object:
        return self._session().run(
            "MATCH (n:User) WHERE n.age > $age RETURN n.id AS id LIMIT 50", age=age
        ).data()

    def q_traversal(self, depth: int, node_id: int) -> object:
        return self._session().run(
            f"MATCH (a:User {{id: $id}})-[:KNOWS*{depth}..{depth}]->(b) RETURN count(DISTINCT b) AS c",
            id=node_id,
        ).data()

    def q_aggregate(self) -> object:
        return self._session().run("MATCH (n:User) RETURN n.gender AS g, count(*) AS c ORDER BY g").data()

    def q_read(self, node_id: int) -> object:
        return self.q_point(node_id)

    def q_write(self, node_id: int) -> object:
        ts = int(time.time() * 1000)
        return self._session().run(
            "MATCH (n:User {id: $id}) SET n.bench_ts = $ts RETURN n.id AS id", id=node_id, ts=ts
        ).data()

    # -- validation / footprint -------------------------------------------
    def counts(self) -> tuple[int, int]:
        s = self._session()
        n = s.run("MATCH (n:User) RETURN count(n) AS c").single()["c"]
        e = s.run("MATCH ()-[r:KNOWS]->() RETURN count(r) AS c").single()["c"]
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


class CognoDBAdapter(Neo4jDriverAdapter):
    name = "cognodb"
    label = "CognoDB Cloud"
    uri_key = "COGNODB_URI"
    user_key = "COGNODB_USERNAME"
    password_key = "COGNODB_PASSWORD"
    database_key = "COGNODB_DATABASE"


class Neo4jAuraAdapter(Neo4jDriverAdapter):
    name = "neo4j"
    label = "Neo4j AuraDB"
    uri_key = "NEO4J_URI"
    user_key = "NEO4J_USERNAME"
    password_key = "NEO4J_PASSWORD"
    database_key = "NEO4J_DATABASE"


class MemgraphAdapter(Neo4jDriverAdapter):
    name = "memgraph"
    label = "Memgraph Cloud"

    def _uri(self) -> str:
        tls = self.connection.get("MEMGRAPH_TLS", "true").lower() == "true"
        scheme = "bolt+s" if tls else "bolt"
        return f"{scheme}://{self.connection['MEMGRAPH_HOST']}:{self.connection['MEMGRAPH_PORT']}"

    def _user(self) -> str:
        return self.connection["MEMGRAPH_USERNAME"]

    def _password(self) -> str:
        return self.connection["MEMGRAPH_PASSWORD"]

    def _database(self) -> str:
        return self.connection.get("MEMGRAPH_DATABASE", "memgraph")

    def _index_statements(self) -> list[str]:
        # Memgraph uses the classic index syntax.
        return [
            "CREATE INDEX ON :User(id)",
            "CREATE INDEX ON :User(age)",
            "CREATE INDEX ON :User(gender)",
        ]
