# SPRINT 27 — New Semantic Signals: `concurrency` + `caching` (all 9 languages)

**Version:** 3.56 → 3.57  
**File:** `god_mode_v3.py` + documentation  
**Workers:** A (lines 1–8730 + version bump) · B (lines 8730–end + README + CHANGES + WORKER_GUIDE)

---

## Goal

Add two new semantic signals across all nine supported languages:

- **`concurrency`** (weight 2.6) — fires when a symbol spawns threads, goroutines, coroutines,
  uses locks/channels/atomics, or submits work to an executor. High-risk: concurrent mutation
  creates race conditions invisible to static types.
- **`caching`** (weight 1.8) — fires when a symbol reads/writes a cache (Redis, Memcached,
  LRU, framework annotations like `@Cacheable`, `Rails.cache`, etc.). Medium-risk: cached data
  can become stale and is often overlooked in security reviews.

Additionally, four existing misclassified patterns are corrected in this sprint:
- Java `@Cacheable/@CacheEvict/@CachePut` — was `state_mutation`, now `caching`
- Kotlin `@Cacheable/@CacheEvict/@CachePut` — was `state_mutation`, now `caching`
- Kotlin coroutine builders (`launch`, `async`, `runBlocking`, …) — was `process_io`, now `concurrency`
- PHP `Cache::put/forget/remember` — was `state_mutation`, now `caching`
- Ruby `Rails.cache.write/fetch/delete` — was `state_mutation`, now `caching`

No new edge kinds. No new CLI flags. No new node types.

---

## Worker A Tasks

### 1. Signal Registration (lines 217–289)

#### `SEMANTIC_SIGNAL_WEIGHTS` — add two entries after `"orm_dynamic_load": 2.5,`

```python
    "concurrency": 2.6,
    "caching": 1.8,
```

After the change the dict ends with:
```python
    "dynamic_dispatch": 2.0,
    "orm_dynamic_load": 2.5,
    "concurrency": 2.6,
    "caching": 1.8,
}
```

#### `SEMANTIC_SIDE_EFFECT_SIGNALS` — add `"concurrency"` (line ~245)

```python
SEMANTIC_SIDE_EFFECT_SIGNALS = {
    "external_io",
    "network_io",
    "database_io",
    "filesystem_io",
    "process_io",
    "state_mutation",
    "concurrency",
}
```

#### `SEMANTIC_EXTERNAL_IO_SIGNALS` — add `"caching"` (line ~255)

```python
SEMANTIC_EXTERNAL_IO_SIGNALS = {"network_io", "database_io", "filesystem_io", "process_io", "orm_dynamic_load", "caching"}
```

#### `SEMANTIC_CRITICAL_SIGNALS` — add both (line ~256)

Add `"concurrency"` and `"caching"` to the set. Final set (keep alphabetical):
```python
SEMANTIC_CRITICAL_SIGNALS = {
    "auth_guard",
    "caching",
    "concurrency",
    "database_io",
    "external_io",
    "filesystem_io",
    "input_boundary",
    "network_io",
    "orm_dynamic_load",
    "output_boundary",
    "process_io",
    "state_mutation",
    "validation_guard",
    "dynamic_dispatch",
}
```

#### `BEHAVIORAL_FLOW_STEP_ORDER` — add both (line ~270)

Add at the end, before the closing `}`:
```python
    "concurrency": 6,
    "caching": 7,
```

`concurrency` shares position 6 with `state_mutation` (concurrent mutation overlaps with plain
mutation). `caching` shares position 7 with `database_io` (a cache is a DB substitute).

---

### 2. Version Bump (line 737)

```python
"version": "3.57",
```

---

### 3. `_extract_python_semantic_spans` — add two blocks (line ~5106)

Insert **before** the `if "frappe" in self.active_plugins` block (i.e., before line 5112),
after the existing `error_handling` / `guard_signal_for_window` logic:

```python
            if (
                re.search(r"\bthreading\.(?:Thread|Lock|RLock|Event|Semaphore|Condition|Barrier)\b", text)
                or re.search(r"\bconcurrent\.futures\.(?:ThreadPoolExecutor|ProcessPoolExecutor|as_completed|wait)\b", text)
                or re.search(r"\bmultiprocessing\.(?:Process|Pool|Queue|Pipe|Lock|Manager)\b", text)
                or re.search(r"\basyncio\.(?:create_task|gather|wait|wait_for|Lock|Semaphore|Queue|Event|Barrier|TaskGroup)\s*[\(\[]", text)
                or re.search(r"\bqueue\.(?:Queue|SimpleQueue|LifoQueue|PriorityQueue)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                         "Spawns threads, coroutines, or uses Python concurrency primitives.")
            if (
                re.search(r"@(?:functools\.)?(?:lru_cache|cache)\b", text)
                or re.search(r"\bfunctools\.lru_cache\s*\(", text)
                or re.search(r"\bredis(?:\.asyncio)?\.(?:Redis|StrictRedis)\s*\(", text)
                or re.search(r"\bcachetools\.(?:cached|LRUCache|TTLCache|LFUCache|MRUCache|RRCache)\b", text)
                or re.search(r"\bdiskcache\.Cache\s*\(", text)
                or re.search(r"\bcache\.(?:get|set|delete|add|incr|decr|get_many|set_many)\s*\(", text)
                or re.search(r"\bdjango\.core\.cache\b", text)
            ):
                self._record_semantic_ref(refs, node, "caching", lineno, lineno,
                                         "Uses an in-memory or distributed cache.")
```

---

### 4. `_extract_java_semantic_spans` — reclassify + add (line ~5125)

**4a — Reclassify `@Cacheable` from `state_mutation` → `caching`.**

Find the existing block (around line 5194):
```python
            if re.search(r"@(?:Cacheable|CacheEvict|CachePut|Caching)\b", text):
                self._record_semantic_ref(
                    refs, node, "state_mutation", lineno, lineno,
                    "Spring cache annotation reads or mutates a shared cache store.",
                )
```
Change `"state_mutation"` to `"caching"` and update the reason:
```python
            if re.search(r"@(?:Cacheable|CacheEvict|CachePut|Caching)\b", text):
                self._record_semantic_ref(
                    refs, node, "caching", lineno, lineno,
                    "Spring cache annotation reads or writes a shared cache store.",
                )
```

**4b — Add `concurrency` block** before `guard = self._guard_signal_for_window(...)`:
```python
            if (
                re.search(r"\bnew Thread\s*\(", text)
                or re.search(r"\bExecutors?\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bCompletableFuture\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bForkJoinPool\b", text)
                or re.search(r"\bCountDownLatch\b|\bCyclicBarrier\b|\bPhaser\b", text)
                or re.search(r"\bReentrantLock\b|\bReentrantReadWriteLock\b|\bStampedLock\b", text)
                or re.search(r"\bsynchronized\s*\(", text)
                or re.search(r"\bAtomicInteger\b|\bAtomicLong\b|\bAtomicReference\b|\bAtomicBoolean\b", text)
                or re.search(r"\bBlockingQueue\b|\bLinkedBlockingQueue\b|\bArrayBlockingQueue\b", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                         "Uses Java threading or concurrency primitives.")
```

---

### 5. `_extract_js_like_semantic_spans` — add two blocks (line ~5210)

Add before `guard = self._guard_signal_for_window(...)`:
```python
            if (
                re.search(r"\bnew Worker\s*\(", text)
                or re.search(r"\bSharedArrayBuffer\b", text)
                or re.search(r"\bAtomics\.", text)
                or re.search(r"\bPromise\.(?:all|race|allSettled|any)\s*\(", text)
                or re.search(r"\bworker_threads\b", text)
                or re.search(r"\bcluster\.fork\s*\(", text)
                or re.search(r"\bnew (?:MessageChannel|BroadcastChannel)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                         "Uses workers, parallel Promise composition, or shared-memory primitives.")
            if (
                re.search(r"\blru[-_]cache\b|\bLRUCache\s*\(|\bnew LRU\s*\(", text, re.IGNORECASE)
                or re.search(r"\bnew NodeCache\s*\(", text)
                or re.search(r"\bunstable_cache\s*\(", text)
                or re.search(r"\buseMemo\s*\(|\buseCallback\s*\(|\bReact\.memo\s*\(", text)
                or re.search(r"\bredis\.(?:get|set|setex|getset|mget|mset|del|expire|exists)\s*\(", lower)
            ):
                self._record_semantic_ref(refs, node, "caching", lineno, lineno,
                                         "Uses a cache (LRU, Redis client, React memo, or Next.js unstable_cache).")
```

---

### 6. `_extract_go_semantic_spans` — add two blocks (line ~5287)

Add before `return refs`:
```python
            if (
                re.search(r"\bgo\s+[A-Za-z_]", text)
                or re.search(r"\bmake\s*\(\s*chan\b", text)
                or re.search(r"\bsync\.(?:Mutex|RWMutex|WaitGroup|Once|Map|Cond)\b", text)
                or re.search(r"\batomic\.(?:Add|Load|Store|Swap|CompareAndSwap)\b", text)
                or re.search(r"\bsync/atomic\b", text)
                or re.search(r"\bselect\s*\{", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                         "Spawns a goroutine or uses Go concurrency primitives.")
            if (
                re.search(r"\bbigcache\.New(?:BigCache)?\s*\(", text)
                or re.search(r"\bfreecache\.NewCache\s*\(", text)
                or re.search(r"\bristretto\.NewCache\s*\(", text)
                or re.search(r"\bgocache\.New\s*\(", text)
                or re.search(r"\bgroupcache\.NewGroup\s*\(", text)
                or re.search(r"\bsync\.Pool\s*\{", text)
            ):
                self._record_semantic_ref(refs, node, "caching", lineno, lineno,
                                         "Uses a Go in-process or distributed cache.")
```

---

### 7. `_extract_rust_semantic_spans` — add two blocks (line ~5364)

Add before `guard = self._guard_signal_for_window(...)`:
```python
            if (
                re.search(r"\bthread::spawn\s*\(", text)
                or re.search(r"\bArc::new\s*\(", text)
                or re.search(r"\bMutex::new\s*\(|\bRwLock::new\s*\(", text)
                or re.search(r"\bmpsc::(?:channel|sync_channel)\s*\(", text)
                or re.search(r"\btokio::spawn\s*\(", text)
                or re.search(r"\bsmol::spawn\s*\(|\basync_std::task::spawn\s*\(", text)
                or re.search(r"\brayon::(?:spawn|scope|join)\s*\(", text)
                or re.search(r"\bcrossbeam(?:_channel)?::\b", text)
                or re.search(r"\bAtomicUsize\b|\bAtomicBool\b|\bAtomicI32\b|\bAtomicU64\b", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                         "Spawns threads or uses Rust concurrency primitives.")
            if (
                re.search(r"\bmoka::(?:Cache|future::Cache)\b", text)
                or re.search(r"\b#\[cached\]\b", text)
                or re.search(r"\bonce_cell::sync::", text)
                or re.search(r"\blazy_static!\b", text)
                or re.search(r"\bstd::sync::(?:OnceLock|LazyLock)\b", text)
                or re.search(r"\blru::LruCache\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "caching", lineno, lineno,
                                         "Uses a Rust cache crate or lazy-initialised global.")
```

---

### 8. `_extract_csharp_semantic_spans` — add two blocks (line ~5448)

Add before `guard = self._guard_signal_for_window(...)`:
```python
            if (
                re.search(r"\bnew Thread\s*\(", text)
                or re.search(r"\bTask\.(?:Run|Factory\.StartNew|WhenAll|WhenAny|Delay)\s*\(", text)
                or re.search(r"\bParallel\.(?:For|ForEach|Invoke)\s*\(", text)
                or re.search(r"\bCancellationToken(?:Source)?\b", text)
                or re.search(r"\bSemaphoreSlim\b|\bMutex\b", text)
                or re.search(r"\bMonitor\.(?:Enter|Exit|Wait|Pulse)\b", text)
                or re.search(r"\bChannel\.Create(?:Unbounded|Bounded)\s*\(", text)
                or re.search(r"\bThreadPool\.QueueUserWorkItem\s*\(", text)
                or re.search(r"\bInterlocked\.(?:Add|Increment|Decrement|Exchange|CompareExchange)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                         "Uses C# threading or async concurrency primitives.")
            if (
                re.search(r"\bIMemoryCache\b|\bIDistributedCache\b", text)
                or re.search(r"\bcache\.(?:Get|Set|TryGetValue|GetOrCreate|GetOrCreateAsync|Remove)\s*\(", text)
                or re.search(r"\bMemoryCache\b|\bDistributedCache\b", text)
                or re.search(r"\[ResponseCache\b", text)
                or re.search(r"\bOutputCache(?:Attribute)?\b", text)
            ):
                self._record_semantic_ref(refs, node, "caching", lineno, lineno,
                                         "Uses ASP.NET Core memory or distributed caching.")
```

---

### 9. `_extract_kotlin_semantic_spans` — reclassify two existing blocks + add one (line ~5529)

**9a — Change coroutine builders from `process_io` → `concurrency`.**

Find (around line 5580):
```python
            if re.search(
                r"\b(?:launch|async|runBlocking|withContext|GlobalScope\.launch|"
                r"CoroutineScope|supervisorScope|coroutineScope)\s*[{\(]",
                text,
            ):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno,
                                         "Coroutine builder creates a concurrent execution context.")
```
Change the signal from `"process_io"` to `"concurrency"` and extend the pattern:
```python
            if (
                re.search(
                    r"\b(?:launch|async|runBlocking|withContext|GlobalScope\.launch|"
                    r"CoroutineScope|supervisorScope|coroutineScope)\s*[{\(]",
                    text,
                )
                or re.search(r"\bMutex\(\)|\bSemaphore\(\)", text)
                or re.search(r"\bChannel<", text)
                or re.search(r"\bnew Thread\s*\(|\bExecutors?\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bStateFlow\b|\bSharedFlow\b|\bMutableStateFlow\b", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                         "Coroutine builder or concurrency primitive creates a concurrent execution context.")
```

**9b — Change `@Cacheable` from `state_mutation` → `caching` and extend.**

Find (around line 5613):
```python
            if re.search(r"@(?:Cacheable|CacheEvict|CachePut|Caching)\b", text):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Spring cache annotation mutates a shared cache store.")
```
Replace with:
```python
            if (
                re.search(r"@(?:Cacheable|CacheEvict|CachePut|Caching)\b", text)
                or re.search(r"\bCaffeineCache\b|\bEhcache\b", text)
                or re.search(r"\bcache\.(?:get|put|evict|putIfAbsent)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "caching", lineno, lineno,
                                         "Spring cache annotation or cache API reads or writes a shared cache store.")
```

---

### 10. `_extract_php_semantic_spans` — split existing block + add (line ~5633)

**10a — Split the `$_SESSION` / `Cache::` block.**

Find (around line 5714):
```python
            if (
                re.search(r"\$_SESSION\b", text)
                or re.search(r"\bCache::(?:put|forget|forever|remember)\s*\(", text)
                or re.search(r"\bcache\s*\(\s*\)->(?:put|forget|remember)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno,
                                          "Mutates session or cache state.")
```
Replace with two separate blocks:
```python
            if re.search(r"\$_SESSION\b", text):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno,
                                          "Mutates PHP session state.")
            if (
                re.search(r"\bCache::(?:get|put|forget|forever|remember|has|pull|flush|tags)\s*\(", text)
                or re.search(r"\bcache\s*\(\s*\)->(?:get|put|forget|remember)\s*\(", text)
                or re.search(r"\bRedis::(?:get|set|setex|expire|del)\s*\(", text)
                or re.search(r"\bnew Memcached\s*\(|\$memcache->(?:get|set|delete)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "caching", lineno, lineno,
                                          "Reads or writes a Laravel/Redis/Memcached cache.")
```

**10b — Add `concurrency` block** before `guard = self._guard_signal_for_window(...)`:
```python
            if (
                re.search(r"\\parallel\\(?:Runtime|Channel|Future)\b", text)
                or re.search(r"\bpcntl_fork\s*\(", text)
                or re.search(r"\bQueue::(?:push|bulk|later)\s*\(", text)
                or re.search(r"\bdispatch(?:Now)?\s*\(\s*new\s+", text)
                or re.search(r"\bReact\\EventLoop\b", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                         "Dispatches async jobs or uses PHP concurrency extension.")
```

---

### 11. `_extract_ruby_semantic_spans` — split existing block + add (line ~5738)

**11a — Split the `Rails.cache.` / `session[` block.**

Find (around line 5835):
```python
            if (
                re.search(r"\bRails\.cache\.(?:write|fetch|delete)\s*\(", text)
                or re.search(r"\bsession\s*\[", text)
            ):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno,
                                          "Mutates Rails cache or session state.")
```
Replace with two separate blocks:
```python
            if re.search(r"\bsession\s*\[", text):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno,
                                          "Mutates Rails session state.")
            if (
                re.search(r"\bRails\.cache\.(?:write|fetch|delete|read|exist\?|clear)\s*\(", text)
                or re.search(r"\bRedis\.new\b|\bRedis::Client\b", text)
                or re.search(r"\bDalli::Client\b", text)
                or re.search(r"\bmemoize\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "caching", lineno, lineno,
                                          "Reads or writes a Rails/Redis/Memcached cache.")
```

**11b — Add `concurrency` block** before `guard = self._guard_signal_for_window(...)`:
```python
            if (
                re.search(r"\bThread\.(?:new|start)\s*[\{\(]", text)
                or re.search(r"\bMutex\.new\b|\.synchronize\s*\{", text)
                or re.search(r"\bQueue\.new\b", text)
                or re.search(r"\bConcurrent::(?:Future|Promise|IVar|Actor|ThreadPoolExecutor)\b", text)
                or re.search(r"\bperform_async\s*\(|\bperform_later\s*\(", text)
                or re.search(r"\bSidekiq::Worker\b|\bResque::Job\b", text)
            ):
                self._record_semantic_ref(refs, node, "concurrency", lineno, lineno,
                                         "Spawns threads or delegates work to a background-job framework.")
```

---

## Worker B Tasks

### 1. Update `CHANGES.md`

Add after the Sprint 26 section:

```markdown
## Sprint 27 — New Semantic Signals: `concurrency` + `caching` (v3.57)

- New signal `concurrency` (weight 2.6) — fires on thread/goroutine/coroutine spawning,
  locks, channels, atomic ops, and executor submission across all 9 languages
- New signal `caching` (weight 1.8) — fires on Redis/Memcached clients, LRU caches,
  framework annotations (`@Cacheable`, `Rails.cache`, Laravel `Cache::`) across all 9 languages
- Both signals added to `SEMANTIC_CRITICAL_SIGNALS`; `concurrency` to
  `SEMANTIC_SIDE_EFFECT_SIGNALS`, `caching` to `SEMANTIC_EXTERNAL_IO_SIGNALS`
- Reclassifications: Java/Kotlin `@Cacheable` `state_mutation` → `caching`; Kotlin
  coroutine builders `process_io` → `concurrency`; PHP `Cache::` / Ruby `Rails.cache.`
  `state_mutation` → `caching`
```

### 2. Update `WORKER_GUIDE.md`

Find:
```
- Sprint history: 29 passes (Runs 1–3 autonomous, Sprints 1–26)
```
Replace with:
```
- Sprint history: 30 passes (Runs 1–3 autonomous, Sprints 1–27)
```

Update any version references `3.56` → `3.57`.

### 3. Update `README.md`

**Semantic signals count** — find `"16 behavioral categories"` → `"18 behavioral categories"`.

**Semantic signals block** — add `concurrency` and `caching`:
```
network_io       database_io      filesystem_io    process_io
config_access    input_boundary   output_boundary  validation_guard
auth_guard       error_handling   serialization    deserialization
state_mutation   time_or_randomness  dynamic_dispatch  orm_dynamic_load
concurrency      caching
```

**Development History table** — add:
```
| Sprint 27 | New semantic signals: `concurrency` + `caching` (all 9 languages) |
```

**Passes line** — update:
```
SIA was developed in **30 passes** (3 autonomous runs + 27 directed sprints)
```

---

## Validation Checklist (Brain)

After workers submit, Brain verifies:

1. `"concurrency": 2.6` and `"caching": 1.8` in `SEMANTIC_SIGNAL_WEIGHTS`.
2. `"concurrency"` in `SEMANTIC_SIDE_EFFECT_SIGNALS` and `SEMANTIC_CRITICAL_SIGNALS`.
3. `"caching"` in `SEMANTIC_EXTERNAL_IO_SIGNALS` and `SEMANTIC_CRITICAL_SIGNALS`.
4. `"concurrency": 6` and `"caching": 7` in `BEHAVIORAL_FLOW_STEP_ORDER`.
5. `meta.version == "3.57"` at line 737.
6. Python extractor emits `concurrency` on `asyncio.create_task(` and `caching` on
   `@lru_cache`.
7. Java extractor emits `caching` (not `state_mutation`) on `@Cacheable`.
8. Kotlin extractor emits `concurrency` (not `process_io`) on `launch {`.
9. PHP extractor emits `caching` on `Cache::put(` and `state_mutation` on `$_SESSION`.
10. Ruby extractor emits `caching` on `Rails.cache.fetch(` and `state_mutation` on `session[`.
11. `CHANGES.md` has a Sprint 27 entry.
12. `WORKER_GUIDE.md` says "30 passes".
13. `README.md` says "18 behavioral categories" and lists `concurrency` and `caching`.

---

## What Does NOT Change

- No new edge kinds.
- No CLI flags changed.
- Frappe plugin behavior unchanged.
- String-ref resolution unchanged.
- All existing signals other than the five reclassifications remain exactly as before.
- `.frappe_fixture/` and `.polyglot_graph_fixture/` unchanged.
