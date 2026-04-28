# ── SIA src/00_header.py ── (god_mode_v3.py lines 1–401) ────────────────────
#!/usr/bin/env python3
"""
Structural Integrity Analyzer (Zero-Voodoo v3)

Deterministic architecture analysis for multi-language codebases:
- Python symbol graph (functions, methods, classes)
- Multi-language module/import graph for JS/TS, Go, Java, and Rust
- Coupling metrics (Ca/Ce, instability)
- Cycle detection (SCC / Tarjan)
- Layer depth on condensed DAG
- Deterministic XY/Z coordinates
- Ranked risk report (top-N)
- LLM context pack for token-aware follow-up analysis
"""

from __future__ import annotations

import argparse
import ast
import builtins
import hashlib
import json
import math
import os
import subprocess
import sys
import re
from pathlib import Path
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple
from xml.etree import ElementTree

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for older runtimes
    tomllib = None


IGNORE_DIRS = {
    ".git",
    ".sia_fixture",
    ".multilang_fixture",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "llm_bundle",
    "venv",
    "node_modules",
}

BUILTIN_NAMES = frozenset(dir(builtins))
LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".java": "Java",
    ".rs": "Rust",
    ".cs": "CSharp",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".php": "PHP",
    ".rb": "Ruby",
}
JS_LIKE_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
_FRAPPE_ORM_LOAD_RE = re.compile(
    r'\bfrappe\.(?:get_doc|new_doc|get_cached_doc|get_last_doc|get_single|get_all|get_list|get_value)\s*\(\s*["\']([^"\']+)["\']',
)
_FRAPPE_DB_RE = re.compile(
    r'\bfrappe\.db\.(?:get_value|set_value|get_all|exists|count|delete|get_singles_value)\s*\(\s*["\']([^"\']+)["\']',
)
JS_CALL_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "return",
    "function",
    "class",
    "typeof",
    "delete",
    "void",
    "new",
    "import",
    "export",
    "super",
}
JS_GLOBAL_NAMES = {
    "Array",
    "Boolean",
    "Date",
    "Error",
    "JSON",
    "Math",
    "Number",
    "Object",
    "Promise",
    "Reflect",
    "RegExp",
    "Set",
    "String",
    "Symbol",
    "WeakMap",
    "WeakSet",
    "console",
    "document",
    "global",
    "globalThis",
    "module",
    "process",
    "window",
}
JS_NON_SYMBOL_TYPES = {
    "any",
    "bigint",
    "boolean",
    "never",
    "null",
    "number",
    "object",
    "string",
    "symbol",
    "undefined",
    "unknown",
    "void",
}
JAVA_NON_SYMBOL_TYPES = {
    "boolean",
    "byte",
    "char",
    "double",
    "float",
    "int",
    "long",
    "short",
    "void",
}
JAVA_COMPONENT_ANNOTATIONS = {
    "ApplicationScoped",
    "Component",
    "Controller",
    "Named",
    "Repository",
    "RestController",
    "Service",
    "Singleton",
}
JAVA_PRIMARY_ANNOTATIONS = {"Primary"}
JAVA_QUALIFIER_ANNOTATIONS = {"Named", "Qualifier", "Resource"}
RESOLUTION_CONFIDENCE = {
    "direct_symbol": (0.99, "very_high"),
    "same_class_method": (0.97, "very_high"),
    "same_module_symbol": (0.95, "high"),
    "import_exact": (0.93, "high"),
    "alias_resolved": (0.89, "high"),
    "barrel_reexport": (0.87, "high"),
    "inheritance_exact": (0.9, "high"),
    "super_dispatch": (0.86, "high"),
    "instance_dispatch": (0.84, "high"),
    "java_di_primary": (0.83, "medium_high"),
    "java_di_qualifier": (0.81, "medium_high"),
    "java_di_unique_impl": (0.78, "medium_high"),
    "string_ref": (0.75, "medium_high"),
    "doctype_link": (1.0, "very_high"),
    "doctype_child": (1.0, "very_high"),
    "doctype_controller": (0.9, "high"),
    "orm_load": (0.85, "high"),
    "heuristic": (0.65, "medium"),
    "ambiguous_candidates": (0.0, "ambiguous"),
}

CONFIDENCE_LABEL_ORDER = {
    "ambiguous": 0,
    "medium": 1,
    "medium_high": 2,
    "high": 3,
    "very_high": 4,
}
FLOW_COMPLETENESS_ORDER = {
    "missing": 0,
    "context_only": 1,
    "partial": 2,
    "complete": 3,
}
OUTCOME_MODE_ORDER = {
    "unproven": 0,
    "ambiguous": 1,
    "partial": 2,
    "confirmed": 3,
}
WORKER_COMPLETION_STATES = (
    "ready_for_execution",
    "in_progress",
    "completed_within_bounds",
    "stopped_on_guardrail",
    "stopped_on_ambiguity",
    "stopped_on_insufficient_evidence",
    "invalid_result",
)

WORKER_TERMINAL_STATES: Set[str] = {
    "completed_within_bounds",
    "stopped_on_guardrail",
    "stopped_on_ambiguity",
    "stopped_on_insufficient_evidence",
    "invalid_result",
}

_TAINT_SOURCE_KINDS = {
    "http_param": ["frappe.form_dict", "frappe.request.json", "frappe.local.form_dict"],
    "cli_arg": ["sys.argv", "argparse", "click.argument", "click.option"],
    "event_hook": ["doc.as_dict()", "frappe.get_doc"],
    "file_read": ["open(", "json.load", "yaml.safe_load", "toml.load"],
    "env_var": ["os.environ", "os.getenv"],
    "external_api": ["requests.get", "requests.post", "httpx.get", "httpx.post"],
}
_TAINT_SOURCE_ORDER = {
    kind: index for index, kind in enumerate(_TAINT_SOURCE_KINDS)
}

SEMANTIC_SIGNAL_WEIGHTS = {
    "state_mutation": 2.4,
    "external_io": 2.2,
    "network_io": 2.6,
    "database_io": 2.8,
    "filesystem_io": 2.4,
    "process_io": 2.9,
    "config_access": 1.6,
    "input_boundary": 2.7,
    "output_boundary": 2.1,
    "validation_guard": 2.0,
    "auth_guard": 2.8,
    "error_handling": 1.7,
    "serialization": 1.4,
    "deserialization": 1.5,
    "time_or_randomness": 1.2,
    "dynamic_dispatch": 2.0,
    "orm_dynamic_load": 2.5,
    "concurrency": 2.6,
    "caching": 1.8,
}
SEMANTIC_SIGNAL_ORDER = {
    signal: index
    for index, signal in enumerate(
        sorted(
            SEMANTIC_SIGNAL_WEIGHTS,
            key=lambda item: (-SEMANTIC_SIGNAL_WEIGHTS[item], item),
        )
    )
}
SEMANTIC_SIDE_EFFECT_SIGNALS = {
    "external_io",
    "network_io",
    "database_io",
    "filesystem_io",
    "process_io",
    "state_mutation",
    "concurrency",
}
SEMANTIC_BOUNDARY_SIGNALS = {"input_boundary", "output_boundary"}
SEMANTIC_GUARD_SIGNALS = {"validation_guard", "auth_guard", "error_handling"}
SEMANTIC_EXTERNAL_IO_SIGNALS = {"network_io", "database_io", "filesystem_io", "process_io", "orm_dynamic_load", "caching"}
SEMANTIC_CRITICAL_SIGNALS = {
    "auth_guard",
    "caching",
    "concurrency",
    "database_io",
    "dynamic_dispatch",
    "external_io",
    "filesystem_io",
    "input_boundary",
    "network_io",
    "orm_dynamic_load",
    "output_boundary",
    "process_io",
    "state_mutation",
    "validation_guard",
}
BEHAVIORAL_FLOW_STEP_ORDER = {
    "input_boundary": 0,
    "deserialization": 1,
    "config_access": 2,
    "validation_guard": 3,
    "auth_guard": 4,
    "state_read": 5,
    "state_mutation": 6,
    "concurrency": 6,
    "orm_dynamic_load": 7,
    "caching": 7,
    "database_io": 7,
    "network_io": 8,
    "filesystem_io": 9,
    "process_io": 10,
    "serialization": 11,
    "output_boundary": 12,
    "error_handling": 13,
    "time_or_randomness": 14,
    "dynamic_dispatch": 15,
}
BEHAVIORAL_FLOW_STEP_SIGNALS = set(BEHAVIORAL_FLOW_STEP_ORDER)
SEMANTIC_AUTH_KEYWORDS = ("auth", "role", "permission", "scope", "token", "session", "principal", "credential")
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
SEMANTIC_VALIDATION_HINTS = (
    " not ",
    "null",
    "undefined",
    "blank",
    "empty",
    "invalid",
    "missing",
    "required",
    "isblank(",
    "isempty(",
    "hastext(",
)
SEMANTIC_EXECUTABLE_KINDS = {"function", "async_function", "method"}
SEMANTIC_CONTAINER_KINDS = {"class", "interface", "enum", "record", "module"}
QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "before",
    "does",
    "for",
    "how",
    "i",
    "in",
    "is",
    "of",
    "or",
    "the",
    "this",
    "to",
    "what",
    "where",
    "which",
}
QUERY_GENERIC_MENTION_TOKENS = {
    "read",
    "write",
    "path",
    "state",
    "check",
    "fetch",
    "load",
    "update",
    "change",
    "create",
    "open",
    "close",
    "request",
    "response",
}
QUERY_INTENT_KEYWORDS = {
    "explain_flow": ("how", "flow", "reach", "path", "through", "before", "after"),
    "debug": ("debug", "broken", "bug", "why"),
    "refactor": ("refactor", "simplify", "cleanup", "clean"),
    "architecture": ("architecture", "layer", "module", "dependency", "structure"),
    "auth": ("auth", "permission", "role", "token", "session", "authorize"),
    "validation": ("validate", "validation", "invalid", "guard", "check", "required"),
    "error_handling": ("error", "exception", "throw", "catch", "fail"),
    "data_access": ("db", "database", "repository", "query", "persistence", "jdbc"),
    "network": ("fetch", "http", "https", "api", "request", "network"),
    "filesystem": ("file", "disk", "fs", "path"),
    "side_effects": ("mutate", "mutation", "state", "assign", "update", "change", "write"),
    "ambiguity_resolution": ("ambiguous", "ambiguity", "unresolved", "candidate", "di", "dependency injection"),
}
QUERY_SIGNAL_KEYWORDS = {
    "auth_guard": ("auth", "permission", "role", "token", "session", "authorize"),
    "validation_guard": ("validate", "validation", "invalid", "guard", "check", "required"),
    "database_io": ("db", "database", "repository", "query", "persistence", "jdbc"),
    "network_io": ("fetch", "http", "https", "api", "request", "network"),
    "filesystem_io": ("file", "disk", "fs", "path"),
    "state_mutation": ("mutate", "mutation", "state", "assign", "update", "change", "write"),
    "input_boundary": ("input", "request", "handler", "controller"),
    "output_boundary": ("output", "response", "return json"),
    "error_handling": ("error", "exception", "throw", "catch", "fail"),
}

