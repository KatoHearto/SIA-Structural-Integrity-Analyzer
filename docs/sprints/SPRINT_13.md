# Sprint 13 Briefing

Read `WORKER_GUIDE.md` first if you haven't already. This file contains your tasks for Sprint 13.

**Goal:** Fix asymmetric framework coverage — Sprint 11 added Gin/Echo/Fiber `input_boundary`
but never updated `output_boundary`; expand shallow `network_io` patterns in Go, Python, and
Rust; update docs.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — Expand Go `output_boundary` to cover Gin / Echo / Fiber responses

**Where:** `_extract_go_semantic_spans`. The existing `output_boundary` check (currently
~line 3997) only covers bare `net/http` patterns. Sprint 11 added Gin/Echo/Fiber context
types to `input_boundary` but left `output_boundary` untouched — meaning requests are detected
but responses are not.

Replace the existing single-line block:

```python
            if re.search(r"\b(?:w\.Write|w\.WriteHeader|json\.NewEncoder\s*\(\s*w\s*\)\.Encode|http\.(?:Error|Redirect|ServeFile|ServeContent))\s*\(", text):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Writes an HTTP response from Go code.")
```

With:

```python
            if (
                re.search(r"\b(?:w\.Write|w\.WriteHeader|json\.NewEncoder\s*\(\s*w\s*\)\.Encode|http\.(?:Error|Redirect|ServeFile|ServeContent))\s*\(", text)
                or re.search(r"\bc\.(?:JSON|String|HTML|XML|File|Redirect|Status|Send|SendString|SendStatus|NoContent|Render|Blob|Attachment|AbortWithStatus(?:JSON)?|IndentedJSON|PureJSON|JSONP)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Writes an HTTP response from Go code.")
```

---

### Task A2 — Expand Go `network_io` detection

**Where:** `_extract_go_semantic_spans`. The existing check (currently ~line 3952) only covers
`http.Get`, `http.Post`, and `client.Do`. `http.NewRequest` (the idiomatic low-level form),
`resty` (the most popular third-party Go HTTP client), and `grpc.Dial` (gRPC) are all undetected.

Replace the existing single-line block:

```python
            if re.search(r"\b(?:http\.(?:Get|Post)|client\.Do)\s*\(", text):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a Go HTTP client.")
```

With:

```python
            if (
                re.search(r"\bhttp\.(?:Get|Post|Head|PostForm|NewRequest)\s*\(", text)
                or re.search(r"\bclient\.(?:Do|Get|Post|Head)\s*\(", text)
                or re.search(r"\bresty\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bgrpc\.(?:Dial|NewClient)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a Go HTTP or gRPC client.")
```

---

### Task A3 — Expand Python `network_io` to cover boto3 and cloud SDKs

**Where:** `_extract_python_semantic_spans`. The existing check (currently ~line 3756) only
covers `requests`, `httpx`, `urllib`, and `aiohttp`. `boto3` (AWS SDK) is used in the majority
of Python backend services and is entirely undetected; gRPC Python stubs and Google Cloud
client libraries are also missed.

Replace the existing single-line block:

```python
            if re.search(r"\b(?:requests|httpx|urllib(?:\.request)?|aiohttp\.ClientSession)\.[A-Za-z_]\w*\s*\(", text):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a Python HTTP client.")
```

With:

```python
            if (
                re.search(r"\b(?:requests|httpx|urllib(?:\.request)?|aiohttp\.ClientSession)\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bboto3\.(?:client|resource|Session)\s*\(", text)
                or re.search(r"\bbotocore\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bgrpc\.(?:insecure_channel|secure_channel)\s*\(", text)
                or re.search(r"\bgoogle\.cloud\.", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a Python HTTP or cloud client.")
```

---

### Task A4 — Expand Rust `network_io` to cover hyper, surf, ureq, tonic

**Where:** `_extract_rust_semantic_spans`. The existing check (currently ~line 4014) only covers
`reqwest::` and `client.execute`. `hyper` (the HTTP primitive beneath reqwest), `surf` (async
HTTP), `ureq` (blocking), and `tonic` (gRPC) are all common Rust networking crates.

Replace the existing single-line block:

```python
            if re.search(r"\b(?:reqwest::|client\.execute)\b", text):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a Rust HTTP client.")
```

With:

```python
            if (
                re.search(r"\breqwest::\b", text)
                or re.search(r"\bclient\.(?:execute|get|post|put|delete|head|request)\s*\(", text)
                or re.search(r"\bhyper::\b", text)
                or re.search(r"\bsurf::\b", text)
                or re.search(r"\bureq::\b", text)
                or re.search(r"\btonic::\b", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a Rust HTTP or gRPC client.")
```

---

### Verification for Worker A

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n "IndentedJSON\|AbortWithStatus\|SendStatus" god_mode_v3.py` — confirm Go
   `output_boundary` expansion in `_extract_go_semantic_spans`.
3. `rg -n "NewRequest\|resty\.\|grpc\.Dial" god_mode_v3.py` — confirm Go `network_io`
   expansion.
4. `rg -n "boto3\.\|botocore\.\|google\.cloud" god_mode_v3.py` — confirm Python `network_io`
   expansion.
5. `rg -n "hyper::\|surf::\|ureq::\|tonic::" god_mode_v3.py` — confirm Rust `network_io`
   expansion.
6. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — `parse_errors=0`.

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–11576, plus project docs

### Task B1 — Add Sprint 12 entry to `CHANGES.md`

Append to the end of `CHANGES.md`:

```markdown
---

## Sprint 12 — config_access + NestJS + Java database_io Improvements (v3.42)

### Change 1 — Go `config_access` expansion
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3960 |
| **Category** | Feature |

Viper (`viper.Get*`), godotenv (`godotenv.Load/Overload/Read`), envconfig
(`envconfig.Process`), and `os.LookupEnv` added alongside the existing `os.Getenv` pattern.
Viper is the dominant Go config library and was entirely undetected.

### Change 2 — Rust `config_access` expansion
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4020 |
| **Category** | Feature |

`dotenv::dotenv`, `envy::from_env/prefixed`, `config::Config`, `figment::Figment`, and
`std::env::var_os` added alongside the existing `std::env::var` pattern.

### Change 3 — NestJS `input_boundary` decorators in JS/TS extractor
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3910 |
| **Category** | Feature |

NestJS route decorators (`@Get`, `@Post`, `@Put`, `@Delete`, `@Patch`) and parameter
decorators (`@Body`, `@Param`, `@Query`, `@Headers`, `@Req`, `@Res`, `@UploadedFile`) are
now detected as `input_boundary` signals.

### Change 4 — Java `database_io` annotation-based detection
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3872 |
| **Category** | Feature |

`@Transactional`, `@Query`, `@Modifying`, `@NamedQuery`, and `@NativeQuery` annotations
now trigger `database_io` directly, independent of the `member_types` resolution path.

### Change 5 — Java `config_access` expansion
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3848 |
| **Category** | Feature |

`@ConfigurationProperties` and Spring `env.getProperty(...)` added alongside the existing
`System.getenv`, `System.getProperty`, and `@Value` patterns.
```

---

### Task B2 — Update `WORKER_GUIDE.md`

In the "Current state" section:
1. Version line → `**3.43**`
2. Sprint history line → `- Sprint history: 14 passes (Runs 1–3 autonomous, Sprints 1–12)`

---

### Task B3 — Bump version to 3.43

**Where:** Line ~672

```python
                "version": "3.43",
```

Indentation: exactly 16 spaces.

---

### Verification for Worker B

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n '"version"' god_mode_v3.py` — confirm `3.43` at line ~672 with 16-space indent.
3. Check `CHANGES.md` ends with the Sprint 12 section.
4. `rg -n "3\.43\|Sprints 1.12" WORKER_GUIDE.md` — confirm both updated.

---

## Handoff

- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`

Format: see `WORKER_GUIDE.md` → "Output file format" section.
