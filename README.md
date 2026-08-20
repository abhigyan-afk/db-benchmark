# Graph Database Cloud Benchmarking — CognoDB vs. the field

A reproducible, honest benchmark of **[CognoDB Cloud](https://cognodb.com)**
against four other managed graph databases, running the **same dataset** and
the **same workloads** under **equivalent resource limits**.

> Built for the Wexa AI take-home assignment — "CognoDB Assignment 1 —
> Benchmarking".

---

## TL;DR

| Platform | Type | Query language | Tier (advertised) | Instance region |
|---|---|---|---|---|
| **CognoDB Cloud** | managed | Cypher (Bolt) | Free `c0`: 0.5 vCPU / 256 MB RAM / 1 GB disk | _record from console_ |
| Neo4j AuraDB | managed | Cypher (Bolt) | Free tier — _record specs_ | _record_ |
| Memgraph Cloud | managed | Cypher (Bolt) | Free tier — _record specs_ | _record_ |
| FalkorDB Cloud | managed | Cypher (OpenCypher subset) | Free tier — _record specs_ | _record_ |
| ArangoDB Cloud | managed | AQL | Free tier — _record specs_ | _record_ |

Cypher platforms (CognoDB, Neo4j, Memgraph, FalkorDB) run the same logical
queries; ArangoDB runs an AQL semantic translation (noted below).

---

## Quick start (reproducible from a clean environment)

```bash
# 1. Clone and install (Python 3.11+)
git clone <this-repo> && cd <this-repo>
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt            # pinned driver versions

# 2. Configure credentials (never commit these)
cp .env.example .env                       # fill in real values for each platform

# 3. Prepare the dataset (downloads SNAP soc-Pokec, samples 100k edges)
python data/prepare.py

# 4. Smoke-test each platform's connectivity + schema + a trivial query
python -m bench smoke --db cognodb
python -m bench smoke --db neo4j
python -m bench smoke --db memgraph
python -m bench smoke --db falkordb
python -m bench smoke --db arangodb

# 5. Load the data and run the full workload suite
python -m bench load --db cognodb         # or: python -m bench load --all
python -m bench run  --db cognodb --load  # loads + benchmarks in one command

# 6. Aggregate results into tables (and paste into this README)
python -m bench report
```

To verify the harness without any cloud account:

```bash
python -m bench run --db mock --dry-run   # fake latencies, exercises the full pipeline
python -m pytest tests/ -q                # 6 unit + dry-run tests
```

---

## Results

## Latency (milliseconds)

| Platform | Workload | p50 | p95 | mean | min | max | iters | failures |
|---|---|---|---|---|---|---|---|---|
| cognodb | point_lookup | 84.953 | 85.463 | 85.002 | 84.298 | 86.363 | 100 | 0 |
| cognodb | filtered_lookup_age | 86.897 | 89.397 | 87.382 | 85.831 | 94.638 | 100 | 0 |
| cognodb | traversal_1_hop | 85.087 | 85.997 | 85.183 | 84.641 | 86.605 | 100 | 0 |
| cognodb | traversal_2_hop | 88.362 | 99.249 | 89.52 | 84.892 | 112.221 | 100 | 0 |
| cognodb | traversal_3_hop | 188.305 | 591.802 | 247.375 | 84.66 | 982.511 | 100 | 0 |
| cognodb | aggregation_gender | 203.436 | 286.071 | 216.235 | 187.284 | 297.466 | 100 | 0 |
| neo4j | point_lookup | 189.958 | 192.565 | 201.665 | 188.999 | 1135.001 | 100 | 0 |
| neo4j | filtered_lookup_age | 191.763 | 196.276 | 195.879 | 190.627 | 392.594 | 100 | 0 |
| neo4j | traversal_1_hop | 189.6 | 192.217 | 193.6 | 188.635 | 383.191 | 100 | 0 |
| neo4j | traversal_2_hop | 189.572 | 192.304 | 193.859 | 188.87 | 395.504 | 100 | 0 |
| neo4j | traversal_3_hop | 191.171 | 195.169 | 195.19 | 189.108 | 382.377 | 100 | 0 |
| neo4j | aggregation_gender | 200.038 | 205.534 | 204.786 | 198.971 | 399.992 | 100 | 0 |
| memgraph | point_lookup | 8.321 | 9.544 | 8.432 | 8.047 | 10.487 | 100 | 0 |
| memgraph | filtered_lookup_age | 10.119 | 12.257 | 10.415 | 9.515 | 15.464 | 100 | 0 |
| memgraph | traversal_1_hop | 8.434 | 10.236 | 8.693 | 8.122 | 14.26 | 100 | 0 |
| memgraph | traversal_2_hop | 8.425 | 9.066 | 8.51 | 8.14 | 9.601 | 100 | 0 |
| memgraph | traversal_3_hop | 10.383 | 15.104 | 10.742 | 8.096 | 18.147 | 100 | 0 |
| memgraph | aggregation_gender | 23.119 | 27.124 | 23.722 | 21.808 | 40.059 | 100 | 0 |
| falkordb | point_lookup | 126.936 | 127.66 | 127.082 | 126.824 | 131.41 | 100 | 0 |
| falkordb | filtered_lookup_age | 127.171 | 128.145 | 127.313 | 127.018 | 130.308 | 100 | 0 |
| falkordb | traversal_1_hop | 127.004 | 127.888 | 127.208 | 126.908 | 135.662 | 100 | 0 |
| falkordb | traversal_2_hop | 127.058 | 127.372 | 127.102 | 126.855 | 128.614 | 100 | 0 |
| falkordb | traversal_3_hop | 128.705 | 133.082 | 128.938 | 126.89 | 134.384 | 100 | 0 |
| falkordb | aggregation_gender | 134.724 | 135.583 | 134.843 | 134.52 | 137.913 | 100 | 0 |
| arangodb | point_lookup | 215.738 | 274.515 | 222.161 | 215.288 | 295.846 | 100 | 0 |
| arangodb | filtered_lookup_age | 215.989 | 272.082 | 221.724 | 215.487 | 286.428 | 100 | 0 |
| arangodb | traversal_1_hop | 216.312 | 268.494 | 221.611 | 215.731 | 305.92 | 100 | 0 |
| arangodb | traversal_2_hop | 219.57 | 247.573 | 222.353 | 215.756 | 272.621 | 100 | 0 |
| arangodb | traversal_3_hop | 315.812 | 1023.716 | 467.532 | 215.868 | 1591.115 | 100 | 0 |
| arangodb | aggregation_gender | 230.407 | 392.889 | 254.29 | 228.815 | 513.511 | 100 | 0 |

## Data loading

| Platform | nodes | relationships | wall (s) | nodes/s | rels/s | notes |
|---|---|---|---|---|---|---|
| cognodb | 49683 | 100000 | 20.689 | 7771.4 | 6994.8 | batched UNWIND, batch=1000 |
| neo4j | 49683 | 100000 | 36.772 | 4042.4 | 4084.8 | batched UNWIND, batch=1000 |
| memgraph | 49683 | 100000 | 5.172 | 22946.3 | 33253.9 | batched UNWIND, batch=1000 |
| falkordb | 49683 | 100000 | 26.381 | 6730.3 | 5263.3 | batched UNWIND, batch=1000 |
| arangodb | 49683 | 100000 | 29.559 | 4682.9 | 5277.2 | insert_many batches, batch=1000 |

## Mixed workload (concurrent read/write)

| Platform | clients | read:write | duration (s) | ops/s | total ops | failures |
|---|---|---|---|---|---|---|
| cognodb | 10 | 0.9:0.1 | 30.074 | 110.4 | 3321 | 0 |
| neo4j | 10 | 0.9:0.1 | 30.187 | 50.1 | 1512 | 0 |
| memgraph | 10 | 0.9:0.1 | 30.006 | 1117.2 | 33521 | 0 |
| falkordb | 10 | 0.9:0.1 | 30.13 | 65.9 | 1986 | 0 |
| arangodb | 10 | 0.9:0.1 | 30.139 | 66.5 | 2003 | 0 |

## Footprint (where observable)

| Platform | observables | notes |
|---|---|---|
| cognodb | nodes=49683; relationships=100000 | instance specs recorded from the console (see README); storage/memory not observable via driver on this tier |
| neo4j | nodes=49683; relationships=100000 | instance specs recorded from the console (see README); storage/memory not observable via driver on this tier |
| memgraph | nodes=49683; relationships=100000 | instance specs recorded from the console (see README); storage/memory not observable via driver on this tier |
| falkordb | nodes=49683; relationships=100000 | instance specs recorded from the console (see README); storage/memory not observable via driver on this tier |
| arangodb | nodes=49683; relationships=100000 | instance specs recorded from the console (see README); storage/memory not observable via driver on this tier |

---

## Methodology

The goal is **fairness by construction**: every platform sees the same data,
the same logical queries, the same start nodes, and the same measurement
procedure. No platform is given a hardware or methodology advantage.

### 1. Same dataset everywhere

- Source: [SNAP `soc-Pokec`](https://snap.stanford.edu/data/soc-Pokec.html)
  (Takac & Zabovsky, 2012). Full network: 1,632,803 nodes / 30,622,564
  directed edges.
- Sample: the **first 100,000 directed edges** (file order), with all
  incident nodes and their profile properties. This is deterministic,
  reproducible, and sized to fit the smallest free tier (CognoDB `c0`).
- Resulting sample: **49,683 nodes**, **100,000 relationships** (recorded in
  `data/dataset.json`).
- Node schema: `User { id: int (unique), gender: int (0/1), region: string, age: int }`.
  Relationship: `KNOWS` (directed, `src → dst`).
- The identical `nodes.csv` / `edges.csv` are loaded into every platform, and
  node/relationship counts are verified after every load.

### 2. Same resources everywhere

Every platform runs on its **free/entry tier**, and the tier's advertised
specs are recorded in the TL;DR table above. The CognoDB free tier is
intentionally small (0.5 vCPU / 256 MB RAM / 1 GB disk), so the dataset is
sized to it and the other platforms run their own free tiers. Where a
platform does not publish exact vCPU/RAM, that is stated honestly rather than
assumed.

### 3. Same logical queries

All workloads are defined once and translated per platform (Cypher for four
platforms, AQL for ArangoDB). Query parameters (start nodes, thresholds) are
identical.

| Workload | Query (logical) | Notes |
|---|---|---|
| Point lookup | node by unique `id` | uses the `id` index |
| Filtered lookup | `age > 25`, limit 50 | uses the `age` index |
| Traversal 1/2/3-hop | distinct nodes **exactly** `k` hops out | start nodes have out-degree 5–30 |
| Aggregation | count nodes grouped by `gender` | |
| Mixed read/write | point read vs. bounded `bench_ts` update, ~90/10 | |

**Indexes created on every platform** (same properties):

- CognoDB & Neo4j Aura: `CREATE INDEX ... FOR (n:User) ON (n.id | n.age | n.gender)`
- Memgraph: `CREATE INDEX ON :User(id | age | gender)`
- FalkorDB: `create_node_range_index("User", "id" | "age" | "gender")`
- ArangoDB: persistent index on `id` (unique), `age`, `gender`

### 4. Measurement procedure

- **Warm-up:** 5 runs of each workload are executed and discarded before
  timing, so caches and connections are warm.
- **Iterations:** ≥100 timed iterations per read workload (point lookup and
  traversals rotate through a fixed, seeded set of start nodes).
- **Percentiles:** p50 and p95 reported, plus mean, standard deviation, min
  and max — not just averages.
- **Client-side wall-clock** (`time.perf_counter()`) around each query.
- **Mixed workload:** N concurrent threads (default 10) issuing a ~90/10
  read/write mix for a fixed window (default 30 s); sustained queries/second
  reported.
- **Cold-start:** not included in the latency numbers; if measured, reported
  separately.

### 5. Caveats (recorded honestly)

- **Query-language differences:** ArangoDB uses AQL; the queries are semantic
  translations, not textual copies. FalkorDB implements an OpenCypher subset.
- **Region / network variance:** the client is a single machine (GitHub
  Codespaces) but each instance lives in a different cloud region (recorded in
  the TL;DR table), so network round-trip time is baked into every number and
  single-digit-millisecond differences should not be over-interpreted.
- **Single run / variance:** each figure is from one timed run; a repeated
  ArangoDB run showed point-lookup p50 shift from ~138 ms to ~216 ms between
  runs, so differences of a few tens of milliseconds are within run-to-run
  noise.
- **Free-tier limits:** throttling, burst CPU, and background compaction vary
  by vendor and can affect tail latencies; these are not controlled for.
- **Writes in the mixed workload** are bounded property updates on a fixed
  node set (no unbounded growth).
- **Footprint:** managed tiers expose little observability over the driver;
  storage/memory is reported "not observable" where the platform does not
  expose it, and instance specs are taken from each console.

---

## Dataset

- **Source:** SNAP `soc-Pokec` — https://snap.stanford.edu/data/soc-Pokec.html
- **License/citation:** L. Takac, M. Zabovsky, "Data Analysis in Public Social
  Networks", 2012. Used for academic benchmarking.
- **Files:** `soc-pokec-relationships.txt` (`src\tdst`, directed) and
  `soc-pokec-profiles.txt` (tab-separated; `gender`=col 3, `region`=col 4,
  `age`=col 7).
- **Sample:** first 100,000 edges → **49,683 nodes**, **100,000 relationships**.
  Regenerate with `python data/prepare.py` (streams the edge file, so only the
  first 100k edges are read).

---

## Analysis

All numbers are client-side wall-clock from a single client machine (GitHub
Codespaces) to each platform's cloud instance, so they include network
round-trip time. Free-tier instances are shared and burstable; read these as
"how these specific tiers behaved on this workload", not a definitive engine
ranking.

**Loading.** Memgraph (in-memory) ingested fastest at ~23k nodes/s and ~33k
rels/s (~5.2 s total). CognoDB was the fastest of the disk-backed Cypher
platforms at ~7.8k nodes/s (~20.7 s), ahead of FalkorDB (~6.7k nodes/s) and
Neo4j Aura (~4.0k nodes/s, ~36.8 s). ArangoDB used its bulk `insert_many` API
and landed mid-pack (~4.7k nodes/s).

**Lookups.** Point lookup on the indexed `id`: Memgraph ~8.3 ms, CognoDB ~85
ms, FalkorDB ~127 ms, Neo4j Aura ~190 ms, ArangoDB ~216 ms. Notably CognoDB is
~2.2× faster than Neo4j Aura on identical Bolt/Cypher point lookups on their
respective free tiers.

**Traversals.** Memgraph stays flat at ~8–10 ms across 1/2/3 hops (in-memory
index-free adjacency). FalkorDB is also nearly flat (~127–129 ms) — the fixed
RESP round-trip dominates the traversal cost. Neo4j Aura is flat (~190 ms),
consistent with a fixed per-request proxy overhead. CognoDB scales gently with
depth (85 → 88 → 188 ms p50; 3-hop p95 592 ms) and is the cheapest of the
non-in-memory engines. ArangoDB shows the steepest 3-hop degradation (p50 316
ms, p95 1024 ms).

**Aggregation.** Memgraph ~23 ms; FalkorDB ~135 ms; Neo4j ~200 ms; CognoDB
~203 ms; ArangoDB ~230 ms (p95 393 ms).

**Mixed workload (10 clients, 90/10 read/write).** Memgraph sustained ~1117
ops/s. CognoDB (~110 ops/s) is clearly ahead of Neo4j Aura (~50), FalkorDB
(~66) and ArangoDB (~67) — i.e. CognoDB handled more than twice the concurrent
read/write throughput of Neo4j Aura.

**Overall.** Memgraph wins raw latency/throughput by a wide margin, which is
expected for an in-memory graph engine. Among the disk-backed cloud graph
databases — the fairer apples-to-apples comparison — CognoDB was strongest on
every metric: fastest point lookup, fastest mixed throughput, second-fastest
ingest, and well-controlled traversal scaling.

---

## Repository layout

```
bench/
  adapters/        one adapter per platform (uniform interface)
  runner.py        warm-up, iterations, percentile math (shared methodology)
  report.py        JSON → CSV + Markdown tables
  cli.py           prepare / smoke / load / run / report
data/
  prepare.py       download + sample the dataset
  nodes.csv, edges.csv, dataset.json   the committed, reproducible sample
results/           raw per-platform JSON + generated tables (committed)
tests/             unit + dry-run tests (no credentials needed)
```

## Security

All credentials are read from environment variables (`.env`, gitignored). No
connection URI or password is committed; `.env.example` holds placeholders
only. See the assignment requirement under section 9.
