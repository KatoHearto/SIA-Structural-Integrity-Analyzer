# Sprint 9 Briefing

Read `WORKER_GUIDE.md` first if you haven't already. This file contains your tasks for Sprint 9.

**Goal:** Fix two real bugs (UnicodeDecodeError crashes, over-broad validation guard detection)
and update docs.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — Fix `UnicodeDecodeError` crash in `_parse_file`

**Where:** Lines 839–844 in `_parse_file`

**Current code:**
```python
        except SyntaxError as exc:
            self.parse_errors.append({"file": rel_path, "error": f"SyntaxError: {exc.msg} (line {exc.lineno})"})
            return
        except OSError as exc:
            self.parse_errors.append({"file": rel_path, "error": f"OSError: {exc}"})
            return
```

**Bug:** `UnicodeDecodeError` is a subclass of `ValueError`, not `OSError`. Opening a `.py`
file that uses a non-UTF-8 encoding (e.g. Latin-1, CP1252) raises `UnicodeDecodeError` which
is not caught — the exception propagates and aborts the entire analysis run.

**Required change:** Add `UnicodeDecodeError` to the `OSError` clause:

```python
        except SyntaxError as exc:
            self.parse_errors.append({"file": rel_path, "error": f"SyntaxError: {exc.msg} (line {exc.lineno})"})
            return
        except (OSError, UnicodeDecodeError) as exc:
            self.parse_errors.append({"file": rel_path, "error": f"OSError: {exc}"})
            return
```

---

### Task A2 — Fix `UnicodeDecodeError` crash in `_read_project_text`

**Where:** Lines 4871–4875 in `_read_project_text`

**Current code:**
```python
        try:
            with open(full_path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except OSError:
            content = None
```

**Bug:** Same issue — `UnicodeDecodeError` from a non-UTF-8 file is not caught and crashes
the analysis. This method is called by `_node_source_lines` and `_build_project_inventory`
among others, so a crash here silently aborts bundle generation.

**Required change:**

```python
        try:
            with open(full_path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except (OSError, UnicodeDecodeError):
            content = None
```

---

### Task A3 — Tighten `_looks_like_validation_guard` to reduce false positives

**Where:** Lines 3589–3600 in `_looks_like_validation_guard`

**Current code:**
```python
    def _looks_like_validation_guard(self, text: str) -> bool:
        lower = f" {text.lower()} "
        if any(hint in lower for hint in SEMANTIC_VALIDATION_HINTS):
            return True
        return bool(
            re.search(r"\bif\s*\(\s*!", text)
            or " is none" in lower
            or "==" in text
            or "!=" in text
            or "<=" in text
            or ">=" in text
        )
```

**Bug:** Bare `"==" in text` and `"!=" in text` match virtually any `if`-with-comparison,
turning ordinary control flow (`if status == "active": return result`) into false-positive
`validation_guard` signals. The `<=` and `>=` checks are less noisy (length/range bounds)
and can stay.

**Required change:** Replace the bare `==`/`!=` checks with a targeted pattern that only
matches comparisons to null/empty/boolean sentinel values — which are the actual validation
patterns:

```python
    def _looks_like_validation_guard(self, text: str) -> bool:
        lower = f" {text.lower()} "
        if any(hint in lower for hint in SEMANTIC_VALIDATION_HINTS):
            return True
        return bool(
            re.search(r"\bif\s*\(\s*!", text)
            or " is none" in lower
            or " is not none" in lower
            or re.search(r'(?:==|!=)\s*(?:None|null|undefined|""|\'\'|0\b|False\b|True\b)', text)
            or "<=" in text
            or ">=" in text
        )
```

---

### Verification for Worker A

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n "OSError, UnicodeDecodeError" god_mode_v3.py` — must return exactly 2 matches
   (one in `_parse_file`, one in `_read_project_text`).
3. `rg -n "is not none\|!=.*None\|==.*None" god_mode_v3.py | grep "looks_like\|3[56][0-9][0-9]"` —
   confirm the new targeted pattern is present in `_looks_like_validation_guard`.
4. `rg -n '"==" in text' god_mode_v3.py` — must return 0 results (bare check removed).
5. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — `parse_errors=0`.

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–11576, plus project docs

### Task B1 — Add Sprint 8 entry to `CHANGES.md`

Append to the end of `CHANGES.md`:

```markdown
---

## Sprint 8 — Risk Reasoning + Rust Consistency (v3.38)

### Change 1 — Pipeline order: semantic signals before risk scores
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | 656–657 |
| **Category** | Bug fix |

`_compute_risk_scores()` was called before `_extract_semantic_signals()`, so `node.semantic_signals`
was always empty when `_reasons_for` ran. Swapped the order so semantic signals are available
during risk-reason generation.

### Change 2 — Semantic signal context in `_reasons_for`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3485 |
| **Category** | Feature |

Added a new reason: when a node carries critical semantic signals (`SEMANTIC_CRITICAL_SIGNALS`)
and is also under structural coupling pressure (instability ≥ 0.7, Ca ≥ 3, or Ce ≥ 3), the
risk reason now explicitly names the signals. This makes top-risk output actionable rather than
purely structural.

### Change 3 — Rust extractor: guard-window enabled
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3968 |
| **Category** | Feature |

Switched `_extract_rust_semantic_spans` loop to enumerated form and added
`_guard_signal_for_window` call. Rust is now consistent with all other four extractors.
```

---

### Task B2 — Update `WORKER_GUIDE.md`

In the "Current state" section:
1. Version line → `**3.39**`
2. Sprint history line → `- Sprint history: 10 passes (Runs 1–3 autonomous, Sprints 1–8)`

---

### Task B3 — Bump version to 3.39

**Where:** Line ~672

```python
                "version": "3.39",
```

Indentation: exactly 16 spaces.

---

### Verification for Worker B

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n '"version"' god_mode_v3.py` — confirm `3.39` at line ~672 with 16-space indent.
3. Check `CHANGES.md` ends with the Sprint 8 section.
4. `rg -n "3\.39\|Sprints 1.8" WORKER_GUIDE.md` — confirm both updated.

---

## Handoff

- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`

Format: see `WORKER_GUIDE.md` → "Output file format" section.
