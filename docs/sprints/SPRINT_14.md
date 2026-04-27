# Sprint 14 Briefing

Read `WORKER_GUIDE.md` first if you haven't already. This file contains your tasks for Sprint 14.

**Goal:** Close all remaining pattern gaps before real-project testing. All 14 signals are
structurally present in all 5 extractors; this sprint expands the patterns within those signals
to cover missing frameworks and stdlib calls that produce false-negatives on real codebases.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — Java `input_boundary`: add `@RequestBody` + `@PathVariable`

**Where:** `_extract_java_semantic_spans`, currently line 3840.

Replace:
```python
            if re.search(r"@(?:RestController|Controller|RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestParam)\b", text):
```
With:
```python
            if re.search(r"@(?:RestController|Controller|RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestParam|RequestBody|PathVariable)\b", text):
```

---

### Task A2 — Java `network_io`: add Apache HttpClient

**Where:** `_extract_java_semantic_spans`, currently line 3848.

Replace:
```python
            if re.search(r"\b(?:RestTemplate|WebClient|HttpClient|OkHttpClient|Feign)\b", text):
```
With:
```python
            if re.search(r"\b(?:RestTemplate|WebClient|HttpClient|OkHttpClient|Feign|CloseableHttpClient|HttpGet|HttpPost|HttpPut|HttpDelete|HttpPatch)\b", text):
```

---

### Task A3 — Java `auth_guard`: add SecurityContextHolder + programmatic checks

**Where:** `_extract_java_semantic_spans`, currently line 3842.

Replace:
```python
            if re.search(r"@(?:PreAuthorize|RolesAllowed|Secured)\b", text):
```
With:
```python
            if (
                re.search(r"@(?:PreAuthorize|RolesAllowed|Secured)\b", text)
                or re.search(r"\bSecurityContextHolder\.getContext\(\)", text)
                or re.search(r"\bauthenticationManager\.authenticate\s*\(", text)
                or re.search(r"\bjwtService\.(?:validate|verify|parseToken|extractUsername)\s*\(", text)
            ):
```

---

### Task A4 — Go `database_io`: add pgx / pgxpool

**Where:** `_extract_go_semantic_spans`, currently line 3965.

Replace:
```python
            if re.search(r"\b(?:db\.(?:Query|Exec)|sql\.Open)\s*\(", text) or re.search(r"\bdb\.(?:Where|Find|First|Last|Create|Save|Delete|Update|Updates|Preload|Joins)\s*\(", text):
```
With:
```python
            if (
                re.search(r"\b(?:db\.(?:Query|Exec)|sql\.Open)\s*\(", text)
                or re.search(r"\bdb\.(?:Where|Find|First|Last|Create|Save|Delete|Update|Updates|Preload|Joins)\s*\(", text)
                or re.search(r"\bpgx(?:pool)?\.(?:New|Connect)\s*\(", text)
                or re.search(r"\b(?:pool|conn)\.(?:QueryRow|Query|Exec|Begin|SendBatch)\s*\(", text)
            ):
```

---

### Task A5 — Go `filesystem_io`: add `os.ReadFile` + bufio

**Where:** `_extract_go_semantic_spans`, currently line 3967.

Replace:
```python
            if re.search(r"\b(?:os\.Open|os\.Create|os\.WriteFile|ioutil\.ReadFile)\s*\(", text):
```
With:
```python
            if re.search(r"\b(?:os\.Open|os\.Create|os\.WriteFile|os\.ReadFile|ioutil\.ReadFile|bufio\.New(?:Reader|Writer|Scanner))\s*\(", text):
```

---

### Task A6 — JS/TS `database_io`: add Drizzle ORM

**Where:** `_extract_js_like_semantic_spans`, currently lines 3923–3929.

Replace:
```python
            if (
                re.search(r"\bprisma\.[A-Za-z_]\w*\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\b(?:mongoose|Model)\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\b(?:getRepository|getConnection|createQueryBuilder)\s*\(", text)
                or re.search(r"\bknex\s*\(", text)
                or re.search(r"\b(?:pool|client|db)\.(?:query|execute|connect)\s*\(", text)
            ):
```
With:
```python
            if (
                re.search(r"\bprisma\.[A-Za-z_]\w*\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\b(?:mongoose|Model)\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\b(?:getRepository|getConnection|createQueryBuilder)\s*\(", text)
                or re.search(r"\bknex\s*\(", text)
                or re.search(r"\b(?:pool|client|db)\.(?:query|execute|connect)\s*\(", text)
                or re.search(r"\bdrizzle\s*\(", text)
                or re.search(r"\bdb\.(?:select|insert|update|delete)\s*\(\s*\)", text)
            ):
```

---

### Task A7 — JS/TS `auth_guard`: add bcrypt + argon2

**Where:** `_extract_js_like_semantic_spans`, currently lines 3931–3935.

Replace:
```python
            if (
                re.search(r"\bjwt\.(?:verify|decode|sign)\s*\(", text)
                or re.search(r"\bpassport\.(?:authenticate|authorize)\s*\(", text)
                or re.search(r"\b(?:verifyToken|checkAuth|requireAuth|isAuthenticated|ensureLoggedIn)\s*\(", text)
            ):
```
With:
```python
            if (
                re.search(r"\bjwt\.(?:verify|decode|sign)\s*\(", text)
                or re.search(r"\bpassport\.(?:authenticate|authorize)\s*\(", text)
                or re.search(r"\b(?:verifyToken|checkAuth|requireAuth|isAuthenticated|ensureLoggedIn)\s*\(", text)
                or re.search(r"\bbcrypt\.(?:hash|compare|hashSync|compareSync)\s*\(", text)
                or re.search(r"\bargon2\.(?:hash|verify)\s*\(", text)
            ):
```

---

### Verification for Worker A

```bash
python -m py_compile god_mode_v3.py
```
No output = pass.

```bash
rg -n "RequestBody|PathVariable" god_mode_v3.py
rg -n "CloseableHttpClient" god_mode_v3.py
rg -n "SecurityContextHolder" god_mode_v3.py
rg -n "pgxpool" god_mode_v3.py
rg -n "os\.ReadFile|bufio\.New" god_mode_v3.py
rg -n "drizzle" god_mode_v3.py
rg -n "bcrypt|argon2" god_mode_v3.py
```

```bash
python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only
```
Expected: `parse_errors=0`

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–end, plus project docs

### Task B1 — Rust `filesystem_io`: add `tokio::fs` + `async_std::fs`

**Where:** `_extract_rust_semantic_spans`, currently line 4037.

Replace:
```python
            if re.search(r"\b(?:std::fs::|File::(?:open|create))\b", text):
```
With:
```python
            if re.search(r"\b(?:std::fs::|tokio::fs::|async_std::fs::|File::(?:open|create))\b", text):
```

---

### Task B2 — Rust `database_io`: add sea_orm + rusqlite

**Where:** `_extract_rust_semantic_spans`, currently line 4053.

Replace:
```python
            if re.search(r"\b(?:diesel::|sqlx::|tokio_postgres::)\b", text) or re.search(r"\.(?:execute|query|query_as|fetch_one|fetch_all|fetch_optional)\s*\(", text):
```
With:
```python
            if (
                re.search(r"\b(?:diesel::|sqlx::|tokio_postgres::|sea_orm::|rusqlite::)\b", text)
                or re.search(r"\.(?:execute|query|query_as|fetch_one|fetch_all|fetch_optional)\s*\(", text)
                or re.search(r"\bEntityTrait::[A-Za-z_]\w*\s*\(", text)
            ):
```

---

### Task B3 — Bump version to 3.44

**Where:** Line 672.

```python
                "version": "3.44",
```
Indentation: exactly 16 spaces.

---

### Task B4 — Append Sprint 13 + Sprint 14 entries to `CHANGES.md`

Sprint 13 was never documented (Worker B in that sprint only wrote a Sprint 12 entry). Append both blocks in order:

```markdown
## Sprint 13 — network_io Depth + Go output_boundary Framework Coverage (v3.43)

### Change 1 — Go `output_boundary`: Gin / Echo / Fiber response helpers
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4008 |
| **Category** | Feature |

Gin (`c.JSON`, `c.String`, `c.HTML`, `c.Redirect`, `c.AbortWithStatusJSON`, `c.IndentedJSON`,
`c.PureJSON`, `c.JSONP`, etc.), Echo, and Fiber response helpers added alongside the existing
bare `net/http` patterns. Sprint 11 added these frameworks to `input_boundary` but left
`output_boundary` unmatched.

### Change 2 — Go `network_io`: `http.NewRequest`, resty, gRPC
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3958 |
| **Category** | Feature |

`http.NewRequest`, `client.Get/Post/Head`, `resty.*`, and `grpc.Dial/NewClient` added
alongside the previous `http.Get/Post` + `client.Do` patterns.

### Change 3 — Python `network_io`: boto3, botocore, gRPC, Google Cloud SDK
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3756 |
| **Category** | Feature |

`boto3.client/resource/Session`, `botocore.*`, `grpc.insecure_channel/secure_channel`,
and `google.cloud.*` added. The majority of Python cloud services use these clients and
were entirely undetected.

### Change 4 — Rust `network_io`: hyper, surf, ureq, tonic
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4028 |
| **Category** | Feature |

`hyper::`, `surf::`, `ureq::`, and `tonic::` added alongside the existing `reqwest::`
and `client.execute` patterns.

---

## Sprint 14 — Final Pattern Coverage Pass (v3.44)

### Change 1 — Java `input_boundary`: `@RequestBody` + `@PathVariable`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3840 |
| **Category** | Feature |

`@RequestBody` and `@PathVariable` added alongside existing Spring MVC annotations.
Both are ubiquitous in REST controllers but were previously undetected.

### Change 2 — Java `network_io`: Apache HttpClient
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3848 |
| **Category** | Feature |

`CloseableHttpClient`, `HttpGet`, `HttpPost`, `HttpPut`, `HttpDelete`, `HttpPatch` added
to the existing RestTemplate/WebClient/Feign pattern. Apache HttpClient is dominant in
enterprise Java codebases.

### Change 3 — Java `auth_guard`: SecurityContextHolder + programmatic checks
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3842 |
| **Category** | Feature |

`SecurityContextHolder.getContext()`, `authenticationManager.authenticate()`, and
`jwtService.validate/verify/parseToken/extractUsername()` added alongside annotation
guards. Spring Security code-level patterns were entirely undetected.

### Change 4 — Go `database_io`: pgx / pgxpool
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3965 |
| **Category** | Feature |

`pgxpool.New`, `pgxpool.Connect`, `pgx.Connect`, and `pool/conn.QueryRow/Query/Exec/Begin/SendBatch`
added. pgx is the most-used PostgreSQL driver in Go and was entirely undetected.

### Change 5 — Go `filesystem_io`: `os.ReadFile` + bufio
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3967 |
| **Category** | Feature |

`os.ReadFile` (stdlib since Go 1.16) and `bufio.NewReader/NewWriter/NewScanner` added
to the existing os.Open/Create/WriteFile pattern.

### Change 6 — JS/TS `database_io`: Drizzle ORM
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3923 |
| **Category** | Feature |

`drizzle()` constructor and `db.select()/insert()/update()/delete()` builder calls added
alongside Prisma/Mongoose/TypeORM/Knex. Drizzle is one of the fastest-growing TypeScript
ORMs and was completely invisible.

### Change 7 — JS/TS `auth_guard`: bcrypt + argon2
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3931 |
| **Category** | Feature |

`bcrypt.hash/compare/hashSync/compareSync` and `argon2.hash/verify` added to the
existing jwt/passport/verifyToken patterns. Password hashing/verification calls are
a core auth signal.

### Change 8 — Rust `filesystem_io`: `tokio::fs` + `async_std::fs`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4037 |
| **Category** | Feature |

`tokio::fs::` and `async_std::fs::` added alongside `std::fs::`. Async Rust filesystem
operations were entirely undetected.

### Change 9 — Rust `database_io`: sea_orm + rusqlite
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4053 |
| **Category** | Feature |

`sea_orm::`, `rusqlite::`, and `EntityTrait::*()` added to the existing
diesel/sqlx/tokio_postgres pattern. sea_orm is the dominant async Rust ORM.
```

---

### Task B5 — Update `WORKER_GUIDE.md` Current state

Replace the `## Current state` block with:

```markdown
## Current state

- Version: **3.44**
- Status: **complete** — all 14 semantic signals covered in all 5 language extractors; all known pattern gaps closed
- Sprint history: 16 passes (Runs 1–3 autonomous, Sprints 1–14)
- **Next step: real-project testing**
```

---

### Verification for Worker B

```bash
python -m py_compile god_mode_v3.py
rg -n '"version"' god_mode_v3.py
rg -n "tokio::fs" god_mode_v3.py
rg -n "sea_orm|rusqlite" god_mode_v3.py
```
`CHANGES.md` must end with the Sprint 14 section.
`WORKER_GUIDE.md` must show version 3.44 and 16 passes.

---

## Handoff

- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`

Format: see `WORKER_GUIDE.md` → "Output file format" section.

**This is the final sprint before real-project testing.**
