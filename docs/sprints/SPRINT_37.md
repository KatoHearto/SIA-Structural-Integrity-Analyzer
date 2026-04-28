# SPRINT 37 — Absence Detection: Spec Alignment (`--spec`)

**Version:** 3.66 → 3.67  
**File:** `god_mode_v3.py`

---

## Goal

SIA reads a specification document (API documentation, OpenAPI YAML, markdown)
and compares it against the implementation. Gaps between spec and code produce
`absence_warnings` of kind `spec_gap`. No more manually reading API docs and
checking whether the code handles what they describe.

---

## Root Cause / Motivation

During the Polaris API debugging session, `POLARIS_API.md` was read manually to
understand what fields are required (`supplierNumber`, `insuranceNumber`, `zipCode`)
and what error conditions exist. The code was then manually checked against the spec.

This is exactly the kind of cross-reference SIA can automate. If SIA had read the
spec, it would have flagged `api_new.py`'s wrong field names immediately — not after
a week of HTTP 500 errors.

---

## Changes

### 1. New CLI Flag: `--spec <path>`

```
sia scan --spec docs/POLARIS_API.md .
sia scan --spec openapi.yaml .
sia scan --spec docs/ .   # scans all .md and .yaml files in directory
```

Accepted formats:
- Markdown (`.md`) — parsed for structure (headings, code blocks, field lists)
- OpenAPI / Swagger (`.yaml`, `.json`) — parsed as structured spec
- Plain text (`.txt`) — best-effort extraction

### 2. Spec Parser

Extract from spec documents:

**From Markdown:**
- Endpoint definitions: lines matching `POST/GET/PUT/DELETE <path>`
- Required fields: code blocks with JSON containing `// required` comments or
  bold-marked field names
- Error codes: lines matching `HTTP 4xx` or `HTTP 5xx` with descriptions
- Field formats: regex patterns in comments or descriptions

**From OpenAPI:**
- `paths` → endpoint list
- `required` arrays → required field list per endpoint
- `responses` → expected status codes
- `schema.pattern` → field format constraints

### 3. Spec-to-Code Matching

For each spec-defined endpoint, SIA searches the codebase for:
- A function that calls that endpoint URL (string match in `resolved_string_refs`)
- A function that constructs a payload with those field names

Then checks:
- Are all required fields present in the payload construction?
- Are all spec-defined error codes handled (except clause or response check)?
- Do field validation guards match spec-defined format constraints?

### 4. Spec Gap Warnings

Added to `absence_warnings` with kind `spec_gap`:

```json
{
  "rule": "spec_gap",
  "severity": "high",
  "node_id": "smartversorgt_crm.api:polaris_register",
  "spec_source": "docs/POLARIS_API.md",
  "spec_line": 57,
  "gap_type": "missing_field_validation",
  "message": "Spec requires insuranceNumber format [A-Z][0-9]{9} — no validation found in implementation",
  "spec_excerpt": "insuranceNumber: 999999999|[a-zA-Z]+[0-9]{9}  // required",
  "suggestion": "Add regex validation before payload construction (see _polaris_token for pattern)"
},
{
  "rule": "spec_gap",
  "severity": "medium",
  "node_id": "smartversorgt_crm.api:polaris_register",
  "spec_source": "docs/POLARIS_API.md",
  "gap_type": "unhandled_error_code",
  "message": "Spec documents HTTP 401 and HTTP 500 responses — only HTTP 200 is handled in implementation",
  "suggestion": "Add except branch for requests.HTTPError with status code check"
}
```

### 5. Spec Coverage Metric

New `meta` entry when `--spec` is used:

```json
"spec_coverage": {
  "spec_file": "docs/POLARIS_API.md",
  "endpoints_in_spec": 4,
  "endpoints_implemented": 3,
  "endpoints_missing": 1,
  "required_fields_validated": 1,
  "required_fields_unvalidated": 2,
  "error_codes_handled": 1,
  "error_codes_unhandled": 3,
  "coverage_score": 0.38
}
```

### 6. Version Bump

`3.66` → `3.67`

---

## Validation

- `sia scan --spec docs/POLARIS_API.md` on smartversorgt_crm must produce:
  - `spec_gap` for `insuranceNumber` format not validated
  - `spec_gap` for `moveToUsDate` not handled (spec says: required when Wechselerklärung)
  - `spec_gap` for HTTP 401 response not handled in `polaris_register`
- `spec_coverage.coverage_score` for smartversorgt_crm must be < 0.5 (honest baseline)
- OpenAPI parsing: `sia scan --spec openapi.yaml` on a standard OpenAPI 3.0 file
  must extract endpoints and required fields correctly
- `--spec` without a valid file: clear error message, no crash

---

## What Does NOT Change

- Spec alignment is purely additive to `absence_warnings`
- `sia scan` without `--spec` is unchanged in behavior and performance
- Spec gaps do not affect `architectural_warnings` or `exploitability_score`
