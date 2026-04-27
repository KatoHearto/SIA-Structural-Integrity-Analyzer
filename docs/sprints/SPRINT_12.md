# Sprint 12 Briefing

Read `WORKER_GUIDE.md` first if you haven't already. This file contains your tasks for Sprint 12.

**Goal:** Expand `config_access` detection in Go (viper, godotenv) and Rust (dotenv, envy, config,
figment); add NestJS `input_boundary` decorators to the JS/TS extractor; improve Java `database_io`
by adding annotation-based detection; improve Java `config_access` with `@ConfigurationProperties`
and Spring `env.getProperty`; update docs.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — Expand Go `config_access` detection

**Where:** `_extract_go_semantic_spans`. The existing check (currently ~line 3949) only covers
`os.Getenv`. Viper is the dominant Go config library; godotenv is standard for .env loading;
`os.LookupEnv` is the idiomatic "check if set" form of `os.Getenv`.

Replace the existing single-line block:

```python
            if re.search(r"\bos\.Getenv\s*\(", text):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads environment configuration.")
```

With this expanded version:

```python
            if (
                re.search(r"\bos\.(?:Getenv|LookupEnv)\s*\(", text)
                or re.search(r"\bviper\.(?:Get|GetString|GetInt(?:Slice)?|GetBool|GetFloat64|GetDuration|GetStringSlice|GetStringMap|GetStringMapString)\s*\(", text)
                or re.search(r"\bgodotenv\.(?:Load|Overload|Read)\s*\(", text)
                or re.search(r"\benvconfig\.Process\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads environment or configuration state.")
```

---

### Task A2 — Expand Rust `config_access` detection

**Where:** `_extract_rust_semantic_spans`. The existing check (currently ~line 4004) only covers
`std::env::var`. The `dotenv`, `envy`, `config`, and `figment` crates are all common in Rust
web/backend projects.

Replace the existing single-line block:

```python
            if re.search(r"\bstd::env::var\s*\(", text):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads environment configuration.")
```

With this expanded version:

```python
            if (
                re.search(r"\bstd::env::(?:var|var_os)\s*\(", text)
                or re.search(r"\bdotenv::dotenv\s*\(", text)
                or re.search(r"\benvy::(?:from_env|prefixed)\s*\(", text)
                or re.search(r"\bconfig::Config\b", text)
                or re.search(r"\bfigment::Figment\b", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads environment or configuration state.")
```

---

### Task A3 — Add NestJS `input_boundary` decorators to JS/TS extractor

**Where:** `_extract_js_like_semantic_spans`. The existing `input_boundary` blocks only cover
Express-style handler signatures and `req.body`/`req.params` access. NestJS uses TypeScript
decorators (`@Get`, `@Post`, `@Body`, `@Param`, `@Query`) that appear on method/parameter
lines and are entirely invisible to current detection.

Insert this block immediately after the second `input_boundary` block (the `req.body/query/params`
line, currently ~line 3902–3903) and before the `output_boundary` block:

```python
            if (
                re.search(r"@(?:Get|Post|Put|Delete|Patch|Options|Head)\s*\(", text)
                or re.search(r"@(?:Body|Param|Query|Headers|Req|Res|UploadedFile)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "NestJS route or parameter decorator marks an input boundary.")
```

---

### Task A4 — Improve Java `database_io` and `config_access`

**Where:** `_extract_java_semantic_spans`.

#### Part 1 — `database_io` annotation detection

The existing `database_io` block (currently ~lines 3860–3867) relies on a `member_types` check
that only fires when the parser has resolved type names. `@Transactional` and `@Query` are
universally present on JPA/Spring Data methods and require no type inference.

Insert this block immediately after the existing `database_io` block (after line ~3867) and
before the `guard = self._guard_signal_for_window` call:

```python
            if re.search(r"@(?:Transactional|Query|Modifying|NamedQuery|NativeQuery)\b", text):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Calls a repository or database-oriented dependency.")
```

#### Part 2 — `config_access` expansion

The existing check (currently ~line 3848) covers `System.getenv`, `System.getProperty`, and
`@Value` but misses `@ConfigurationProperties` and the Spring `Environment` injection pattern.

Replace the existing single-line block:

```python
            if re.search(r"\b(?:System\.getenv|System\.getProperty|@Value)\b", text):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads configuration or environment state.")
```

With:

```python
            if (
                re.search(r"\b(?:System\.getenv|System\.getProperty)\s*\(", text)
                or re.search(r"@(?:Value|ConfigurationProperties)\b", text)
                or re.search(r"\benv\.getProperty\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads configuration or environment state.")
```

---

### Verification for Worker A

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n "viper\.Get\|godotenv\.\|LookupEnv" god_mode_v3.py` — confirm Go `config_access`
   expansion in `_extract_go_semantic_spans`.
3. `rg -n "dotenv::dotenv\|envy::\|figment::Figment" god_mode_v3.py` — confirm Rust
   `config_access` expansion in `_extract_rust_semantic_spans`.
4. `rg -n "@(?:Get|Post|Put|Delete).*NestJS\|NestJS.*input_boundary\|UploadedFile" god_mode_v3.py`
   — confirm NestJS block present in `_extract_js_like_semantic_spans`.
5. `rg -n "Transactional\|Modifying\|NamedQuery" god_mode_v3.py` — confirm Java annotation
   `database_io` block.
6. `rg -n "ConfigurationProperties\|env\.getProperty" god_mode_v3.py` — confirm Java
   `config_access` expansion.
7. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — `parse_errors=0`.

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–11576, plus project docs

### Task B1 — Add Sprint 11 entry to `CHANGES.md`

Append to the end of `CHANGES.md`:

```markdown
---

## Sprint 11 — Go & Rust validation_guard + Framework input_boundary Coverage (v3.41)

### Change 1 — Direct `validation_guard` detection in Go extractor
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3972 |
| **Category** | Feature |

`go-playground/validator` (`validate.Struct`, `validate.Var`) and `ozzo-validation`
(`validation.Validate`, `validation.ValidateStruct`) call validation functions directly —
no `if`-block — so they were invisible to `_guard_signal_for_window`. Added direct detection
for both libraries.

### Change 2 — Go `input_boundary` expanded to Gin, Echo, Fiber, Chi
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3951 |
| **Category** | Feature |

The existing Go `input_boundary` check only covered `net/http` handler signatures. Gin
(`*gin.Context`), Echo (`echo.Context`), Fiber (`*fiber.Ctx`), common accessor methods
(`c.Param`, `c.Query`, `c.Bind`, `c.ShouldBind`), and Chi (`chi.URLParam`) are now detected.

### Change 3 — Direct `validation_guard` detection in Rust extractor
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4042 |
| **Category** | Feature |

The Rust `validator` crate (`Validate::validate`, `validate.Struct`) and `garde` crate
(`.validate(&())`) were not detected without an `if`-block. Added direct pattern matching
for both library styles.

### Change 4 — Rust `output_boundary` expanded to cover Axum responses
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~4026 |
| **Category** | Feature |

The Rust `output_boundary` block only covered Actix-web patterns. Sprint 10 added Axum
`input_boundary`; this sprint completes Axum coverage with `impl IntoResponse`,
`axum::response::*`, and `StatusCode::*` response patterns.
```

---

### Task B2 — Update `WORKER_GUIDE.md`

In the "Current state" section:
1. Version line → `**3.42**`
2. Sprint history line → `- Sprint history: 13 passes (Runs 1–3 autonomous, Sprints 1–11)`

---

### Task B3 — Bump version to 3.42

**Where:** Line ~672

```python
                "version": "3.42",
```

Indentation: exactly 16 spaces.

---

### Verification for Worker B

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n '"version"' god_mode_v3.py` — confirm `3.42` at line ~672 with 16-space indent.
3. Check `CHANGES.md` ends with the Sprint 11 section.
4. `rg -n "3\.42\|Sprints 1.11" WORKER_GUIDE.md` — confirm both updated.

---

## Handoff

- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`

Format: see `WORKER_GUIDE.md` → "Output file format" section.
