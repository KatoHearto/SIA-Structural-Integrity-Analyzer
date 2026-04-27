# Sprint 7 Briefing

Read `WORKER_GUIDE.md` first if you haven't already. This file contains your tasks for Sprint 7.

**Goal:** Fill the last major semantic signal gaps — Python ORM/auth decorators, Go GORM, Rust boundary
signals, and JS/TS output_boundary.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — Extend Python `database_io` with Django ORM and asyncpg

**Where:** Lines ~3763–3767 in `_extract_python_semantic_spans`

**Current code:**
```python
if (
    re.search(r"\b(?:sqlite3|aiosqlite)\.connect\s*\(", text)
    or re.search(r"\b(?:cursor|session|db|conn|connection)\.(?:execute|query|commit|rollback|add|delete|merge|get)\s*\(", text)
):
    self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Touches a database or session API.")
```

Missing: Django ORM class-level queries (`Model.objects.*`) and asyncpg methods (`conn.fetch`,
`conn.fetchrow`). `.save()` and `.delete()` on Django model instances also go undetected.

**Required change:**
```python
if (
    re.search(r"\b(?:sqlite3|aiosqlite)\.connect\s*\(", text)
    or re.search(r"\b(?:cursor|session|db|conn|connection)\.(?:execute|query|commit|rollback|add|delete|merge|get)\s*\(", text)
    or re.search(r"\.objects\.(?:filter|get|create|update|delete|all|exclude|annotate|aggregate|bulk_create)\s*\(", text)
    or re.search(r"\bself\.[A-Za-z_]\w*\.(?:save|delete)\s*\(\s*\)", text)
    or re.search(r"\b(?:conn|connection)\.(?:fetch|fetchrow|fetchval|execute)\s*\(", text)
):
    self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Touches a database or session API.")
```

---

### Task A2 — Add decorator-based Python `auth_guard`

**Where:** Immediately before the `error_handling` block in `_extract_python_semantic_spans`
(currently line ~3787, the `stripped.startswith("try:")` line).

Python auth decorators like `@login_required`, `@jwt_required`, `@requires_auth` are guard signals
but are never caught by the guard-window check (which only fires on `if` statements). Add a direct
pattern:

```python
            if re.search(r"@(?:login_required|permission_required|jwt_required|token_required|requires_auth|authenticated|auth_required|requires_permission)\b", text):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "Auth/permission decorator guards this callable.")
```

---

### Task A3 — Add GORM patterns to Go `database_io`

**Where:** The `database_io` block inside `_extract_go_semantic_spans` (line ~3920, the
`db\.(?:Query|Exec)|sql\.Open` block).

GORM is the most common Go ORM. Its method chains (`db.Where(...).Find(...)`,
`db.First(...)`, `db.Create(...)`) are not caught by the current pattern.

Extend the existing block to also match GORM:
```python
            if re.search(r"\b(?:db\.(?:Query|Exec)|sql\.Open)\s*\(", text) or re.search(r"\bdb\.(?:Where|Find|First|Last|Create|Save|Delete|Update|Updates|Preload|Joins)\s*\(", text):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Touches a Go database handle.")
```

---

### Task A4 — Add `input_boundary`, `output_boundary`, and `auth_guard` to Rust extractor

**Where:** `_extract_rust_semantic_spans`, line ~3951. Currently the Rust extractor has no
boundary or auth signals at all.

Add these three blocks **inside the loop, after the existing `state_mutation` block, before
`return refs`**:

**`input_boundary`** — Actix-web route macros and parameter extractors:
```python
            if (
                re.search(r"#\[(?:get|post|put|delete|patch|head|options)\s*\(", text)
                or re.search(r"\b(?:web::Path|web::Json|web::Query|web::Form|HttpRequest)\b", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Declares a Rust HTTP input boundary.")
```

**`output_boundary`** — Actix-web response types:
```python
            if (
                re.search(r"\bHttpResponse::(?:Ok|Created|BadRequest|Unauthorized|Forbidden|NotFound|InternalServerError)\s*\(", text)
                or re.search(r"\bweb::Json\s*\(", text)
                or re.search(r"\bimpl\s+Responder\b", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Produces a Rust HTTP response.")
```

**`auth_guard`** — Bearer token extraction and JWT decode patterns:
```python
            if (
                re.search(r"\bbearer_token\b", text)
                or re.search(r"\bjwt::decode\s*::<", text)
                or re.search(r"Authorization.*Bearer\b", text)
                or re.search(r"\bIdentity::(?:identity|remember|forget)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "Enforces authentication in Rust code.")
```

---

### Verification for Worker A

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n "objects\.filter\|objects\.get\|objects\.create" god_mode_v3.py` — confirm Django ORM pattern.
3. `rg -n "login_required\|jwt_required\|auth_required" god_mode_v3.py` — confirm Python auth decorator pattern.
4. `rg -n "db\.Where\|db\.First\|db\.Create" god_mode_v3.py` — confirm GORM pattern in Go extractor.
5. `rg -n "HttpResponse::Ok\|web::Json\|impl Responder" god_mode_v3.py` — confirm Rust output_boundary.
6. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — `parse_errors=0`.

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–11576, plus project docs.

**Note:** Task B1 is a cross-boundary edit at line ~3876 — explicitly permitted.

### Task B1 — Extend JS/TS `output_boundary`

**Where:** `_extract_js_like_semantic_spans`, line ~3876

**Current code:**
```python
if re.search(r"\b(?:res\.(?:json|send|status)|NextResponse|Response\.json|new Response)\b", text):
    self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Produces boundary-facing output.")
```

Missing: Express `res.render(`, `res.sendFile(`, `res.download(`, `res.redirect(` — these all
produce HTTP output but are not caught.

**Required change:**
```python
if re.search(r"\b(?:res\.(?:json|send|status|render|sendFile|download|redirect)|NextResponse|Response\.json|new Response)\b", text):
    self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Produces boundary-facing output.")
```

---

### Task B2 — Add Sprint 6 entry to `CHANGES.md`

Append the following to the end of `CHANGES.md`:

```markdown
---

## Sprint 6 — Signal Depth Pass (v3.36)

### Change 1 — Python `input_boundary`: Django and FastAPI patterns
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3781 |
| **Category** | Feature |

Extended `_extract_python_semantic_spans` `input_boundary` detection to cover Django request
field access (`request.GET/POST/data/body/json/form/files/args`) and FastAPI dependency injection
parameter markers (`Body`, `Query`, `Path`, `Form`, `Header`, `Cookie`, `Depends`).

### Change 2 — Python `state_mutation`: collection mutations on `self`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3776 |
| **Category** | Feature |

Extended `state_mutation` to also detect subscript writes on self attributes
(`self.d[key] = ...`) and common mutating collection methods (`append`, `extend`,
`insert`, `update`, `setdefault`, `pop`, `remove`, `clear`, `add`, `discard`).

### Change 3 — Go extractor: `auth_guard` + guard-window enabled
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3913 |
| **Category** | Feature |

Switched `_extract_go_semantic_spans` loop to enumerated form, added `auth_guard`
detection (Authorization header access, jwt.Parse, middleware names), and wired in
`_guard_signal_for_window` — the only extractor that previously lacked it.
```

---

### Task B3 — Bump version to 3.37

**Where:** Line ~672

```python
                "version": "3.37",
```

Indentation: exactly 16 spaces.

---

### Verification for Worker B

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n '"version"' god_mode_v3.py` — confirm `3.37` at line ~672 with 16-space indent.
3. `rg -n "res\.render\|res\.sendFile\|res\.download" god_mode_v3.py` — confirm JS/TS extension.
4. Check `CHANGES.md` ends with the Sprint 6 section.

---

## Handoff

- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`

Format: see `WORKER_GUIDE.md` → "Output file format" section.
