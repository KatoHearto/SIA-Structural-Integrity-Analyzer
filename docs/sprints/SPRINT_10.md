# Sprint 10 Briefing

Read `WORKER_GUIDE.md` first if you haven't already. This file contains your tasks for Sprint 10.

**Goal:** Add direct `validation_guard` detection for Python and JS/TS schema libraries (currently
only Java has it); add Axum `input_boundary` patterns for Rust; update docs.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — Add direct `validation_guard` detection to Python extractor

**Where:** `_extract_python_semantic_spans`, immediately before the `error_handling` block
(the `stripped.startswith("try:")` line, currently ~line 3801).

`validation_guard` is currently only produced by the `_guard_signal_for_window` path,
which requires an `if`-statement followed by a guard action. Schema validation libraries
(Pydantic, marshmallow, Django forms/DRF serializers) perform validation by calling methods
or constructors — no `if` statement involved — so they are never detected.

Add this block:

```python
            if (
                re.search(r"\bmodel_validate(?:_json)?\s*\(", text)
                or re.search(r"\bBaseModel\s*\(", text)
                or re.search(r"\b(?:schema|Schema)\.(?:load|loads|validate)\s*\(", text)
                or re.search(r"\b(?:form|serializer)\.(?:is_valid|validate)\s*\(", text)
                or re.search(r"\.validate_on_submit\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Invokes schema or form validation.")
```

---

### Task A2 — Add direct `validation_guard` detection to JS/TS extractor

**Where:** `_extract_js_like_semantic_spans`, immediately before the `guard =
self._guard_signal_for_window` call (currently ~line 3893).

Zod, Joi, Yup, and generic schema `.validate()` calls are invisible to the guard window
because they don't use `if`-blocks. Add direct detection:

```python
            if (
                re.search(r"\bz\.[a-z]\w*\(\s*\)\.(?:parse|safeParse|parseAsync)\s*\(", text)
                or re.search(r"\bz\.(?:parse|safeParse)\s*\(", text)
                or re.search(r"\b(?:schema|Schema)\.(?:parse|validate|validateSync|validateAsync)\s*\(", text)
                or re.search(r"\bjoi\.[a-z]\w*\(\s*\)\.validate\s*\(", text)
                or re.search(r"\b(?:yup\.|Yup\.)\w+\(\s*\)\.validate\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Invokes schema validation (Zod/Joi/Yup).")
```

---

### Task A3 — Add Axum `input_boundary` patterns to Rust extractor

**Where:** The `input_boundary` block inside `_extract_rust_semantic_spans` (currently
~line 3993). Actix-web patterns were added in Sprint 7. Axum is now equally common and
has completely different extractor syntax.

Extend the existing `input_boundary` block:

```python
            if (
                re.search(r"#\[(?:get|post|put|delete|patch|head|options)\s*\(", text)
                or re.search(r"\b(?:web::Path|web::Json|web::Query|web::Form|HttpRequest)\b", text)
                or re.search(r"\baxum::extract::\b", text)
                or re.search(r"\bextract::(?:Json|Path|Query|Form|State|TypedHeader)\b", text)
                or re.search(r"\baxum::routing::\b", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Declares a Rust HTTP input boundary.")
```

Replace the existing `input_boundary` block entirely with this expanded version.

---

### Verification for Worker A

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n "model_validate\|schema.*load\|is_valid\|validate_on_submit" god_mode_v3.py` — confirm
   Python `validation_guard` additions in `_extract_python_semantic_spans`.
3. `rg -n "safeParse\|z\.parse\|yup\.\|joi\." god_mode_v3.py` — confirm JS/TS `validation_guard`
   additions.
4. `rg -n "axum::extract\|axum::routing\|extract::Json" god_mode_v3.py` — confirm Rust Axum
   additions.
5. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — `parse_errors=0`.

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–11576, plus project docs

### Task B1 — Add Sprint 9 entry to `CHANGES.md`

Append to the end of `CHANGES.md`:

```markdown
---

## Sprint 9 — Bug Fixes: Encoding + Validation Guard (v3.39)

### Change 1 — `UnicodeDecodeError` crash in `_parse_file`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~842 |
| **Category** | Bug fix |

`_parse_file` only caught `SyntaxError` and `OSError`. A `.py` file with non-UTF-8
encoding (Latin-1, CP1252, etc.) raised `UnicodeDecodeError` which is a `ValueError`
subclass — not caught — and aborted the entire analysis run. Fixed by broadening the
`OSError` clause to `(OSError, UnicodeDecodeError)`.

### Change 2 — `UnicodeDecodeError` crash in `_read_project_text`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4874 |
| **Category** | Bug fix |

Same encoding issue in `_read_project_text`, which is called during bundle generation
and inventory building. Non-UTF-8 source files would abort bundle output. Fixed by
broadening the `except OSError` to `except (OSError, UnicodeDecodeError)`.

### Change 3 — `_looks_like_validation_guard` false positives reduced
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3593 |
| **Category** | Bug fix |

Bare `"==" in text` and `"!=" in text` triggers caused virtually any `if`-with-comparison
that had a nearby `return`/`raise` to be labeled `validation_guard`. Replaced with a
targeted regex that only matches comparisons against null/empty/boolean sentinels
(`None`, `null`, `undefined`, `""`, `''`, `0`, `False`, `True`). Also added
`" is not none"` as an explicit positive case.
```

---

### Task B2 — Update `WORKER_GUIDE.md`

In the "Current state" section:
1. Version line → `**3.40**`
2. Sprint history line → `- Sprint history: 11 passes (Runs 1–3 autonomous, Sprints 1–9)`

---

### Task B3 — Bump version to 3.40

**Where:** Line ~672

```python
                "version": "3.40",
```

Indentation: exactly 16 spaces.

---

### Verification for Worker B

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n '"version"' god_mode_v3.py` — confirm `3.40` at line ~672 with 16-space indent.
3. Check `CHANGES.md` ends with the Sprint 9 section.
4. `rg -n "3\.40\|Sprints 1.9" WORKER_GUIDE.md` — confirm both updated.

---

## Handoff

- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`

Format: see `WORKER_GUIDE.md` → "Output file format" section.
