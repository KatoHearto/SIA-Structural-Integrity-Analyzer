# Sprint 11 Briefing

Read `WORKER_GUIDE.md` first if you haven't already. This file contains your tasks for Sprint 11.

**Goal:** Add direct `validation_guard` detection to Go and Rust (currently only detected via
`_guard_signal_for_window`); expand Go `input_boundary` to cover Gin/Echo/Fiber/Chi; expand
Rust `output_boundary` to cover Axum `IntoResponse` patterns; update docs.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — Add direct `validation_guard` detection to Go extractor

**Where:** `_extract_go_semantic_spans`, immediately before the
`guard = self._guard_signal_for_window` call (currently ~line 3964).

Go's `go-playground/validator` and `ozzo-validation` perform validation through direct function
calls — no `if`-block involved — so they are invisible to `_guard_signal_for_window`.

Insert this block between the `auth_guard` record call and the `guard =` line:

```python
            if (
                re.search(r"\bvalidate\.(?:Struct|Var|StructPartial|StructExcept|VarWithValue)\s*\(", text)
                or re.search(r"\bvalidation\.(?:Validate|ValidateStruct|ValidateMap)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Invokes Go struct/field validation (go-playground/validator or ozzo-validation).")
```

---

### Task A2 — Expand Go `input_boundary` to cover popular frameworks

**Where:** `_extract_go_semantic_spans`. The existing single-line `input_boundary` check
(currently ~line 3951) only covers `net/http` patterns. Gin, Echo, Fiber, and Chi are equally
common but use different context types and accessor methods.

Replace the existing two-line block:

```python
            if re.search(r"\bhttp\.(?:HandleFunc|ListenAndServe)\b", text) or re.search(r"func\s*\(\s*\w+\s+http\.ResponseWriter\s*,\s*\w+\s+\*http\.Request", text):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Declares an HTTP boundary in Go code.")
```

With this expanded version:

```python
            if (
                re.search(r"\bhttp\.(?:HandleFunc|ListenAndServe)\b", text)
                or re.search(r"func\s*\(\s*\w+\s+http\.ResponseWriter\s*,\s*\w+\s+\*http\.Request", text)
                or re.search(r"\*gin\.Context\b", text)
                or re.search(r"\becho\.Context\b", text)
                or re.search(r"\*fiber\.Ctx\b", text)
                or re.search(r"\bc\.(?:Param|Query|FormValue|Bind|ShouldBind(?:JSON|Query)?|BodyParser|QueryParam)\s*\(", text)
                or re.search(r"\bchi\.URLParam\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Declares an HTTP boundary in Go code.")
```

---

### Task A3 — Add direct `validation_guard` detection to Rust extractor

**Where:** `_extract_rust_semantic_spans`, immediately before the
`guard = self._guard_signal_for_window` call (currently ~line 4026).

The Rust `validator` crate (and `garde`) call `.validate()` as a method — no `if`-block, so
`_guard_signal_for_window` never fires. Insert this block after the `auth_guard` record call:

```python
            if (
                re.search(r"\bValidate::validate\s*\(", text)
                or re.search(r"\bvalidate\.(?:Struct|Var|StructPartial)\s*\(", text)
                or re.search(r"\.validate\s*\(\s*&\s*\(\s*\)\s*\)", text)
                or re.search(r"\bvalidator::validate_\w+\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Invokes Rust struct/field validation (validator/garde crate).")
```

---

### Task A4 — Expand Rust `output_boundary` to cover Axum responses

**Where:** `_extract_rust_semantic_spans`. The existing `output_boundary` block (currently
~lines 4013–4018) only covers Actix-web patterns (`HttpResponse::*`, `web::Json`,
`impl Responder`). Sprint 10 added Axum `input_boundary`; this completes Axum coverage
by adding response patterns.

Replace the existing block entirely:

```python
            if (
                re.search(r"\bHttpResponse::(?:Ok|Created|BadRequest|Unauthorized|Forbidden|NotFound|InternalServerError)\s*\(", text)
                or re.search(r"\bweb::Json\s*\(", text)
                or re.search(r"\bimpl\s+Responder\b", text)
                or re.search(r"\bimpl\s+IntoResponse\b", text)
                or re.search(r"\baxum::response::", text)
                or re.search(r"\bStatusCode::[A-Z_]{2,}\b", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Produces a Rust HTTP response.")
```

---

### Verification for Worker A

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n "validate\.Struct\|validation\.Validate" god_mode_v3.py` — confirm Go `validation_guard`
   additions in `_extract_go_semantic_spans`.
3. `rg -n "gin\.Context\|echo\.Context\|fiber\.Ctx\|chi\.URLParam" god_mode_v3.py` — confirm
   Go `input_boundary` expansion.
4. `rg -n "Validate::validate\|validate\.Struct\|validator::validate" god_mode_v3.py` — confirm
   Rust `validation_guard` additions in `_extract_rust_semantic_spans`.
5. `rg -n "IntoResponse\|axum::response\|StatusCode::" god_mode_v3.py` — confirm Rust Axum
   `output_boundary` expansion.
6. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — `parse_errors=0`.

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–11576, plus project docs

### Task B1 — Add Sprint 10 entry to `CHANGES.md`

Append to the end of `CHANGES.md`:

```markdown
---

## Sprint 10 — Direct Schema Validation + Axum Input Boundaries (v3.40)

### Change 1 — Direct `validation_guard` detection in Python extractor
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3808 |
| **Category** | Feature |

Pydantic (`model_validate`, `BaseModel`), marshmallow (`Schema.load`/`loads`/`validate`),
Django forms/DRF serializers (`form.is_valid`, `serializer.validate`), and WTForms
(`validate_on_submit`) were invisible to `validation_guard` because they don't use `if`-blocks.
Added direct pattern matching for all five library families.

### Change 2 — Direct `validation_guard` detection in JS/TS extractor
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3920 |
| **Category** | Feature |

Zod (`z.parse`, `z.safeParse`, chained `.parse`/`.safeParse`/`.parseAsync`), Joi
(`joi.*.validate`), and Yup (`yup.*.validate`) schema calls were not detected without
an `if`-block. Added direct regex patterns for all three libraries.

### Change 3 — Axum `input_boundary` patterns in Rust extractor
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4008 |
| **Category** | Feature |

The Rust `input_boundary` block only covered Actix-web patterns. Axum extractor syntax
(`axum::extract::`, `extract::Json/Path/Query/Form/State/TypedHeader`, `axum::routing::`)
is now fully covered alongside the existing Actix-web patterns.
```

---

### Task B2 — Update `WORKER_GUIDE.md`

In the "Current state" section:
1. Version line → `**3.41**`
2. Sprint history line → `- Sprint history: 12 passes (Runs 1–3 autonomous, Sprints 1–10)`

---

### Task B3 — Bump version to 3.41

**Where:** Line ~672

```python
                "version": "3.41",
```

Indentation: exactly 16 spaces.

---

### Verification for Worker B

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n '"version"' god_mode_v3.py` — confirm `3.41` at line ~672 with 16-space indent.
3. Check `CHANGES.md` ends with the Sprint 10 section.
4. `rg -n "3\.41\|Sprints 1.10" WORKER_GUIDE.md` — confirm both updated.

---

## Handoff

- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`

Format: see `WORKER_GUIDE.md` → "Output file format" section.
