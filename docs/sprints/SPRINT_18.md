# Sprint 18 Briefing

Read `WORKER_GUIDE.md` first. Both tasks are pure pattern-coverage additions — no refactoring.
Worker A fills the Java Spring messaging/async/cache gap and adds Python Celery support.
Worker B fills the remaining Rust gaps (UUID, Redis, message consumers), then bumps the version
and updates docs.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — Java Spring annotation patterns

**Where:** `_extract_java_semantic_spans` (search for `def _extract_java_semantic_spans`).

Add the following blocks. Each is a **new standalone `if` statement**, added after the
existing `@Transactional/@Query` database_io check.

---

#### A1a — Message listener annotations → `input_boundary`

```python
if re.search(
    r"@(?:KafkaListener|RabbitListener|SqsListener|EventListener|JmsListener)\b",
    text,
):
    self._record_semantic_ref(
        refs, node, "input_boundary", lineno, lineno,
        "Message-listener annotation marks this method as a queue/event consumer.",
    )
```

These annotations appear on methods that receive messages from Kafka, RabbitMQ, AWS SQS,
Spring application events, or JMS — all input boundaries.

---

#### A1b — Async execution annotation → `process_io`

```python
if re.search(r"@Async\b", text):
    self._record_semantic_ref(
        refs, node, "process_io", lineno, lineno,
        "@Async marks a method that runs in a separate thread pool.",
    )
```

---

#### A1c — Cache annotations → `state_mutation`

```python
if re.search(r"@(?:Cacheable|CacheEvict|CachePut|Caching)\b", text):
    self._record_semantic_ref(
        refs, node, "state_mutation", lineno, lineno,
        "Spring cache annotation reads or mutates a shared cache store.",
    )
```

---

#### A1d — Scheduled annotation → `time_or_randomness`

```python
if re.search(r"@Scheduled\b", text):
    self._record_semantic_ref(
        refs, node, "time_or_randomness", lineno, lineno,
        "@Scheduled drives execution by a time-based trigger.",
    )
```

---

### Task A2 — Python Celery task patterns

**Where:** `_extract_python_semantic_spans` — the `process_io` block (currently detects
`subprocess`, `os.system`, `asyncio.create_subprocess_exec/shell`).

Add one condition as an additional `or` clause inside the existing `process_io` `if` block:

```python
or re.search(r"@(?:\w+\.)?(?:task|shared_task)\s*(?:\(|$)", text)
```

This matches:
- `@app.task` / `@celery.task` — bound task decorator
- `@shared_task` — reusable task decorator (Celery best-practice pattern)
- `@app.task(bind=True)` — the `(?:\(|$)` allows for optional arguments or end-of-line

---

### Verification for Worker A

```bash
python -m py_compile god_mode_v3.py
python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only
rg -n "KafkaListener\|RabbitListener\|SqsListener\|@Async\|Cacheable\|@Scheduled\|shared_task" god_mode_v3.py
```

Expected: `parse_errors=0`, `nodes=74, edges=58`. The `rg` output must show all new
patterns inside the extractor methods.

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–end, plus Rust extractor and docs.
Note: `_extract_rust_semantic_spans` is at line ~4041 (Worker A territory by line number)
— edit it as part of this task.

### Task B1 — Rust missing patterns

**Where:** `_extract_rust_semantic_spans` (search for `def _extract_rust_semantic_spans`).

---

#### B1a — UUID generation → `time_or_randomness`

Find the existing `time_or_randomness` check in the Rust extractor:
```python
if re.search(r"\b(?:SystemTime::now|rand::)\b", text):
```

Add `uuid::Uuid::new_v` as an additional `or` clause:
```python
or re.search(r"\buuid::Uuid::new_v\d\b", text)
```

This matches `uuid::Uuid::new_v4()` and `uuid::Uuid::new_v7()` from the `uuid` crate.

---

#### B1b — Redis client → `database_io`

Find the existing `database_io` check in the Rust extractor (currently detects `diesel::`,
`sqlx::`, `tokio_postgres::`, `sea_orm::`, `rusqlite::`). Add one `or` clause:

```python
or re.search(r"\bredis::(?:Client|Connection|Commands|AsyncCommands)\b", text)
```

This covers `redis::Client::open(...)` and direct trait imports from the `redis` crate
(`redis::Commands`, `redis::AsyncCommands`).

---

#### B1c — Message consumers → `input_boundary`

Find the existing `input_boundary` check in the Rust extractor (currently detects actix-web
routes and axum extractors). Add two `or` clauses:

```python
or re.search(r"\blapin::\b", text)
or re.search(r"\brdkafka::consumer::\b", text)
```

`lapin` is the primary Rust AMQP/RabbitMQ client library. `rdkafka::consumer` is the
Confluent Kafka consumer for Rust. Both mark code that receives messages from external brokers.

---

### Task B2 — Version bump and docs

**Version:** Bump `god_mode_v3.py` line 672 from `"3.47"` to `"3.48"`.

**CHANGES.md:** Append:

```markdown
## Sprint 18 — Pattern coverage: Java Spring + Python Celery + Rust gaps (v3.48)

### Change 1 — Java Spring annotation patterns
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Method** | `_extract_java_semantic_spans` |
| **Category** | Pattern coverage |

- `input_boundary`: `@KafkaListener`, `@RabbitListener`, `@SqsListener`, `@EventListener`, `@JmsListener`
- `process_io`: `@Async`
- `state_mutation`: `@Cacheable`, `@CacheEvict`, `@CachePut`, `@Caching`
- `time_or_randomness`: `@Scheduled`

### Change 2 — Python Celery task patterns
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Method** | `_extract_python_semantic_spans` |
| **Category** | Pattern coverage |

- `process_io`: `@app.task`, `@celery.task`, `@shared_task` decorators

### Change 3 — Rust missing patterns
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Method** | `_extract_rust_semantic_spans` |
| **Category** | Pattern coverage |

- `time_or_randomness`: `uuid::Uuid::new_v4/new_v7`
- `database_io`: `redis::Client/Connection/Commands/AsyncCommands`
- `input_boundary`: `lapin::` (AMQP/RabbitMQ), `rdkafka::consumer::` (Kafka)
```

**WORKER_GUIDE.md:** Update Current state:
- Version: `**3.48**`
- Sprint history: `20 passes (Runs 1–3 autonomous, Sprints 1–18)`

---

### Verification for Worker B

```bash
python -m py_compile god_mode_v3.py
python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only
rg -n '"version"' god_mode_v3.py
rg -n "uuid::Uuid::new_v\|redis::.*Client\|lapin::\|rdkafka::consumer" god_mode_v3.py
```

Expected: `parse_errors=0`, `nodes=74, edges=58`. The `rg` output must show all new
patterns inside `_extract_rust_semantic_spans`.

---

## Handoff

- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`
