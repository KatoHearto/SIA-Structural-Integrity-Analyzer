# Sprint 4 Briefing

Read `WORKER_GUIDE.md` first if you haven't already. This file contains your tasks for Sprint 4.

**Goal:** Fix a factual error in `requirements.txt`, extend Python `output_boundary` detection, add missing
guard action patterns, and bring documentation up to date.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730 (analysis, parsers, semantic signals)

### Task A1 — Extend Python `output_boundary` detection

**Where:** Line ~3778 in `_extract_python_semantic_spans`

**Current code:**
```python
if re.search(r"\b(?:jsonify|Response)\s*\(", text):
    self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Produces boundary-facing output.")
```

`Response` is too generic and only catches the base class name. This misses the most common FastAPI, Starlette,
and Django response constructors that coworkers' codebases will actually use.

**Required change:** Extend the regex to cover the full set of common Python web framework response types:

```python
if re.search(
    r"\b(?:jsonify|Response|JSONResponse|HTMLResponse|StreamingResponse|FileResponse|"
    r"ORJSONResponse|RedirectResponse|PlainTextResponse|UJSONResponse|"
    r"HttpResponse|JsonResponse|HttpResponseRedirect|StreamingHttpResponse)\s*\(",
    text,
):
    self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Produces boundary-facing output.")
```

---

### Task A2 — Add missing guard action patterns

**Where:** `SEMANTIC_GUARD_ACTION_PATTERNS` at line ~270

**Current code:**
```python
SEMANTIC_GUARD_ACTION_PATTERNS = (
    "raise ",
    "throw ",
    "return ",
    "return;",
    "return null",
    "return false",
    "return responseentity",
    "return res.",
    "res.status(",
)
```

`abort(` (Flask) and `redirect(` (Django/Flask) cut the request short the same way `raise` does, but they are
not in the pattern list. A Python guard block that calls `abort(403)` or `redirect(login_url)` will currently
go undetected.

**Required change:** Add the two missing entries:

```python
SEMANTIC_GUARD_ACTION_PATTERNS = (
    "raise ",
    "throw ",
    "return ",
    "return;",
    "return null",
    "return false",
    "return responseentity",
    "return res.",
    "res.status(",
    "abort(",
    "redirect(",
)
```

---

### Verification for Worker A

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n "JSONResponse|HttpResponse|StreamingResponse" god_mode_v3.py` — confirm the new patterns appear
   in `_extract_python_semantic_spans`.
3. `rg -n '"abort\("|"redirect\("' god_mode_v3.py` — confirm both appear in
   `SEMANTIC_GUARD_ACTION_PATTERNS`.
4. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — must complete with
   `parse_errors=0`.

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–11576 (validation, bundle, CLI), plus project docs

### Task B1 — Fix `requirements.txt` (factual error)

The current `requirements.txt` mentions `gitpython` as an optional dependency. This is **wrong**. The git
hotspot feature (`_compute_git_hotspots`, line ~3321) uses `subprocess` to call the `git` CLI directly — it
does not import or use the `gitpython` package at any point.

**Replace the entire file** with the corrected version:

```
# Structural Integrity Analyzer v3
# No third-party dependencies required.
# Pure Python stdlib — runs on Python 3.8+.
#
# Optional: tomllib is available in stdlib from Python 3.11 onwards.
# On Python 3.8–3.10, TOML manifest parsing (pyproject.toml) is silently
# skipped. Install tomli if you need it:
#
#   pip install tomli
#
# Optional: git hotspot analysis (--no-git-hotspots is the default when git
# is unavailable) requires the `git` CLI binary to be on PATH — no Python
# package needed.
```

---

### Task B2 — Add Sprint 3 entry to `CHANGES.md`

Append the following section to `CHANGES.md` (at the end of the file):

```markdown
---

## Sprint 3 — Usability Pass (v3.33)

### Change 1 — `should_ignore_dir` skips `ask_bundle` prefix
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | 470 |
| **Category** | Performance / Correctness |

`ask_bundle_*` output directories were not in the ignore list, causing SIA to walk into them
on every run against the project root. Extended `should_ignore_dir` to skip the `ask_bundle`
prefix, matching the existing `llm_bundle` prefix pattern.

### Change 2 — Async Python semantic signals
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | ~3748–3759 |
| **Category** | Feature |

Extended `_extract_python_semantic_spans` with three async-specific detection patterns:
- `aiohttp.ClientSession` → `network_io`
- `aiofiles.open` → `filesystem_io`
- `asyncio.create_subprocess_exec/shell` → `process_io`

These patterns were absent, causing async Python codebases to produce false-negative results
for the three affected signals.

### Change 3 — `requirements.txt` created
| | |
|---|---|
| **File** | `requirements.txt` (new) |
| **Category** | Documentation |

Added project root `requirements.txt` documenting the stdlib-only dependency model and optional
`tomli` / `git` CLI requirements.
```

---

### Task B3 — Update `WORKER_GUIDE.md` current state section

**Where:** In `WORKER_GUIDE.md`, find the "Current state" section.

Replace the version and status line:
```markdown
- Version: **3.32**
```
with:
```markdown
- Version: **3.34**
```

Also find the line:
```markdown
- **No README.md, no setup documentation, no requirements.txt at the top level**
```
If that line exists, remove it (it was from a prior planning note and is no longer accurate).
If it does not exist, no action needed.

---

### Task B4 — Bump version to 3.34

**Where:** Line ~670

```python
                "version": "3.34",
```

Indentation: exactly 16 spaces.

Verify:
```bash
rg -n '"version"' god_mode_v3.py
```
Expected output: `670:                "version": "3.34",`

---

### Verification for Worker B

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n '"version"' god_mode_v3.py` — confirm `3.34` at line ~670 with 16-space indent.
3. `rg -n "gitpython" requirements.txt` — must return no results.
4. `rg -n "git CLI" requirements.txt` — must return a match.
5. Check `CHANGES.md` ends with the Sprint 3 section.
6. Check `WORKER_GUIDE.md` shows `3.34` in the current state section.

---

## Handoff

- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`

Format: see `WORKER_GUIDE.md` → "Output file format" section.
