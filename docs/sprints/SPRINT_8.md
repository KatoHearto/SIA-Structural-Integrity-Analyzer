# Sprint 8 Briefing

Read `WORKER_GUIDE.md` first if you haven't already. This file contains your tasks for Sprint 8.

**Goal:** Make risk output more actionable by surfacing semantic signals in risk reasons; complete Rust
extractor consistency; update docs.

---

## Worker A — Tasks

**Domain:** `god_mode_v3.py` lines 1–8730

### Task A1 — Swap pipeline order so semantic signals feed into risk reasons

**Where:** Lines 656–657 in `run()`

**Current code:**
```python
        self._compute_risk_scores()
        self._extract_semantic_signals()
```

`_compute_risk_scores()` generates the risk reasons (`_reasons_for`) but semantic signals haven't
been extracted yet at that point, so they can't inform the reasons. `_extract_semantic_signals()`
only reads source text — it has no dependency on risk scores — so swapping is safe.

**Required change:**
```python
        self._extract_semantic_signals()
        self._compute_risk_scores()
```

---

### Task A2 — Add semantic signal context to `_reasons_for`

**Where:** `_reasons_for`, line ~3461. After the existing final block (`if not reasons and
node.risk_score >= 55.0`), add a new block that surfaces critical semantic signals when
structural pressure is also present:

```python
        if node.semantic_signals:
            critical = [s for s in node.semantic_signals if s in SEMANTIC_CRITICAL_SIGNALS]
            if critical and (node.instability >= 0.7 or node.ca >= 3 or node.ce_internal >= 3):
                reasons.append(
                    f"Carries critical semantic signals ({', '.join(sorted(critical))}) under structural pressure — verify change safety."
                )
        return reasons
```

**Important:** Remove the existing bare `return reasons` at the end of the method and replace
with the block above (which ends with `return reasons`). Do not add a duplicate `return`.

---

### Task A3 — Add guard-window to Rust extractor

**Where:** `_extract_rust_semantic_spans`, line ~3957. The Rust extractor is the only one still
using a plain `for lineno, text in source_lines:` loop. All other extractors use `enumerate` and
call `_guard_signal_for_window`.

**Change 1 — Switch loop header:**
```python
        for index, (lineno, text) in enumerate(source_lines):
```

**Change 2 — Add guard-window call** inside the loop, after the `auth_guard` block, before
`return refs`:
```python
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
```

---

### Verification for Worker A

1. `python -m py_compile god_mode_v3.py` — no output.
2. `grep -n "extract_semantic_signals\|compute_risk_scores" god_mode_v3.py | head -5`  
   (or `rg`) — confirm `_extract_semantic_signals` appears on an earlier line than
   `_compute_risk_scores` in the `run()` method.
3. `rg -n "Carries critical semantic signals" god_mode_v3.py` — confirm new reason present.
4. `rg -n "enumerate.*source_lines" god_mode_v3.py` — confirm Rust extractor now in the list
   (should show 5 lines total: Python, Java, JS/TS, Go, Rust).
5. `rg -n "guard_signal_for_window" god_mode_v3.py` — confirm Rust extractor calls it.
6. `python god_mode_v3.py .polyglot_graph_fixture --out NUL --summary-only` — `parse_errors=0`.

**Do not bump the version** — Worker B handles that.

---

## Worker B — Tasks

**Domain:** `god_mode_v3.py` lines 8730–11576, plus project docs

### Task B1 — Add Sprint 7 entry to `CHANGES.md`

Append the following to the end of `CHANGES.md`:

```markdown
---

## Sprint 7 — Final Signal Coverage (v3.37)

### Change 1 — Python `database_io`: Django ORM and asyncpg
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3763 |
| **Category** | Feature |

Extended `_extract_python_semantic_spans` `database_io` pattern with Django ORM class-method
queries (`objects.filter/get/create/update/delete/all/exclude/annotate/aggregate/bulk_create`),
Django model instance `.save()` / `.delete()`, and asyncpg `conn.fetch/fetchrow/fetchval`.

### Change 2 — Python `auth_guard`: decorator patterns
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3797 |
| **Category** | Feature |

Added direct detection of Python auth/permission decorators (`@login_required`,
`@permission_required`, `@jwt_required`, `@token_required`, `@requires_auth`,
`@authenticated`, `@auth_required`, `@requires_permission`) as `auth_guard` signals.
Previously these were only caught probabilistically via the guard-window keyword search.

### Change 3 — Go `database_io`: GORM patterns
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3921 |
| **Category** | Feature |

Extended Go `database_io` to include GORM method chains:
`db.Where`, `db.Find`, `db.First`, `db.Last`, `db.Create`, `db.Save`, `db.Delete`,
`db.Update`, `db.Updates`, `db.Preload`, `db.Joins`.

### Change 4 — Rust: `input_boundary`, `output_boundary`, `auth_guard`
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Lines** | ~3983–4000 |
| **Category** | Feature |

Added three previously absent signals to `_extract_rust_semantic_spans`:
`input_boundary` (Actix-web route macros `#[get/post/…]`, `web::Path/Json/Query/Form`,
`HttpRequest`), `output_boundary` (`HttpResponse::Ok/Created/…`, `web::Json(`,
`impl Responder`), `auth_guard` (bearer token, `jwt::decode`, Authorization header,
`Identity` API).

### Change 5 — JS/TS `output_boundary`: Express render/file/redirect
| | |
|---|---|
| **File** | `god_mode_v3.py` |
| **Line** | ~3885 |
| **Category** | Feature |

Extended `_extract_js_like_semantic_spans` `output_boundary` pattern to also catch
`res.render(`, `res.sendFile(`, `res.download(`, and `res.redirect(`.
```

---

### Task B2 — Update `WORKER_GUIDE.md`

Make two edits in the "Current state" section:

1. Version line → `**3.38**`
2. Sprint history line → `- Sprint history: 9 passes (Runs 1–3 autonomous, Sprints 1–7)`

Also update the **Version bump** section example, which still shows `"3.32"`. Change it to show
the current version pattern:
```markdown
```python
                "version": "3.37",
```

Indentation is exactly 16 spaces. Increment the minor version by 1 (e.g., 3.37 → 3.38).
```
(Replace whatever version number is currently shown in that example block.)

---

### Task B3 — Bump version to 3.38

**Where:** Line ~672

```python
                "version": "3.38",
```

Indentation: exactly 16 spaces.

---

### Verification for Worker B

1. `python -m py_compile god_mode_v3.py` — no output.
2. `rg -n '"version"' god_mode_v3.py` — confirm `3.38` at line ~672 with 16-space indent.
3. Check `CHANGES.md` ends with the Sprint 7 section.
4. `rg -n "3\.38\|Sprints 1.7" WORKER_GUIDE.md` — confirm version and sprint history updated.

---

## Handoff

- Worker A → `worker_output_a.md`
- Worker B → `worker_output_b.md`

Format: see `WORKER_GUIDE.md` → "Output file format" section.
