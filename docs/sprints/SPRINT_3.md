# Sprint 3 Briefing

Read `WORKER_GUIDE.md` first if you haven't already. This file contains your specific tasks for Sprint 3.

**Goal:** Improve usability — fix directory scanning noise and extend async Python semantic coverage.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730 (analysis, parsers, graph, semantic signals)

### Task A1 — Extend `should_ignore_dir` to skip `ask_bundle` prefix

**Where:** Line 470

**Current code:**
```python
def should_ignore_dir(name: str) -> bool:
    return name in IGNORE_DIRS or name.startswith(".") or name.startswith("llm_bundle")
```

**Required change:** Also skip directories whose names start with `ask_bundle`. The project root contains many
`ask_bundle_*` directories (e.g., `ask_bundle_appshell_v49`, `ask_bundle_disk_v50_flowcheck`) that are output
artifact directories containing only JSON/txt/md files — no source code. SIA currently walks into them
unnecessarily. The existing `llm_bundle` prefix skip already handles the newer `llm_bundle_ask_*` directories;
`ask_bundle` handles the older-format directories.

**Required result:**
```python
def should_ignore_dir(name: str) -> bool:
    return name in IGNORE_DIRS or name.startswith(".") or name.startswith("llm_bundle") or name.startswith("ask_bundle")
```

---

### Task A2 — Add async Python semantic signals to `_extract_python_semantic_spans`

**Where:** `_extract_python_semantic_spans`, starting at line 3739. The function runs line-by-line regex checks
to detect semantic signals. Three signals are currently missing async-specific patterns:

1. **`process_io`** — the existing pattern catches `subprocess.*()`, but not `asyncio.create_subprocess_exec`
   or `asyncio.create_subprocess_shell`, which are the async equivalents.

2. **`filesystem_io`** — the existing pattern catches `open(`, `Path(`, etc., but not `aiofiles.open(` which is
   the standard async filesystem library.

3. **`network_io`** — the existing pattern catches `requests`, `httpx`, `urllib`, but not `aiohttp.ClientSession`
   which is the most common async HTTP client.

**Required change:** Extend the three existing `if` blocks in `_extract_python_semantic_spans` as follows:

For **`process_io`** (currently around line 3758), extend the regex to also match `asyncio.create_subprocess`:
```python
if re.search(r"\b(?:subprocess\.[A-Za-z_]\w*|os\.(?:system|popen|spawnv|execv)|asyncio\.create_subprocess_(?:exec|shell))\s*\(", text):
    self._record_semantic_ref(refs, node, "process_io", lineno, lineno, "Starts or controls a process from Python code.")
```

For **`filesystem_io`** (currently around line 3750–3757), add `aiofiles\.open\s*\(` to the existing OR block:
```python
if (
    re.search(r"\bopen\s*\(", text)
    or re.search(r"\bPath\s*\(", text)
    or re.search(r"\.(?:read_text|write_text|read_bytes|write_bytes)\s*\(", text)
    or re.search(r"\bos\.(?:remove|unlink|rename|replace|makedirs)\s*\(", text)
    or re.search(r"\bshutil\.[A-Za-z_]\w*\s*\(", text)
    or re.search(r"\baiofiles\.open\s*\(", text)
):
    self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno, "Touches the filesystem from Python code.")
```

For **`network_io`** (currently around line 3748), extend the regex to also match `aiohttp.ClientSession`:
```python
if re.search(r"\b(?:requests|httpx|urllib(?:\.request)?|aiohttp\.ClientSession)\.[A-Za-z_]\w*\s*\(", text):
    self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a Python HTTP client.")
```

**Verification after your changes:**
1. `python -m py_compile god_mode_v3.py` — must produce no output.
2. `python god_mode_v3.py .polyglot_graph_fixture --out /dev/null --summary-only` — must complete with
   `parse_errors=0`.
3. `rg -n "ask_bundle\|llm_bundle" god_mode_v3.py` on line 470 — confirm both prefixes are present.
4. `rg -n "aiofiles|aiohttp|create_subprocess" god_mode_v3.py` — confirm the three new patterns appear.

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–11576 (validation, bundle generation, CLI)

### Task B1 — Create `requirements.txt`

Create a new file `requirements.txt` in the project root with this content:

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
# Optional: gitpython is used for --git-hotspot analysis if available.
# Without it, hotspot analysis is silently disabled (--no-git-hotspots default).
#
#   pip install gitpython
```

This file documents setup for new users. Do not add any actual package entries — only the comments above.

---

### Task B2 — Bump version to 3.33

**Where:** Line ~670

```python
                "version": "3.33",
```

Indentation is exactly 16 spaces. Verify with:
```bash
rg -n '"version"' god_mode_v3.py
```
Expected: `670:                "version": "3.33",` (leading spaces = 16).

---

### Verification for Worker B

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n '"version"' god_mode_v3.py` — confirm `3.33` at line ~670 with 16-space indent.
3. Confirm `requirements.txt` exists in the project root with no non-comment lines.
4. `python god_mode_v3.py --validate-worker-result worker_result_auth_valid.json --against-ask-bundle llm_bundle_ask_auth_v50`
   — must print `valid, violations=0`.

---

## Handoff

Both workers write results to their output files:
- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`

Format: see `WORKER_GUIDE.md` → "Output file format" section.
