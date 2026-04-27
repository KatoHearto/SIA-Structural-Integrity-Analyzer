# Sprint 6 Briefing

Read `WORKER_GUIDE.md` first if you haven't already. This file contains your tasks for Sprint 6.

**Goal:** Fill remaining Python and Go semantic gaps, then bring docs up to date.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — Extend Python `input_boundary` detection

**Where:** Line ~3778 in `_extract_python_semantic_spans`

**Current code:**
```python
if re.search(r"\binput\s*\(", text) or re.search(r"@\w*(?:route|get|post|put|delete|patch)\b", lower):
    self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Reads data at an input boundary.")
```

The current pattern only catches `input()` calls and decorator-based routes. It misses:
- **Django**: `request.GET`, `request.POST`, `request.data`, `request.body`, `request.json()`
- **FastAPI**: `Body(`, `Query(`, `Path(`, `Form(`, `Header(` — dependency injection parameter markers

**Required change:**
```python
if (
    re.search(r"\binput\s*\(", text)
    or re.search(r"@\w*(?:route|get|post|put|delete|patch)\b", lower)
    or re.search(r"\brequest\.(?:GET|POST|data|body|json|form|files|args)\b", text)
    or re.search(r"\b(?:Body|Query|Path|Form|Header|Cookie|Depends)\s*\(", text)
):
    self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Reads data at an input boundary.")
```

---

### Task A2 — Extend Python `state_mutation` to cover self-member collections

**Where:** Line ~3776 in `_extract_python_semantic_spans`

**Current code:**
```python
if re.search(r"\bself\.[A-Za-z_]\w*\s*=", text):
    self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates object state via `self`.")
```

Only catches direct attribute assignment. Misses mutation of collection attributes:
`self.items.append(x)`, `self.cache.update({...})`, `self.nodes[key] = val` — all mutate object
state but go undetected.

**Required change:** Extend the regex to also cover self-member subscript writes and common
mutable collection method calls:
```python
if (
    re.search(r"\bself\.[A-Za-z_]\w*\s*=", text)
    or re.search(r"\bself\.[A-Za-z_]\w*\[", text)
    or re.search(r"\bself\.[A-Za-z_]\w*\.(?:append|extend|insert|update|setdefault|pop|remove|clear|add|discard)\s*\(", text)
):
    self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates object state via `self`.")
```

---

### Task A3 — Add `auth_guard` and guard-window to Go extractor

**Where:** `_extract_go_semantic_spans`, line ~3907 (currently ends after `time_or_randomness` block).

**Two changes needed:**

**Change 1 — Switch loop header to enumerated form** so the guard window check can use an index.

Current loop header:
```python
for lineno, text in source_lines:
```

Replace with:
```python
for index, (lineno, text) in enumerate(source_lines):
```

**Change 2 — Add `auth_guard` detection and guard-window call** inside the loop (after the existing
`time_or_randomness` block, before `return refs`):

```python
            if (
                re.search(r"\br\.Header\.Get\s*\(\s*[\"']Authorization", text)
                or re.search(r"\bjwt\.(?:Parse|ParseWithClaims|Valid)\b", text)
                or re.search(r"\b(?:Middleware|middleware)\.(?:Auth|JWT|Token|Bearer)\b", text)
                or re.search(r"\bctx\.Value\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "Enforces authentication in Go code.")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
```

---

### Verification for Worker A

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n "request\.GET\|request\.POST\|Body\\\|Query\\\|Path\\\|Form\\\(" god_mode_v3.py` — confirm
   Python `input_boundary` extensions present.
3. `rg -n "self\.\[A-Za-z\|append\|update.*self" god_mode_v3.py` — confirm `state_mutation` extension
   present.
4. `rg -n "Header\.Get\|jwt\.Parse\|auth_guard.*Go" god_mode_v3.py` — confirm Go `auth_guard` present.
5. `rg -n "enumerate.*source_lines" god_mode_v3.py` — confirm Go loop was switched to enumerated form.
6. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — must complete with
   `parse_errors=0`.

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–11576, plus project docs

### Task B1 — Add Sprint 5 entry to `CHANGES.md`

Append the following section to the end of `CHANGES.md`:

```markdown
---

## Sprint 5 — Polyglot Signal Coverage (v3.35)

### Change 1 — Go extractor: `output_boundary`, `serialization`, `deserialization`, `state_mutation`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | ~3907–3926 |
| **Category** | Feature |

Extended `_extract_go_semantic_spans` with four previously absent signals:
`output_boundary` (w.Write, w.WriteHeader, json.NewEncoder(w).Encode, http.Error/Redirect),
`serialization` (json.Marshal/MarshalIndent), `deserialization` (json.Unmarshal/NewDecoder),
`state_mutation` (struct field assignment).

### Change 2 — Rust extractor: `error_handling`, `database_io`, `serialization`, `deserialization`, `state_mutation`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | ~3934–3956 |
| **Category** | Feature |

Extended `_extract_rust_semantic_spans` with five previously absent signals:
`error_handling` (.unwrap/.expect/? operator/Err), `database_io` (diesel/sqlx/tokio-postgres),
`serialization` (serde_json::to_string/to_vec/to_writer), `deserialization`
(serde_json::from_str/from_reader/from_slice/from_value), `state_mutation` (self.field =).

### Change 3 — JS/TS extractor: `database_io`, `auth_guard`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | ~3879–3891 |
| **Category** | Feature |

Extended `_extract_js_like_semantic_spans` with two previously absent signals:
`database_io` (Prisma, Mongoose/Model, TypeORM helpers, Knex, pool/client/db.query),
`auth_guard` (jwt.verify/decode/sign, passport.authenticate, common auth helper names).
```

---

### Task B2 — Update `WORKER_GUIDE.md` current state section

**Where:** `WORKER_GUIDE.md`, "Current state" section.

Make two edits:

1. Change the version line from `3.34` (or whatever it currently shows) to `3.36`.

2. Replace the sprint history line:
```markdown
- Sprint history: 5 passes (Runs 1–3 autonomous, Sprint 1, Sprint 2)
```
with:
```markdown
- Sprint history: 8 passes (Runs 1–3 autonomous, Sprints 1–5)
```

---

### Task B3 — Bump version to 3.36

**Where:** Line ~672

```python
                "version": "3.36",
```

Indentation: exactly 16 spaces.

---

### Verification for Worker B

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n '"version"' god_mode_v3.py` — confirm `3.36` at line ~672 with 16-space indent.
3. Check `CHANGES.md` ends with the Sprint 5 section.
4. `rg -n "3\.36\|Sprints 1" WORKER_GUIDE.md` — confirm version and sprint history updated.

---

## Handoff

- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`

Format: see `WORKER_GUIDE.md` → "Output file format" section.
