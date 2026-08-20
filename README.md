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
| **CognoDB Cloud** | managed | Cypher (Bolt) | Free `c0`: 0.5 vCPU / 256 MB RAM / 1 GB disk | `us-east1` (GCP, ~Washington DC) |
| Neo4j AuraDB | managed | Cypher (Bolt) | Free tier ($0) — vCPU/RAM **not published** (limited by node/relationship count) | Singapore (GCP) |
| Memgraph Cloud | managed | Cypher (Bolt) | Free/entry tier — RAM from 1 GB; vCPU **not published** | `eu-central-1` (AWS, Frankfurt) |
| FalkorDB Cloud | managed | Cypher (OpenCypher subset) | Free tier — specs **not published** | `ap-south-1` (AWS, Mumbai) |
| ArangoDB Cloud | managed | AQL | Free tier — specs **not published** | `ap-south-1` (AWS, Mumbai) |

We used each platform's **free/entry configuration** and report the published
resource limits. Where exact parity was unavailable (most vendors do not publish
exact vCPU/RAM for their free tiers), the difference is documented as a
benchmark limitation rather than assumed.

Regions are inferred from the instance IP address (Google/AWS geolocation) and
the FalkorDB hostname; they are approximate and recorded so the network
component of every measurement is transparent.

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

# 5. Load the data (verifies counts + indexes on every platform)
python -m bench load --all

# 6. Cross-database correctness check (all 5 must agree)
python -m bench verify

# 7. Run the full workload suite
python -m bench run --all

# 8. Aggregate results into tables (and paste into this README)
python -m bench report
```

To verify the harness without any cloud account:

```bash
python -m bench run --db mock --dry-run   # fake latencies, exercises the full pipeline
python -m pytest tests/ -q                # unit + dry-run tests
```

---

## Results

## Latency (milliseconds)

| Platform | Workload | p50 | p95 | p99 | mean | min | max | iters | failures |
|---|---|---|---|---|---|---|---|---|---|
| cognodb | point_lookup | 85.112 | 86.102 | 91.872 | 85.65 | 84.723 | 122.916 | 100 | 0 |
| cognodb | filtered_lookup_age | 86.931 | 89.579 | 89.997 | 87.168 | 86.082 | 90.484 | 100 | 0 |
| cognodb | traversal_1_hop | 85.255 | 86.138 | 87.2 | 85.361 | 84.73 | 88.339 | 100 | 0 |
| cognodb | traversal_2_hop | 88.22 | 98.671 | 100.613 | 89.39 | 84.833 | 103.913 | 100 | 0 |
| cognodb | traversal_3_hop | 204.328 | 625.691 | 965.498 | 261.037 | 85.069 | 1000.074 | 100 | 0 |
| cognodb | aggregation_gender | 202.611 | 280.233 | 295.542 | 209.845 | 182.551 | 299.965 | 100 | 0 |
| cognodb | aggregation_rel_type | 407.706 | 489.709 | 496.743 | 419.225 | 380.864 | 572.61 | 100 | 0 |
| neo4j | point_lookup | 189.159 | 191.071 | 389.97 | 200.718 | 188.755 | 1126.391 | 100 | 0 |
| neo4j | filtered_lookup_age | 191.001 | 194.908 | 381.76 | 195.229 | 190.149 | 387.599 | 100 | 0 |
| neo4j | traversal_1_hop | 189.407 | 191.269 | 194.719 | 191.524 | 188.864 | 384.787 | 100 | 0 |
| neo4j | traversal_2_hop | 189.649 | 190.92 | 387.84 | 193.732 | 189.065 | 389.074 | 100 | 0 |
| neo4j | traversal_3_hop | 191.527 | 196.768 | 386.993 | 195.928 | 189.207 | 396.118 | 100 | 0 |
| neo4j | aggregation_gender | 200.135 | 203.641 | 394.888 | 204.509 | 199.466 | 402.355 | 100 | 0 |
| neo4j | aggregation_rel_type | 200.693 | 204.809 | 392.884 | 205.181 | 199.793 | 402.263 | 100 | 0 |
| memgraph | point_lookup | 8.383 | 9.809 | 12.705 | 8.594 | 7.993 | 12.889 | 100 | 0 |
| memgraph | filtered_lookup_age | 10.224 | 14.224 | 15.58 | 10.755 | 9.515 | 17.278 | 100 | 0 |
| memgraph | traversal_1_hop | 8.335 | 8.738 | 10.098 | 8.392 | 8.067 | 10.231 | 100 | 0 |
| memgraph | traversal_2_hop | 8.503 | 10.04 | 10.684 | 8.668 | 8.074 | 10.759 | 100 | 0 |
| memgraph | traversal_3_hop | 11.767 | 21.245 | 25.207 | 12.63 | 8.3 | 27.365 | 100 | 0 |
| memgraph | aggregation_gender | 22.499 | 25.586 | 27.302 | 23.04 | 21.732 | 32.909 | 100 | 0 |
| memgraph | aggregation_rel_type | 42.963 | 50.716 | 57.782 | 43.865 | 38.709 | 59.715 | 100 | 0 |
| falkordb | point_lookup | 126.944 | 128.151 | 128.837 | 127.085 | 126.801 | 129.173 | 100 | 0 |
| falkordb | filtered_lookup_age | 127.2 | 128.169 | 128.896 | 127.341 | 127.003 | 129.181 | 100 | 0 |
| falkordb | traversal_1_hop | 127.034 | 127.729 | 128.398 | 127.123 | 126.865 | 128.442 | 100 | 0 |
| falkordb | traversal_2_hop | 127.151 | 128.229 | 128.554 | 127.276 | 126.919 | 129.369 | 100 | 0 |
| falkordb | traversal_3_hop | 129.315 | 134.839 | 135.961 | 129.68 | 126.998 | 136.22 | 100 | 0 |
| falkordb | aggregation_gender | 134.749 | 136.048 | 136.235 | 134.916 | 134.552 | 138.58 | 100 | 0 |
| falkordb | aggregation_rel_type | 203.369 | 246.153 | 250.097 | 208.78 | 201.918 | 257.151 | 100 | 0 |
| arangodb | point_lookup | 133.285 | 170.388 | 200.025 | 138.374 | 132.731 | 200.274 | 100 | 0 |
| arangodb | filtered_lookup_age | 133.571 | 197.454 | 200.148 | 140.001 | 133.079 | 200.57 | 100 | 0 |
| arangodb | traversal_1_hop | 133.964 | 192.694 | 199.439 | 138.95 | 133.284 | 200.06 | 100 | 0 |
| arangodb | traversal_2_hop | 138.657 | 203.424 | 300.148 | 150.4 | 133.541 | 305.282 | 100 | 0 |
| arangodb | traversal_3_hop | 484.82 | 1690.198 | 2197.439 | 647.015 | 133.855 | 2227.64 | 100 | 0 |
| arangodb | aggregation_gender | 145.912 | 320.199 | 379.412 | 172.052 | 143.698 | 381.597 | 100 | 0 |
| arangodb | aggregation_rel_type | 142.693 | 295.314 | 299.079 | 162.032 | 141.437 | 301.555 | 100 | 0 |

## Data loading

| Platform | nodes | relationships | node load (s) | index (s) | rel load (s) | total (s) | nodes/s | rels/s | notes |
|---|---|---|---|---|---|---|---|---|---|
| cognodb | 49683 | 100000 | 6.072 | 0.255 | 14.423 | 20.75 | 8182.7 | 6933.2 | batched UNWIND, batch=1000 |
| neo4j | 49683 | 100000 | 12.28 | 0.578 | 24.619 | 37.476 | 4046.0 | 4062.0 | batched UNWIND, batch=1000 |
| memgraph | 49683 | 100000 | 2.371 | 0.025 | 3.13 | 5.526 | 20957.4 | 31950.3 | batched UNWIND, batch=1000 |
| falkordb | 49683 | 100000 | 7.359 | 0.423 | 18.905 | 26.687 | 6751.1 | 5289.7 | batched UNWIND, batch=1000 |
| arangodb | 49683 | 100000 | 11.433 | 4.19 | 20.579 | 36.202 | 4345.5 | 4859.2 | insert_many batches, batch=1000 |

## Mixed workload (concurrent read/write)

| Platform | clients | cfg read:write | actual read:write | duration (s) | ops/s | total ops | read ops | write ops | failures |
|---|---|---|---|---|---|---|---|---|---|---|
| cognodb | 10 | 0.9:0.1 | 0.8996:0.1004 | 30.094 | 110.2 | 3317 | 2984 | 333 | 2 |
| neo4j | 10 | 0.9:0.1 | 0.9032:0.0968 | 30.186 | 50.0 | 1508 | 1362 | 146 | 0 |
| memgraph | 10 | 0.9:0.1 | 0.9017:0.0983 | 30.009 | 1063.3 | 31909 | 28773 | 3136 | 1 |
| falkordb | 10 | 0.9:0.1 | 0.8926:0.1074 | 30.119 | 71.1 | 2142 | 1912 | 230 | 0 |
| arangodb | 10 | 0.9:0.1 | 0.8939:0.1061 | 30.125 | 70.7 | 2131 | 1905 | 226 | 0 |

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
  `data/dataset.json`, with the SHA-256 of `nodes.csv` and `edges.csv`).
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
assumed, and the lack of exact hardware parity is a documented limitation.

### 3. Same logical queries

All workloads are defined once and translated per platform (Cypher for four
platforms, AQL for ArangoDB). Query parameters (start nodes, thresholds) are
identical.

| Workload | Query (logical) | Notes |
|---|---|---|
| Point lookup | node by unique `id` | uses the `id` index |
| Filtered lookup | `age > 25`, limit 50 | uses the `age` index |
| Traversal 1/2/3-hop | distinct nodes **within** `k` hops | start node excluded; start nodes have out-degree 5–30 |
| Aggregation (gender) | count nodes grouped by `gender` | |
| Aggregation (rel type) | count relationships grouped by type | dataset has one type (`KNOWS`) |
| Mixed read/write | point read vs. bounded `bench_ts` update, ~90/10 | concurrency + actual read/write split recorded |

**Traversal semantics.** "N-hop traversal" is defined as *distinct nodes
reachable within N hops* (shortest-path distance ≤ N), with the start node
excluded. This definition is unambiguous across engines: a `*N..N`
("exactly N") pattern is not comparable because engines disagree on whether a
node reachable via both a shorter and a length-N path (or via a cycle back to
the start) should be counted. We verified the `within N` definition yields
identical counts on all five platforms before timing.

**Indexes created on every platform** (same properties: `id`, `age`, `gender`):

- CognoDB & Neo4j Aura: `CREATE INDEX ... FOR (n:User) ON (n.id | n.age | n.gender)`
- Memgraph: `CREATE INDEX ON :User(id | age | gender)`
- FalkorDB: `create_node_range_index("User", "id" | "age" | "gender")`
- ArangoDB: persistent index on `id` (unique), `age`, `gender`

Index creation is **verified** (not assumed): after load, each adapter lists
the platform's indexes and fails if any required index is missing, so a
"filtered lookup" can never silently degrade into a full collection scan.

### 4. Measurement procedure

- **Warm-up:** 20 runs of each workload are executed and discarded before
  timing, so caches and connections are warm. Warm-up failures are counted; if
  *every* warm-up iteration fails, the workload is aborted rather than
  measured against a broken query.
- **Iterations:** ≥100 timed iterations per read workload (point lookup and
  traversals rotate through a fixed, seeded set of start nodes).
- **Percentiles:** p50, p95 and **p99** reported, plus mean, standard
  deviation, min and max — not just averages. **Raw per-iteration samples are
  retained** in `results/` so outliers can be investigated.
- **Client-side wall-clock** (`time.perf_counter()`) around each query.
- **Load timing** is split into three phases — `node_load_seconds`,
  `index_creation_seconds`, `relationship_load_seconds` — so node and
  relationship insert throughput are reported independently of index build.
- **Mixed workload:** N concurrent threads (default 10) issuing a ~90/10
  read/write mix for a fixed window (default 30 s). The **actual** read and
  write operation counts (and the actual achieved ratio) are recorded, not
  just the configured ratio, so throughput is defensible.
- **Correctness cross-check:** before timing, 10 deterministic probe nodes are
  queried on every platform (point lookup, filtered count, 1/2/3-hop, gender
  aggregation) and the results must agree across all five platforms.
- **Cold-start:** not included in the latency numbers; if measured, reported
  separately.

### 5. Caveats (recorded honestly)

- **Query-language differences:** ArangoDB uses AQL; the queries are semantic
  translations, not textual copies. FalkorDB implements an OpenCypher subset.
- **Region / network variance:** the client is a single machine (GitHub
  Codespaces, US) but each instance lives in a different cloud region (see the
  TL;DR table), so network round-trip time is baked into every number and
  single-to-tens-of-millisecond differences should not be over-interpreted.
- **Single run / variance:** each figure is from one timed run; run-to-run
  variance on shared free tiers can exceed the difference between adjacent
  platforms, so only consistent, order-of-magnitude differences are
  meaningful.
- **Free-tier limits:** throttling, burst CPU, auto-pause/resume, and
  background compaction vary by vendor and can affect tail latencies; these
  are not controlled for.
- **Writes in the mixed workload** are bounded property updates on a fixed
  node set (no unbounded growth).
- **Footprint:** managed tiers expose little observability over the driver;
  storage/memory is reported "not observable" where the platform does not
  expose it, and instance specs are taken from each console / pricing page.

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
  first 100k edges are read). Selection is deterministic (file order, no
  random seed); checksums are recorded in `data/dataset.json`.

---

## Analysis

All numbers are client-side wall-clock from a single client machine (GitHub
Codespaces) to each platform's cloud instance, so they include network
round-trip time. Free-tier instances are shared and burstable; read these as
"how these specific tiers behaved on this workload", not a definitive engine
ranking. Only consistent, order-of-magnitude differences are meaningful.

**Loading.** Memgraph (in-memory) ingested fastest at ~21k nodes/s and ~32k
rels/s (~5.5 s total). Among the disk-backed engines, CognoDB was fastest at
~8.2k nodes/s (~20.8 s), ahead of FalkorDB (~6.8k nodes/s, ~26.7 s), ArangoDB
(~4.3k nodes/s, ~36.2 s) and Neo4j Aura (~4.0k nodes/s, ~37.5 s). Index build
time was negligible everywhere except ArangoDB (~4.2 s), where three
persistent indexes are built on a fresh collection.

**Lookups.** Point lookup on the indexed `id`: Memgraph ~8.4 ms, CognoDB ~85
ms, FalkorDB ~127 ms, ArangoDB ~133 ms, Neo4j Aura ~189 ms. On identical
Bolt/Cypher point lookups against their respective free tiers, CognoDB is
~2.2× faster than Neo4j Aura. Filtered lookup (`age > 25`) tracks the same
ranking.

**Traversals (distinct nodes within N hops).** Memgraph stays near-flat at
~8–12 ms across 1/2/3 hops (in-memory index-free adjacency). FalkorDB is also
nearly flat (~127–129 ms) — the fixed RESP round-trip dominates the traversal
cost. Neo4j Aura is flat at ~190 ms, consistent with a fixed per-request proxy
overhead. CognoDB scales gently with depth (85 → 88 → 204 ms p50) and ArangoDB
degrades most at 3 hops (p50 485 ms, p95 1.7 s), consistent with a materialized
traversal over HTTP.

**Aggregation.** Gender aggregation (group over 49,683 nodes): Memgraph ~23
ms, FalkorDB ~135 ms, ArangoDB ~146 ms, Neo4j ~200 ms, CognoDB ~203 ms.
Relationship-type aggregation (group over 100,000 relationships) costs more on
the engines whose cost scales with data scanned — CognoDB rises to ~408 ms
while Neo4j stays ~200 ms, which suggests Neo4j's fixed ~190 ms request
overhead masks the extra scan cost. This is recorded as a single-run
observation, not a ranking claim.

**Mixed workload (10 clients, 90/10 read/write).** Memgraph sustained ~1063
ops/s. CognoDB (~110 ops/s) is ~2.2× ahead of Neo4j Aura (~50 ops/s) and ahead
of FalkorDB (~71) and ArangoDB (~71) — i.e. CognoDB handled more than twice the
concurrent read/write throughput of Neo4j Aura on comparable free tiers. The
measured read:write ratio stayed within ~1 point of the configured 90/10 on
every platform.

**Overall.** Memgraph wins raw latency/throughput by a wide margin, as expected
for an in-memory graph engine. Among the disk-backed cloud graph databases —
the fairer apples-to-apples comparison — CognoDB is strongest on the
lookup-intensive and write-mixed workloads (fastest point/filtered lookup and
mixed throughput, fastest ingest), while Neo4j Aura shows flatter latency
(consistent with a fixed proxy floor) and is faster on the relationship-type
aggregation. ArangoDB's numbers are the most variable between runs (its point
lookup p50 shifted from ~216 ms in an earlier session to ~133 ms here), which
underscores why single-run, sub-100 ms differences should not be over-read.

### What we would do differently

- **Concurrency sweep** (1/10/40 clients) on the mixed workload to separate
  client-side saturation from server-side limits.
- **Multiple timed passes** to quantify run-to-run variance instead of
  reporting one point estimate per metric.
- **p99 + outlier analysis** is included, but a longer tail histogram would
  better characterise the periodic latency spikes seen on free tiers.

---

## Repository layout

```
bench/
  adapters/        one adapter per platform (uniform interface)
  runner.py        warm-up, iterations, percentile math (shared methodology)
  report.py        JSON → CSV + Markdown tables
  environment.py   machine info, driver versions, git commit, dataset checksums
  cli.py           prepare / smoke / load / verify / run / report
data/
  prepare.py       download + sample the dataset
  nodes.csv, edges.csv, dataset.json   the committed, reproducible sample
results/           raw per-platform JSON + run manifest + generated tables (committed)
tests/             unit + dry-run tests (no credentials needed)
```

## Security

All credentials are read from environment variables (`.env`, gitignored). No
connection URI or password is committed; `.env.example` holds placeholders
only. See the assignment requirement under section 9.
