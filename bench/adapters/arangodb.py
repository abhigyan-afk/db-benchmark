"""ArangoDB Cloud adapter (python-arango, AQL).

Graph model: document collection ``users`` (node properties) + edge
collection ``knows`` (_from/_to). Traversal and lookup workloads are AQL
semantic translations of the Cypher workloads (noted in the README).
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from arango import ArangoClient

from .base import (
    REQUIRED_INDEXES,
    DatabaseAdapter,
    FootprintResult,
    IngestResult,
    iter_edges,
    iter_nodes,
)

NODES_COL = "users"
EDGES_COL = "knows"
BATCH = 1000


def _node_doc(n: dict) -> dict:
    return {
        "_key": str(n["id"]),
        "id": n["id"],
        "gender": 0 if n["gender"] is None else n["gender"],
        "region": n["region"] or "",
        "age": 0 if n["age"] is None else n["age"],
    }


class ArangoDBAdapter(DatabaseAdapter):
    name = "arangodb"
    label = "ArangoDB Cloud"

    def __init__(self, connection: dict[str, str]):
        super().__init__(connection)
        self._local = threading.local()

    def _db(self):
        """Thread-local database handle (python-arango's HTTP session is not thread-safe)."""
        d = getattr(self._local, "db", None)
        if d is None:
            c = self.connection
            client = ArangoClient(hosts=c["ARANGO_URL"])
            d = client.db(c["ARANGO_DATABASE"], c["ARANGO_USERNAME"], c["ARANGO_PASSWORD"], verify=True)
            self._local.client = client
            self._local.db = d
        return d

    def connect(self) -> None:
        self._db().aql.execute("RETURN 1")  # forces connection/auth

    def close(self) -> None:
        client = getattr(self._local, "client", None)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    # -- schema ------------------------------------------------------------
    def reset(self) -> None:
        db = self._db()
        for col in (NODES_COL, EDGES_COL):
            if db.has_collection(col):
                db.delete_collection(col)

    def _ensure_collections(self) -> None:
        db = self._db()
        if not db.has_collection(NODES_COL):
            db.create_collection(NODES_COL)
        if not db.has_collection(EDGES_COL):
            db.create_collection(EDGES_COL, edge=True)

    def _create_indexes(self) -> None:
        users = self._db().collection(NODES_COL)
        for fields, unique in ((["id"], True), (["age"], False), (["gender"], False)):
            try:
                users.add_persistent_index(fields=fields, unique=unique)
            except Exception as exc:
                print(f"  note: index statement skipped ({exc}): {fields}", file=sys.stderr)

    def create_schema(self) -> None:
        self._ensure_collections()
        self._create_indexes()

    def verify_indexes(self) -> None:
        db = self._db()
        if not db.has_collection(NODES_COL):
            raise RuntimeError(f"{self.name}: collection {NODES_COL} missing")
        users = db.collection(NODES_COL)
        indexed = {
            tuple(i.get("fields") or [])
            for i in users.indexes()
            if i.get("type") in ("persistent", "hash")
        }
        for prop in REQUIRED_INDEXES:
            if (prop,) not in indexed:
                raise RuntimeError(f"{self.name}: missing required index on users({prop})")

    # -- ingest ------------------------------------------------------------
    def load(self, nodes_path: str | Path, edges_path: str | Path) -> IngestResult:
        self.reset()
        self._ensure_collections()
        nodes = list(iter_nodes(nodes_path))
        edges = list(iter_edges(edges_path))
        users = self._db().collection(NODES_COL)
        knows = self._db().collection(EDGES_COL)

        t0 = time.perf_counter()
        for i in range(0, len(nodes), BATCH):
            users.insert_many([_node_doc(n) for n in nodes[i : i + BATCH]], overwrite_mode="ignore")
        node_wall = time.perf_counter() - t0

        t0 = time.perf_counter()
        self._create_indexes()
        index_wall = time.perf_counter() - t0

        self.verify_indexes()  # fail rather than silently run a full scan

        t0 = time.perf_counter()
        for i in range(0, len(edges), BATCH):
            knows.insert_many(
                [{"_from": f"{NODES_COL}/{s}", "_to": f"{NODES_COL}/{t}"} for s, t in edges[i : i + BATCH]],
                overwrite_mode="ignore",
            )
        edge_wall = time.perf_counter() - t0

        return IngestResult(
            label="ingest",
            nodes=len(nodes),
            relationships=len(edges),
            node_load_seconds=node_wall,
            index_creation_seconds=index_wall,
            relationship_load_seconds=edge_wall,
            notes=f"insert_many batches, batch={BATCH}",
        )

    # -- queries (AQL) -----------------------------------------------------
    def q_point(self, node_id: int) -> object:
        return list(self._db().aql.execute(
            f"FOR u IN {NODES_COL} FILTER u.id == @id RETURN u.id", bind_vars={"id": node_id}
        ))

    def q_filter(self, age: int) -> object:
        return list(self._db().aql.execute(
            f"FOR u IN {NODES_COL} FILTER u.age > @age LIMIT 50 RETURN u.id", bind_vars={"age": age}
        ))

    def q_traversal(self, depth: int, node_id: int) -> object:
        # "N-hop traversal" = distinct vertices within N hops (start excluded),
        # the AQL equivalent of Cypher `[:KNOWS*1..N]` + `WHERE b.id <> $id`.
        # `WITH users` is required when the start vertex is a bind variable.
        return list(self._db().aql.execute(
            f"WITH {NODES_COL} FOR v IN 1..{depth} OUTBOUND @start {EDGES_COL} "
            "FILTER v._key != @start_key "
            "COLLECT k = v._key COLLECT WITH COUNT INTO c RETURN c",
            bind_vars={"start": f"{NODES_COL}/{node_id}", "start_key": str(node_id)},
        ))

    def q_aggregate(self) -> object:
        return list(self._db().aql.execute(
            f"FOR u IN {NODES_COL} COLLECT g = u.gender WITH COUNT INTO c RETURN {{gender: g, count: c}}"
        ))

    def q_aggregate_rels(self) -> object:
        # A single edge collection means a single relationship type; the
        # group-by still yields the relationship count for the "knows" type
        # (semantic equivalent of Cypher type(r) with one type in the dataset).
        return list(self._db().aql.execute(
            f"FOR e IN {EDGES_COL} COLLECT WITH COUNT INTO c RETURN {{type: 'knows', count: c}}"
        ))

    def q_read(self, node_id: int) -> object:
        return self.q_point(node_id)

    def q_write(self, node_id: int) -> object:
        return list(self._db().aql.execute(
            f"UPDATE @key WITH {{bench_ts: @ts}} IN {NODES_COL}",
            bind_vars={"key": str(node_id), "ts": int(time.time() * 1000)},
        ))

    # -- correctness probes (deterministic counts) -------------------------
    def probe_point(self, node_id: int) -> int:
        r = list(self._db().aql.execute(
            f"FOR u IN {NODES_COL} FILTER u.id == @id COLLECT WITH COUNT INTO c RETURN c",
            bind_vars={"id": node_id},
        ))
        return int(r[0])

    def probe_filter(self, age: int) -> int:
        r = list(self._db().aql.execute(
            f"FOR u IN {NODES_COL} FILTER u.age > @age COLLECT WITH COUNT INTO c RETURN c",
            bind_vars={"age": age},
        ))
        return int(r[0])

    def probe_traversal(self, depth: int, node_id: int) -> int:
        r = list(self._db().aql.execute(
            f"WITH {NODES_COL} FOR v IN 1..{depth} OUTBOUND @start {EDGES_COL} "
            "FILTER v._key != @start_key "
            "COLLECT k = v._key COLLECT WITH COUNT INTO c RETURN c",
            bind_vars={"start": f"{NODES_COL}/{node_id}", "start_key": str(node_id)},
        ))
        return int(r[0])

    def probe_aggregate(self) -> dict:
        rows = list(self._db().aql.execute(
            f"FOR u IN {NODES_COL} COLLECT g = u.gender WITH COUNT INTO c RETURN {{gender: g, count: c}}"
        ))
        return {str(r["gender"]): int(r["count"]) for r in rows}

    # -- validation / footprint -------------------------------------------
    def counts(self) -> tuple[int, int]:
        db = self._db()
        return (db.collection(NODES_COL).count(), db.collection(EDGES_COL).count())

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
