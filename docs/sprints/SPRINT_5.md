# Sprint 5 Briefing

Read `WORKER_GUIDE.md` first if you haven't already. This file contains your tasks for Sprint 5.

**Goal:** Fill the most significant semantic signal gaps in the Go, Rust, and JS/TS extractors. These are
the highest-impact analysis quality improvements — missing signals mean coworkers' codebase analyses
produce false-negative results for common patterns.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — Extend Go semantic extractor

**Where:** `_extract_go_semantic_spans`, starting at line ~3884. The current Go extractor is missing four
signals that common Go codebases exercise heavily.

Find the end of the existing `for lineno, text in source_lines:` loop body and append these four blocks
**inside the loop, before the `return refs` statement**:

**`output_boundary`** — Go HTTP handlers write responses via `http.ResponseWriter`:
```python
if re.search(r"\b(?:w\.Write|w\.WriteHeader|json\.NewEncoder\s*\(\s*w\s*\)\.Encode|http\.(?:Error|Redirect|ServeFile|ServeContent))\s*\(", text):
    self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Writes an HTTP response from Go code.")
```

**`serialization`** — `json.Marshal` and `json.MarshalIndent`:
```python
if re.search(r"\bjson\.Marshal(?:Indent)?\s*\(", text):
    self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes structured data in Go.")
```

**`deserialization`** — `json.Unmarshal` and `json.NewDecoder`:
```python
if re.search(r"\bjson\.(?:Unmarshal|NewDecoder)\s*\(", text):
    self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes structured data in Go.")
```

**`state_mutation`** — struct field assignments (`s.Field = …`):
```python
if re.search(r"\b[a-z]\w*\.[A-Za-z_]\w*\s*=(?!=)", text):
    self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates a struct field in Go.")
```

---

### Task A2 — Extend Rust semantic extractor

**Where:** `_extract_rust_semantic_spans`, starting at line ~3909. The Rust extractor is the thinnest of
all five — it is missing `error_handling`, `database_io`, `serialization`, `deserialization`, and
`state_mutation`.

Add these five blocks **inside the loop, before the `return refs` statement**:

**`error_handling`** — Rust's `?` operator, `.unwrap()`, `.expect()`, `match … Err`:
```python
if re.search(r"\.(?:unwrap|expect)\s*\(", text) or re.search(r"\?\s*(?:;|$)", text.rstrip()) or re.search(r"\bErr\s*\(", text):
    self._record_semantic_ref(refs, node, "error_handling", lineno, lineno, "Contains explicit Rust error handling.")
```

**`database_io`** — Diesel, SQLx, tokio-postgres:
```python
if re.search(r"\b(?:diesel::|sqlx::|tokio_postgres::)\b", text) or re.search(r"\.(?:execute|query|query_as|fetch_one|fetch_all|fetch_optional)\s*\(", text):
    self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Touches a Rust database client.")
```

**`serialization`** — `serde_json::to_string`, `serde_json::to_vec`, `to_string()` on serializable types:
```python
if re.search(r"\bserde_json::(?:to_string|to_vec|to_writer)\s*\(", text):
    self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes structured data in Rust.")
```

**`deserialization`** — `serde_json::from_str`, `serde_json::from_reader`:
```python
if re.search(r"\bserde_json::(?:from_str|from_reader|from_slice|from_value)\s*\(", text):
    self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes structured data in Rust.")
```

**`state_mutation`** — `self.field = …` assignments:
```python
if re.search(r"\bself\.[A-Za-z_]\w*\s*=(?!=)", text):
    self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates self state in Rust.")
```

---

### Verification for Worker A

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n "w\.WriteHeader\|json\.NewEncoder" god_mode_v3.py` — confirm Go `output_boundary` pattern present.
3. `rg -n "json\.Marshal\|json\.Unmarshal" god_mode_v3.py | grep -v "import\|#"` — confirm Go
   serialization patterns.
4. `rg -n "unwrap\|expect.*Rust\|serde_json" god_mode_v3.py` — confirm Rust additions present.
5. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — must complete with
   `parse_errors=0`.

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–11576, plus project docs

**Note:** Task B1 requires editing line ~3846, which is in Worker A's primary range. This is an
explicitly permitted cross-boundary edit — see `WORKER_GUIDE.md` "Domain split" note.

### Task B1 — Add `database_io` and `auth_guard` to the JS/TS semantic extractor

**Where:** `_extract_js_like_semantic_spans`, line ~3846. The JS/TS extractor has **no** `database_io`
detection at all, even though Prisma, Mongoose, TypeORM, and Knex are ubiquitous in Node.js/TypeScript
codebases. It also has no `auth_guard` detection.

Find the JS/TS extractor loop and add these two new blocks **inside the loop, before `guard =
self._guard_signal_for_window`**:

**`database_io`** — Prisma, Mongoose, TypeORM, Knex, pg/postgres:
```python
if (
    re.search(r"\bprisma\.[A-Za-z_]\w*\.[A-Za-z_]\w*\s*\(", text)
    or re.search(r"\b(?:mongoose|Model)\.[A-Za-z_]\w*\s*\(", text)
    or re.search(r"\b(?:getRepository|getConnection|createQueryBuilder)\s*\(", text)
    or re.search(r"\bknex\s*\(", text)
    or re.search(r"\b(?:pool|client|db)\.(?:query|execute|connect)\s*\(", text)
):
    self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Calls a JS/TS database client.")
```

**`auth_guard`** — JWT verification, Passport, session checks:
```python
if (
    re.search(r"\bjwt\.(?:verify|decode|sign)\s*\(", text)
    or re.search(r"\bpassport\.(?:authenticate|authorize)\s*\(", text)
    or re.search(r"\b(?:verifyToken|checkAuth|requireAuth|isAuthenticated|ensureLoggedIn)\s*\(", text)
):
    self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "Enforces authentication or token verification.")
```

---

### Task B2 — Add Sprint 4 entry to `CHANGES.md`

Append the following section to the end of `CHANGES.md`:

```markdown
---

## Sprint 4 — Analysis Quality Pass (v3.34)

### Change 1 — Extended Python `output_boundary` detection
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3778 |
| **Category** | Feature |

Extended `_extract_python_semantic_spans` `output_boundary` pattern from two names
(`jsonify`, `Response`) to twelve, covering FastAPI, Starlette, and Django response
constructors (`JSONResponse`, `HTMLResponse`, `StreamingResponse`, `FileResponse`,
`ORJSONResponse`, `RedirectResponse`, `PlainTextResponse`, `UJSONResponse`,
`HttpResponse`, `JsonResponse`, `HttpResponseRedirect`, `StreamingHttpResponse`).

### Change 2 — Added `abort(` and `redirect(` to guard action patterns
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~270 |
| **Category** | Feature |

Flask's `abort()` and Django/Flask's `redirect()` short-circuit the request path the
same way `raise` does. Added both to `SEMANTIC_GUARD_ACTION_PATTERNS` so guards using
these calls are correctly detected.

### Change 3 — Fixed `requirements.txt` (`gitpython` reference removed)
| | |
|---|---|
| **File** | `requirements.txt` |
| **Category** | Bug fix / Documentation |

The file incorrectly listed `gitpython` as an optional dependency. The git hotspot
feature (`_compute_git_hotspots`) uses `subprocess` to call the `git` CLI binary
directly — no Python package is needed. Replaced with a note about the `git` binary.
```

---

### Task B3 — Bump version to 3.35

**Where:** Line ~672

```python
                "version": "3.35",
```

Indentation: exactly 16 spaces.

---

### Verification for Worker B

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n '"version"' god_mode_v3.py` — confirm `3.35` at line ~672 with 16-space indent.
3. `rg -n "prisma\.\|mongoose\.\|jwt\.verify" god_mode_v3.py` — confirm JS/TS additions present in
   `_extract_js_like_semantic_spans`.
4. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — must complete with
   `parse_errors=0`.
5. Check `CHANGES.md` ends with the Sprint 4 section.

---

## Handoff

- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`

Format: see `WORKER_GUIDE.md` → "Output file format" section.
