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
}
SEMANTIC_BOUNDARY_SIGNALS = {"input_boundary", "output_boundary"}
SEMANTIC_GUARD_SIGNALS = {"validation_guard", "auth_guard", "error_handling"}
SEMANTIC_EXTERNAL_IO_SIGNALS = {"network_io", "database_io", "filesystem_io", "process_io"}
SEMANTIC_CRITICAL_SIGNALS = {
    "auth_guard",
    "database_io",
    "external_io",
    "filesystem_io",
    "input_boundary",
    "network_io",
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
    "database_io": 7,
    "network_io": 8,
    "filesystem_io": 9,
    "process_io": 10,
    "serialization": 11,
    "output_boundary": 12,
    "error_handling": 13,
    "time_or_randomness": 14,
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


@dataclass
class SymbolNode:
    node_id: str
    module: str
    qualname: str
    kind: str
    file: str
    lines: List[int]
    class_context: Optional[str]
    imports_modules: Dict[str, str]
    imports_symbols: Dict[str, str]
    member_types: Dict[str, str] = field(default_factory=dict)
    member_qualifiers: Dict[str, str] = field(default_factory=dict)
    language: str = "Python"
    package_name: str = ""
    declared_symbols: List[str] = field(default_factory=list)
    annotations: List[str] = field(default_factory=list)
    bean_name: str = ""
    is_abstract: bool = False
    di_primary: bool = False
    raw_imports: Set[str] = field(default_factory=set)
    resolved_imports: Set[str] = field(default_factory=set)
    external_imports: Set[str] = field(default_factory=set)
    unresolved_imports: Set[str] = field(default_factory=set)
    raw_calls: Set[str] = field(default_factory=set)
    raw_bases: Set[str] = field(default_factory=set)
    resolved_calls: Set[str] = field(default_factory=set)
    resolved_bases: Set[str] = field(default_factory=set)
    external_calls: Set[str] = field(default_factory=set)
    external_bases: Set[str] = field(default_factory=set)
    unresolved_calls: Set[str] = field(default_factory=set)
    unresolved_call_details: Dict[str, Dict[str, object]] = field(default_factory=dict)
    unresolved_bases: Set[str] = field(default_factory=set)
    recursive_self_call: bool = False
    ca: int = 0
    ce_internal: int = 0
    ce_external: int = 0
    ce_total: int = 0
    instability: float = 0.0
    instability_total: float = 0.0
    layer: int = 0
    scc_id: int = -1
    scc_size: int = 1
    pagerank: float = 0.0
    betweenness: float = 0.0
    git_commit_count: int = 0
    git_churn: int = 0
    git_hotness: float = 0.0
    coord: List[float] = field(default_factory=list)
    risk_score: float = 0.0
    reasons: List[str] = field(default_factory=list)
    heuristic_candidates: Dict[str, List[str]] = field(default_factory=dict)
    semantic_signals: List[str] = field(default_factory=list)
    semantic_evidence_spans: List[Dict[str, object]] = field(default_factory=list)
    semantic_summary: Dict[str, object] = field(default_factory=dict)
    semantic_weight: float = 0.0
    contained_semantic_signals: List[str] = field(default_factory=list)
    contained_semantic_refs: List[Dict[str, object]] = field(default_factory=list)
    contained_semantic_summary: Dict[str, object] = field(default_factory=dict)
    contained_semantic_weight: float = 0.0
    behavioral_flow_steps: List[Dict[str, object]] = field(default_factory=list)
    behavioral_flow_summary: Dict[str, object] = field(default_factory=dict)


@dataclass
class ResolutionOutcome:
    target: Optional[str]
    resolution_kind: str = ""
    confidence_score: float = 0.0
    confidence_label: str = ""
    resolution_reason: str = ""
    candidates: List[str] = field(default_factory=list)

    def to_payload(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "confidence_score": self.confidence_score,
            "confidence_label": self.confidence_label,
            "resolution_kind": self.resolution_kind,
            "resolution_reason": self.resolution_reason,
        }
        if self.candidates:
            payload["candidates"] = list(self.candidates)
        return payload


def path_to_module(rel_path: str) -> str:
    stem = rel_path[:-3] if rel_path.endswith(".py") else rel_path
    parts = stem.split(os.sep)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else stem


def language_slug(language: str) -> str:
    return language.lower().replace(" ", "_")


def source_group(rel_path: str, language: str, package_name: str = "") -> str:
    if package_name:
        return f"{language_slug(language)}.{package_name}"
    parent = Path(rel_path).parent.as_posix()
    if parent in {"", "."}:
        return language_slug(language)
    return f"{language_slug(language)}.{parent.replace('/', '.')}"


def source_qualname(rel_path: str) -> str:
    return Path(rel_path).name


def should_ignore_dir(name: str) -> bool:
    return name in IGNORE_DIRS or name.startswith(".") or name.startswith("llm_bundle") or name.startswith("ask_bundle")


def strip_json_comments(text: str) -> str:
    out: List[str] = []
    quote: Optional[str] = None
    escaped = False
    line_comment = False
    block_comment = False
    index = 0
    while index < len(text):
        char = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
                out.append(char)
        elif block_comment:
            if char == "*" and nxt == "/":
                block_comment = False
                index += 1
        elif quote:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        else:
            if char == "/" and nxt == "/":
                line_comment = True
                index += 1
            elif char == "/" and nxt == "*":
                block_comment = True
                index += 1
            else:
                out.append(char)
                if char in {'"', "'"}:
                    quote = char
        index += 1
    return "".join(out)


def load_relaxed_json(path: str) -> Dict[str, object]:
    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read()
    stripped = strip_json_comments(content)
    stripped = re.sub(r",(\s*[}\]])", r"\1", stripped)
    data = json.loads(stripped)
    return data if isinstance(data, dict) else {}


def resolve_relative_module(current_module: str, level: int, module: Optional[str]) -> Optional[str]:
    if level <= 0:
        return module
    base_parts = current_module.split(".")
    if len(base_parts) < level:
        return module
    prefix = ".".join(base_parts[:-level])
    if module:
        return f"{prefix}.{module}" if prefix else module
    return prefix or None


def stable_jitter(text: str, salt: str) -> float:
    digest = hashlib.sha1(f"{salt}:{text}".encode("utf-8")).hexdigest()
    value = int(digest[:8], 16) / 0xFFFFFFFF
    return (value - 0.5) * 3.0


def ref_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = ref_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Subscript):
        return ref_name(node.value)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "super":
            return "super()"
        return ref_name(node.func)
    return None


def call_name(func_node: ast.AST) -> Optional[str]:
    return ref_name(func_node)


class CallCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: Set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        name = call_name(node.func)
        if name:
            self.calls.add(name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


class ImportCollector(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.imports_modules: Dict[str, str] = {}
        self.imports_symbols: Dict[str, str] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname if alias.asname else alias.name.split(".")[0]
            self.imports_modules[local] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        resolved_mod = resolve_relative_module(self.module, node.level, node.module)
        for alias in node.names:
            if alias.name == "*":
                continue
            local = alias.asname if alias.asname else alias.name
            self.imports_symbols[local] = f"{resolved_mod}.{alias.name}" if resolved_mod else alias.name

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


class StructuralIntegrityAnalyzerV3:
    def __init__(
        self,
        root_dir: str,
        exclude_globs: Optional[List[str]] = None,
        filter_languages: Optional[List[str]] = None,
    ) -> None:
        self.root_dir = os.path.abspath(root_dir)
        self.nodes: Dict[str, SymbolNode] = {}
        self.adj: Dict[str, Set[str]] = defaultdict(set)
        self.edge_kinds: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
        self.parse_errors: List[Dict[str, str]] = []
        self.fq_to_id: Dict[str, str] = {}
        self.short_index: Dict[str, List[str]] = defaultdict(list)
        self.file_module_node: Dict[str, str] = {}
        self.file_top_level_symbol_index: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
        self.js_barrel_bindings: Dict[str, Dict[str, str]] = defaultdict(dict)
        self.js_barrel_star_specs: Dict[str, List[str]] = defaultdict(list)
        self.go_dir_to_node: Dict[str, str] = {}
        self.java_type_to_node: Dict[str, str] = {}
        self.java_member_to_node: Dict[str, str] = {}
        self.java_concrete_type_targets: Dict[str, List[str]] = defaultdict(list)
        self.rust_module_to_node: Dict[str, str] = {}
        self.edge_resolution: Dict[Tuple[str, str], ResolutionOutcome] = {}
        self.project_text_cache: Dict[str, Optional[str]] = {}
        self.project_lines_cache: Dict[str, List[str]] = {}
        self.git_hotspot_enabled: bool = False
        self.git_tracked_file_count: int = 0
        self.exclude_globs: List[str] = list(exclude_globs or [])
        self.filter_languages: Optional[Set[str]] = set(filter_languages) if filter_languages else None
        self.go_root_module: str = self._discover_go_root_module()
        self.js_resolver_configs: List[Dict[str, object]] = self._discover_js_resolver_configs()

    def run(
        self,
        top_n: int = 20,
        include_graph: bool = True,
        context_line_budget: int = 220,
        include_git_hotspots: bool = True,
        ask_query: str = "",
        ask_line_budget: int = 110,
    ) -> Dict[str, object]:
        self._scan_files()
        self._build_indices()
        self._resolve_edges()
        sccs, node_to_scc = self._tarjan_scc()
        self._apply_scc(node_to_scc, sccs)
        self._compute_layers(node_to_scc, sccs)
        self._compute_pagerank()
        self._compute_betweenness()
        self._compute_git_hotspots(enabled=include_git_hotspots)
        self._compute_coords()
        self._extract_semantic_signals()
        self._compute_risk_scores()
        self._extract_behavioral_flows()

        top_risks = self._top_risks(top_n)
        modules = self._module_report()
        cycles = [sorted(comp) for comp in sccs if len(comp) > 1]
        cycles = sorted(cycles, key=lambda c: (-len(c), c))
        recursive_symbols = self._recursive_symbols()
        llm_context_pack = self._build_llm_context_pack(top_risks, line_budget=context_line_budget)
        project_inventory = self._build_project_inventory()
        project_context_pack = self._build_project_context_pack(project_inventory)
        ask_context_pack = self._build_ask_context_pack(ask_query.strip(), line_budget=max(20, ask_line_budget)) if ask_query.strip() else None

        report: Dict[str, object] = {
            "meta": {
                "version": "3.52",
                "root_dir": self.root_dir,
                "node_count": len(self.nodes),
                "edge_count": sum(len(v) for v in self.adj.values()),
                "cycle_count": len(cycles),
                "recursive_symbol_count": len(recursive_symbols),
                "git_hotspots_enabled": self.git_hotspot_enabled,
                "git_tracked_file_count": self.git_tracked_file_count,
                "parse_error_count": len(self.parse_errors),
                "ask_query_present": bool(ask_context_pack),
            },
            "top_risks": top_risks,
            "module_report": modules,
            "project_inventory": project_inventory,
            "project_context_pack": project_context_pack,
            "cycles": cycles,
            "recursive_symbols": recursive_symbols,
            "llm_context_pack": llm_context_pack,
            "parse_errors": self.parse_errors,
        }
        if ask_context_pack is not None:
            report["ask_context_pack"] = ask_context_pack

        if include_graph:
            report["nodes"] = [self._node_payload(self.nodes[nid]) for nid in sorted(self.nodes)]
            report["edges"] = [
                [src, dst]
                for src in sorted(self.adj)
                for dst in sorted(self.adj[src])
            ]
            report["edge_details"] = [
                {
                    "source": src,
                    "target": dst,
                    "kinds": sorted(self.edge_kinds[(src, dst)]),
                    **(
                        self.edge_resolution[(src, dst)].to_payload()
                        if (src, dst) in self.edge_resolution
                        else self._resolution("heuristic", "Resolved edge without explicit provenance.", target=dst).to_payload()
                    ),
                }
                for src in sorted(self.adj)
                for dst in sorted(self.adj[src])
            ]

        return report

    def _scan_files(self) -> None:
        import fnmatch as _fnmatch
        norm_excludes = [p.rstrip("/\\") for p in self.exclude_globs]
        _siaignore = os.path.join(self.root_dir, ".siaignore")
        if os.path.isfile(_siaignore):
            try:
                with open(_siaignore, encoding="utf-8") as _fh:
                    for _raw in _fh:
                        _pat = _raw.strip()
                        if _pat and not _pat.startswith("#"):
                            norm_excludes.append(_pat.rstrip("/\\"))
            except OSError:
                pass
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if not should_ignore_dir(d)]
            if norm_excludes:
                dirs[:] = [
                    d for d in dirs
                    if not any(_fnmatch.fnmatch(d, pat) for pat in norm_excludes)
                ]
            for file_name in files:
                if file_name.endswith(".d.ts"):
                    continue
                suffix = Path(file_name).suffix.lower()
                full_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(full_path, self.root_dir)
                if norm_excludes and any(
                    _fnmatch.fnmatch(rel_path.replace(os.sep, "/"), pat)
                    or _fnmatch.fnmatch(file_name, pat)
                    for pat in norm_excludes
                ):
                    continue
                if suffix == ".py":
                    if self.filter_languages is None or "Python" in self.filter_languages:
                        self._parse_file(rel_path)
                elif suffix in LANGUAGE_BY_SUFFIX:
                    _lang = LANGUAGE_BY_SUFFIX[suffix]
                    if self.filter_languages is None or _lang in self.filter_languages:
                        self._parse_non_python_file(rel_path, _lang)

    def _discover_go_root_module(self) -> str:
        go_mod_path = os.path.join(self.root_dir, "go.mod")
        if not os.path.exists(go_mod_path):
            return ""
        try:
            with open(go_mod_path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except OSError:
            return ""
        match = re.search(r"(?m)^\s*module\s+(.+?)\s*$", content)
        return match.group(1).strip() if match else ""

    def _discover_js_resolver_configs(self) -> List[Dict[str, object]]:
        configs: List[Dict[str, object]] = []
        config_paths: List[str] = []
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if not should_ignore_dir(d)]
            for file_name in files:
                lower_name = file_name.lower()
                if lower_name == "jsconfig.json" or (lower_name.startswith("tsconfig") and lower_name.endswith(".json")):
                    config_paths.append(os.path.join(root, file_name))

        for config_path in sorted(config_paths):
            compiler_options = self._load_js_compiler_options(config_path, visited=set())
            config_dir = os.path.dirname(config_path)
            base_url = str(compiler_options.get("baseUrl", "."))
            base_dir = os.path.normpath(os.path.join(config_dir, base_url))
            raw_paths = compiler_options.get("paths", {})
            normalized_paths: Dict[str, List[str]] = {}
            if isinstance(raw_paths, dict):
                for alias_pattern, targets in raw_paths.items():
                    if not isinstance(alias_pattern, str):
                        continue
                    target_list = targets if isinstance(targets, list) else [targets]
                    resolved_targets: List[str] = []
                    for raw_target in target_list:
                        if not isinstance(raw_target, str):
                            continue
                        resolved_targets.append(os.path.normpath(os.path.join(base_dir, raw_target.replace("/", os.sep))))
                    if resolved_targets:
                        normalized_paths[alias_pattern] = resolved_targets
            configs.append(
                {
                    "config_file": Path(os.path.relpath(config_path, self.root_dir)).as_posix(),
                    "config_dir": config_dir,
                    "base_dir": base_dir,
                    "paths": normalized_paths,
                }
            )

        return sorted(configs, key=lambda item: len(str(item["config_dir"])), reverse=True)

    def _load_js_compiler_options(self, config_path: str, visited: Set[str]) -> Dict[str, object]:
        normalized = os.path.normpath(os.path.abspath(config_path))
        if normalized in visited or not os.path.exists(normalized):
            return {}
        visited.add(normalized)

        try:
            data = load_relaxed_json(normalized)
        except (OSError, json.JSONDecodeError):
            return {}

        merged: Dict[str, object] = {}
        extends_value = data.get("extends")
        if isinstance(extends_value, str):
            base_path = self._resolve_extended_js_config_path(normalized, extends_value)
            if base_path:
                merged.update(self._load_js_compiler_options(base_path, visited))

        current_options = data.get("compilerOptions", {})
        if isinstance(current_options, dict):
            if "baseUrl" in current_options:
                merged["baseUrl"] = current_options["baseUrl"]
            existing_paths = merged.get("paths", {})
            merged_paths = dict(existing_paths) if isinstance(existing_paths, dict) else {}
            raw_paths = current_options.get("paths", {})
            if isinstance(raw_paths, dict):
                for alias_pattern, targets in raw_paths.items():
                    merged_paths[alias_pattern] = targets
            if merged_paths:
                merged["paths"] = merged_paths

        return merged

    def _resolve_extended_js_config_path(self, config_path: str, extends_value: str) -> str:
        if not extends_value or not extends_value.startswith((".", "..")):
            return ""
        candidate = os.path.normpath(os.path.join(os.path.dirname(config_path), extends_value.replace("/", os.sep)))
        suffix = Path(candidate).suffix.lower()
        if suffix != ".json":
            candidate_json = candidate + ".json"
            if os.path.exists(candidate_json):
                return candidate_json
        if os.path.isdir(candidate):
            nested = os.path.join(candidate, "tsconfig.json")
            if os.path.exists(nested):
                return nested
        return candidate if os.path.exists(candidate) else ""

    def _parse_file(self, rel_path: str) -> None:
        full_path = os.path.join(self.root_dir, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8") as handle:
                source = handle.read()
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError as exc:
            self.parse_errors.append({"file": rel_path, "error": f"SyntaxError: {exc.msg} (line {exc.lineno})"})
            return
        except (OSError, UnicodeDecodeError) as exc:
            self.parse_errors.append({"file": rel_path, "error": f"OSError: {exc}"})
            return

        module = path_to_module(rel_path)
        imports_modules, imports_symbols = self._extract_imports(tree, module)
        self._collect_definitions(
            module=module,
            rel_path=rel_path,
            statements=tree.body,
            imports_modules=imports_modules,
            imports_symbols=imports_symbols,
            qual_prefix="",
            class_context=None,
        )

    def _extract_imports(self, tree: ast.Module, module: str) -> Tuple[Dict[str, str], Dict[str, str]]:
        imports_modules: Dict[str, str] = {}
        imports_symbols: Dict[str, str] = {}
        for stmt in tree.body:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    local = alias.asname if alias.asname else alias.name.split(".")[0]
                    imports_modules[local] = alias.name
            elif isinstance(stmt, ast.ImportFrom):
                resolved_mod = resolve_relative_module(module, stmt.level, stmt.module)
                for alias in stmt.names:
                    if alias.name == "*":
                        continue
                    local = alias.asname if alias.asname else alias.name
                    if resolved_mod:
                        imports_symbols[local] = f"{resolved_mod}.{alias.name}"
                    else:
                        imports_symbols[local] = alias.name
        return imports_modules, imports_symbols

    def _extract_local_imports(
        self,
        module: str,
        statements: Iterable[ast.stmt],
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        collector = ImportCollector(module)
        for stmt in statements:
            collector.visit(stmt)
        return collector.imports_modules, collector.imports_symbols

    def _merged_imports(
        self,
        base_modules: Dict[str, str],
        base_symbols: Dict[str, str],
        local_modules: Dict[str, str],
        local_symbols: Dict[str, str],
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        merged_modules = dict(base_modules)
        merged_modules.update(local_modules)
        merged_symbols = dict(base_symbols)
        merged_symbols.update(local_symbols)
        return merged_modules, merged_symbols

    def _collect_definitions(
        self,
        module: str,
        rel_path: str,
        statements: Iterable[ast.stmt],
        imports_modules: Dict[str, str],
        imports_symbols: Dict[str, str],
        qual_prefix: str,
        class_context: Optional[str],
    ) -> None:
        for stmt in statements:
            if isinstance(stmt, ast.ClassDef):
                class_qual = f"{qual_prefix}.{stmt.name}" if qual_prefix else stmt.name
                class_id = f"{module}:{class_qual}"
                local_modules, local_symbols = self._extract_local_imports(module, stmt.body)
                class_imports_modules, class_imports_symbols = self._merged_imports(
                    imports_modules,
                    imports_symbols,
                    local_modules,
                    local_symbols,
                )
                class_calls = self._calls_from_body(stmt.body)
                class_bases = {name for name in (ref_name(base) for base in stmt.bases) if name}
                self.nodes[class_id] = SymbolNode(
                    node_id=class_id,
                    module=module,
                    qualname=class_qual,
                    kind="class",
                    file=rel_path,
                    lines=[stmt.lineno, getattr(stmt, "end_lineno", stmt.lineno)],
                    class_context=class_qual,
                    imports_modules=class_imports_modules,
                    imports_symbols=class_imports_symbols,
                    raw_calls=class_calls,
                    raw_bases=class_bases,
                )
                self._collect_definitions(
                    module=module,
                    rel_path=rel_path,
                    statements=stmt.body,
                    imports_modules=imports_modules,
                    imports_symbols=imports_symbols,
                    qual_prefix=class_qual,
                    class_context=class_qual,
                )
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_qual = f"{qual_prefix}.{stmt.name}" if qual_prefix else stmt.name
                fn_id = f"{module}:{fn_qual}"
                local_modules, local_symbols = self._extract_local_imports(module, stmt.body)
                fn_imports_modules, fn_imports_symbols = self._merged_imports(
                    imports_modules,
                    imports_symbols,
                    local_modules,
                    local_symbols,
                )
                fn_calls = self._calls_from_body(stmt.body)
                kind = "async_function" if isinstance(stmt, ast.AsyncFunctionDef) else "function"
                self.nodes[fn_id] = SymbolNode(
                    node_id=fn_id,
                    module=module,
                    qualname=fn_qual,
                    kind=kind,
                    file=rel_path,
                    lines=[stmt.lineno, getattr(stmt, "end_lineno", stmt.lineno)],
                    class_context=class_context,
                    imports_modules=fn_imports_modules,
                    imports_symbols=fn_imports_symbols,
                    raw_calls=fn_calls,
                )

    def _parse_non_python_file(self, rel_path: str, language: str) -> None:
        content = self._read_project_text(rel_path)
        if content is None:
            self.parse_errors.append({"file": rel_path, "error": "OSError: Could not read source file"})
            return

        if language in {"JavaScript", "TypeScript"}:
            self._parse_js_like_file(rel_path, content, language)
            return
        if language == "Java":
            self._parse_java_file(rel_path, content, language)
            return
        if language == "CSharp":
            self._parse_csharp_file(rel_path, content, language)
            return
        if language == "Kotlin":
            self._parse_kotlin_file(rel_path, content, language)
            return
        if language == "PHP":
            self._parse_php_file(rel_path, content, language)
            return
        if language == "Ruby":
            self._parse_ruby_file(rel_path, content, language)
            return

        parser = {
            "Go": self._parse_go_module,
            "Rust": self._parse_rust_module,
            "CSharp": self._parse_csharp_module,
        }.get(language)
        if parser is None:
            return

        payload = parser(rel_path, content, language)
        self._register_non_python_node(rel_path, content, language, payload)

    def _register_non_python_node(
        self,
        rel_path: str,
        content: str,
        language: str,
        payload: Dict[str, object],
    ) -> str:
        module = payload.get("module") or source_group(rel_path, language)
        qualname = payload.get("qualname") or source_qualname(rel_path)
        node_id = f"{module}:{qualname}"
        line_count = max(1, len(content.splitlines()))
        lines = payload.get("lines")
        self.nodes[node_id] = SymbolNode(
            node_id=node_id,
            module=module,
            qualname=qualname,
            kind=str(payload.get("kind", "module")),
            file=rel_path,
            lines=list(lines) if isinstance(lines, list) and len(lines) == 2 else [1, line_count],
            class_context=str(payload.get("class_context")) if payload.get("class_context") else None,
            imports_modules=dict(payload.get("imports_modules", {})),
            imports_symbols=dict(payload.get("imports_symbols", {})),
            member_types=dict(payload.get("member_types", {})),
            member_qualifiers=dict(payload.get("member_qualifiers", {})),
            language=language,
            package_name=str(payload.get("package_name", "")),
            declared_symbols=list(payload.get("declared_symbols", [])),
            annotations=list(payload.get("annotations", [])),
            bean_name=str(payload.get("bean_name", "")),
            is_abstract=bool(payload.get("is_abstract", False)),
            di_primary=bool(payload.get("di_primary", False)),
            raw_imports=set(payload.get("raw_imports", set())),
            raw_calls=set(payload.get("raw_calls", set())),
            raw_bases=set(payload.get("raw_bases", set())),
        )
        return node_id

    def _parse_js_like_file(self, rel_path: str, content: str, language: str) -> None:
        module_payload = self._parse_js_like_module(rel_path, content, language)
        module_name = str(module_payload.get("module") or source_group(rel_path, language))
        file_imports_modules = dict(module_payload.get("imports_modules", {}))
        file_imports_symbols = dict(module_payload.get("imports_symbols", {}))
        file_key = Path(rel_path).as_posix()
        self.js_barrel_bindings[file_key] = dict(module_payload.get("export_bindings", {}))
        self.js_barrel_star_specs[file_key] = list(module_payload.get("export_star_specs", []))
        self._register_non_python_node(rel_path, content, language, module_payload)

        for symbol_payload in self._extract_js_like_symbol_payloads(
            rel_path,
            content,
            language,
            module_name,
            file_imports_modules,
            file_imports_symbols,
        ):
            self._register_non_python_node(rel_path, content, language, symbol_payload)

    def _parse_java_file(self, rel_path: str, content: str, language: str) -> None:
        module_payload = self._parse_java_module(rel_path, content, language)
        module_name = str(module_payload.get("module") or source_group(rel_path, language))
        package_name = str(module_payload.get("package_name", ""))
        file_imports_symbols = dict(module_payload.get("imports_symbols", {}))
        self._register_non_python_node(rel_path, content, language, module_payload)

        for symbol_payload in self._extract_java_symbol_payloads(
            rel_path,
            content,
            module_name,
            package_name,
            file_imports_symbols,
        ):
            self._register_non_python_node(rel_path, content, language, symbol_payload)

    def _parse_csharp_file(self, rel_path: str, content: str, language: str) -> None:
        module_payload = self._parse_csharp_module(rel_path, content, language)
        module_name = str(module_payload.get("module") or source_group(rel_path, language))
        namespace = str(module_payload.get("package_name", ""))
        file_imports_symbols = dict(module_payload.get("imports_symbols", {}))
        self._register_non_python_node(rel_path, content, language, module_payload)
        for symbol_payload in self._extract_csharp_symbol_payloads(
            rel_path, content, module_name, namespace, file_imports_symbols,
        ):
            self._register_non_python_node(rel_path, content, language, symbol_payload)

    def _parse_kotlin_file(self, rel_path: str, content: str, language: str) -> None:
        module_payload = self._parse_kotlin_module(rel_path, content, language)
        module_name = str(module_payload.get("module") or source_group(rel_path, language))
        package_name = str(module_payload.get("package_name", ""))
        file_imports_symbols = dict(module_payload.get("imports_symbols", {}))
        self._register_non_python_node(rel_path, content, language, module_payload)
        for symbol_payload in self._extract_kotlin_symbol_payloads(
            rel_path, content, module_name, package_name, file_imports_symbols,
        ):
            self._register_non_python_node(rel_path, content, language, symbol_payload)

    def _parse_php_file(self, rel_path: str, content: str, language: str) -> None:
        module_payload = self._parse_php_module(rel_path, content, language)
        module_name = str(module_payload.get("module") or source_group(rel_path, language))
        package_name = str(module_payload.get("package_name", ""))
        file_imports_symbols = dict(module_payload.get("imports_symbols", {}))
        self._register_non_python_node(rel_path, content, language, module_payload)
        for symbol_payload in self._extract_php_symbol_payloads(
            rel_path, content, module_name, package_name, file_imports_symbols,
        ):
            self._register_non_python_node(rel_path, content, language, symbol_payload)

    def _parse_ruby_file(self, rel_path: str, content: str, language: str) -> None:
        module_payload = self._parse_ruby_module(rel_path, content, language)
        module_name = str(module_payload.get("module") or source_group(rel_path, language))
        package_name = str(module_payload.get("package_name", ""))
        file_imports_symbols = dict(module_payload.get("imports_symbols", {}))
        self._register_non_python_node(rel_path, content, language, module_payload)
        for symbol_payload in self._extract_ruby_symbol_payloads(
            rel_path, content, module_name, package_name, file_imports_symbols,
        ):
            self._register_non_python_node(rel_path, content, language, symbol_payload)

    def _parse_js_like_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        function_names = re.findall(r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)\s*\(", content)
        class_names = re.findall(r"(?m)^\s*(?:export\s+)?class\s+([A-Za-z_]\w*)\b", content)
        arrow_names = re.findall(
            r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_]\w*)\s*=>",
            content,
        )
        type_names = re.findall(r"(?m)^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_]\w*)\b", content)
        declared_symbols = self._dedupe(function_names + class_names + arrow_names + type_names)[:20]

        raw_imports: Set[str] = set()
        imports_modules: Dict[str, str] = {}
        imports_symbols: Dict[str, str] = {}
        export_bindings: Dict[str, str] = {}
        export_star_specs: List[str] = []
        for lhs, spec in re.findall(r"(?m)^\s*import\s+(.+?)\s+from\s+['\"]([^'\"]+)['\"]", content):
            raw_imports.add(spec)
            self._parse_js_import_bindings(lhs, spec, imports_modules, imports_symbols)
        for spec in re.findall(r"(?m)^\s*import\s+['\"]([^'\"]+)['\"]", content):
            raw_imports.add(spec)
        for spec in re.findall(r"(?m)^\s*export\s+.+?\s+from\s+['\"]([^'\"]+)['\"]", content):
            raw_imports.add(spec)
        for alias, spec in re.findall(
            r"(?m)^\s*(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
            content,
        ):
            raw_imports.add(spec)
            imports_symbols[alias] = f"{spec}#default"
        for spec in re.findall(r"\brequire\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", content):
            raw_imports.add(spec)
        for spec in re.findall(r"\bimport\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", content):
            raw_imports.add(spec)
        for lhs, spec in re.findall(r"(?m)^\s*export\s+\{([^}]+)\}\s+from\s+['\"]([^'\"]+)['\"]", content):
            raw_imports.add(spec)
            for raw_item in lhs.split(","):
                item = raw_item.strip()
                if not item:
                    continue
                if " as " in item:
                    original, alias = [part.strip() for part in item.split(" as ", 1)]
                else:
                    original, alias = item, item
                export_bindings[alias] = f"{spec}#{original}"
        for alias, spec in re.findall(r"(?m)^\s*export\s+\*\s+as\s+([A-Za-z_$][\w$]*)\s+from\s+['\"]([^'\"]+)['\"]", content):
            raw_imports.add(spec)
            export_bindings[alias] = spec
        for spec in re.findall(r"(?m)^\s*export\s+\*\s+from\s+['\"]([^'\"]+)['\"]", content):
            raw_imports.add(spec)
            export_star_specs.append(spec)

        raw_bases: Set[str] = set(re.findall(r"\bclass\s+[A-Za-z_]\w*\s+extends\s+([A-Za-z_][\w$.]*)", content))
        return {
            "module": source_group(rel_path, language),
            "qualname": source_qualname(rel_path),
            "kind": "module",
            "imports_modules": imports_modules,
            "imports_symbols": imports_symbols,
            "declared_symbols": declared_symbols,
            "raw_imports": raw_imports,
            "raw_bases": raw_bases,
            "export_bindings": export_bindings,
            "export_star_specs": export_star_specs,
        }

    def _extract_js_like_symbol_payloads(
        self,
        rel_path: str,
        content: str,
        language: str,
        module_name: str,
        imports_modules: Dict[str, str],
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        depth_map = self._compute_js_like_brace_depths(content)
        payloads: List[Dict[str, object]] = []

        class_pattern = re.compile(r"(?m)^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)\b(?:\s+extends\s+([A-Za-z_$][\w$.]*))?")
        for match in class_pattern.finditer(content):
            if depth_map[match.start()] != 0:
                continue
            class_name = match.group(1)
            base_name = match.group(2)
            open_brace = content.find("{", match.end())
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(content, open_brace)
            if close_brace < 0:
                continue
            body = content[open_brace + 1:close_brace]
            member_types = self._extract_js_like_class_member_types(body)
            payloads.append(
                {
                    "module": module_name,
                    "qualname": class_name,
                    "kind": "class",
                    "class_context": class_name,
                    "imports_modules": dict(imports_modules),
                    "imports_symbols": dict(imports_symbols),
                    "member_types": member_types,
                    "declared_symbols": [],
                    "raw_calls": self._extract_js_like_top_level_calls(body),
                    "raw_bases": {base_name} if base_name else set(),
                    "lines": self._span_to_lines(content, match.start(), close_brace),
                }
            )
            payloads.extend(
                self._extract_js_like_method_payloads(
                    full_content=content,
                    class_body=body,
                    body_offset=open_brace + 1,
                    module_name=module_name,
                    class_name=class_name,
                    member_types=member_types,
                    imports_modules=imports_modules,
                    imports_symbols=imports_symbols,
                )
            )

        function_pattern = re.compile(r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(")
        for match in function_pattern.finditer(content):
            if depth_map[match.start()] != 0:
                continue
            name = match.group(1)
            open_brace = content.find("{", match.end())
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(content, open_brace)
            if close_brace < 0:
                continue
            body = content[open_brace + 1:close_brace]
            payloads.append(
                {
                    "module": module_name,
                    "qualname": name,
                    "kind": "function",
                    "imports_modules": dict(imports_modules),
                    "imports_symbols": dict(imports_symbols),
                    "declared_symbols": [],
                    "raw_calls": self._extract_js_like_calls(body),
                    "raw_bases": set(),
                    "lines": self._span_to_lines(content, match.start(), close_brace),
                }
            )

        arrow_pattern = re.compile(
            r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
        )
        for match in arrow_pattern.finditer(content):
            if depth_map[match.start()] != 0:
                continue
            name = match.group(1)
            idx = match.end()
            while idx < len(content) and content[idx].isspace():
                idx += 1
            if idx < len(content) and content[idx] == "{":
                close_brace = self._find_matching_brace(content, idx)
                if close_brace < 0:
                    continue
                body = content[idx + 1:close_brace]
                end_index = close_brace
            else:
                end_index = content.find("\n", idx)
                if end_index < 0:
                    end_index = len(content) - 1
                body = content[idx:end_index + 1]
            payloads.append(
                {
                    "module": module_name,
                    "qualname": name,
                    "kind": "function",
                    "imports_modules": dict(imports_modules),
                    "imports_symbols": dict(imports_symbols),
                    "declared_symbols": [],
                    "raw_calls": self._extract_js_like_calls(body),
                    "raw_bases": set(),
                    "lines": self._span_to_lines(content, match.start(), end_index),
                }
            )

        return payloads

    def _extract_js_like_method_payloads(
        self,
        full_content: str,
        class_body: str,
        body_offset: int,
        module_name: str,
        class_name: str,
        member_types: Dict[str, str],
        imports_modules: Dict[str, str],
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []
        depth_map = self._compute_js_like_brace_depths(class_body)
        seen: Set[Tuple[str, int, int]] = set()

        method_pattern = re.compile(
            r"(?m)^\s*(?:@[A-Za-z_$][\w$]*(?:\([^)]*\))?\s*)*"
            r"(?:(?:public|private|protected|static|async|abstract|readonly|override|get|set)\s+)*"
            r"([A-Za-z_$][\w$]*)\s*(?:<[^>{}]+>\s*)?\([^;{}=]*\)\s*(?::\s*[^({}=;]+)?\s*\{"
        )
        for match in method_pattern.finditer(class_body):
            if depth_map[match.start()] != 0:
                continue
            method_name = match.group(1)
            open_brace = class_body.find("{", match.end() - 1)
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(class_body, open_brace)
            if close_brace < 0:
                continue
            body = class_body[open_brace + 1:close_brace]
            start_index = body_offset + match.start()
            end_index = body_offset + close_brace
            marker = (method_name, start_index, end_index)
            if marker in seen:
                continue
            seen.add(marker)
            payloads.append(
                {
                    "module": module_name,
                    "qualname": f"{class_name}.{method_name}",
                    "kind": "method",
                    "class_context": class_name,
                    "imports_modules": dict(imports_modules),
                    "imports_symbols": dict(imports_symbols),
                    "member_types": dict(member_types),
                    "declared_symbols": [],
                    "raw_calls": self._extract_js_like_calls(body),
                    "raw_bases": set(),
                    "lines": self._span_to_lines(full_content, start_index, end_index),
                }
            )

        arrow_pattern = re.compile(
            r"(?m)^\s*(?:@[A-Za-z_$][\w$]*(?:\([^)]*\))?\s*)*"
            r"(?:(?:public|private|protected|static|readonly|override)\s+)*"
            r"([A-Za-z_$][\w$]*)\s*(?::\s*[^=;]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
        )
        for match in arrow_pattern.finditer(class_body):
            if depth_map[match.start()] != 0:
                continue
            method_name = match.group(1)
            idx = match.end()
            while idx < len(class_body) and class_body[idx].isspace():
                idx += 1
            if idx < len(class_body) and class_body[idx] == "{":
                close_brace = self._find_matching_brace(class_body, idx)
                if close_brace < 0:
                    continue
                body = class_body[idx + 1:close_brace]
                end_index = body_offset + close_brace
            else:
                close_delims = [pos for pos in (class_body.find("\n", idx), class_body.find(";", idx)) if pos >= 0]
                close_index = min(close_delims) if close_delims else len(class_body) - 1
                body = class_body[idx:close_index + 1]
                end_index = body_offset + close_index
            start_index = body_offset + match.start()
            marker = (method_name, start_index, end_index)
            if marker in seen:
                continue
            seen.add(marker)
            payloads.append(
                {
                    "module": module_name,
                    "qualname": f"{class_name}.{method_name}",
                    "kind": "method",
                    "class_context": class_name,
                    "imports_modules": dict(imports_modules),
                    "imports_symbols": dict(imports_symbols),
                    "member_types": dict(member_types),
                    "declared_symbols": [],
                    "raw_calls": self._extract_js_like_calls(body),
                    "raw_bases": set(),
                    "lines": self._span_to_lines(full_content, start_index, end_index),
                }
            )

        return payloads

    def _clean_js_like_type(self, raw_type: str, initializer: str = "") -> str:
        cleaned = raw_type.strip()
        if not cleaned:
            match = re.search(r"\bnew\s+([A-Za-z_$][\w$.]*)\s*\(", initializer)
            cleaned = match.group(1) if match else ""
        cleaned = re.sub(r"<.*?>", "", cleaned)
        cleaned = cleaned.replace("[]", " ")
        cleaned = cleaned.replace("readonly", " ")
        for splitter in ("|", "&"):
            if splitter in cleaned:
                cleaned = cleaned.split(splitter, 1)[0]
        tokens = re.findall(r"[A-Za-z_$][\w$]*", cleaned)
        if not tokens:
            return ""
        candidate = tokens[-1]
        if candidate in JS_NON_SYMBOL_TYPES:
            return ""
        return candidate

    def _extract_js_like_param_types(self, params_spec: str) -> Dict[str, str]:
        params: Dict[str, str] = {}
        for raw_param in params_spec.split(","):
            param = raw_param.strip()
            if not param:
                continue
            param = re.sub(r"^\.\.\.", "", param).strip()
            parts = re.match(
                r"(?:(?:public|private|protected|readonly)\s+)*([A-Za-z_$][\w$]*)\s*(?::\s*([^=]+))?",
                param,
            )
            if not parts:
                continue
            variable_name = parts.group(1)
            variable_type = self._clean_js_like_type(parts.group(2) or "")
            if variable_type:
                params[variable_name] = variable_type
        return params

    def _extract_js_like_class_member_types(self, class_body: str) -> Dict[str, str]:
        member_types: Dict[str, str] = {}
        depth_map = self._compute_js_like_brace_depths(class_body)

        field_pattern = re.compile(
            r"(?m)^\s*(?:(?:public|private|protected|readonly|static|declare|override)\s+)*"
            r"([A-Za-z_$][\w$]*)\s*(?::\s*([^=;]+))?\s*(?:=\s*([^;]+))?;"
        )
        for match in field_pattern.finditer(class_body):
            if depth_map[match.start()] != 0:
                continue
            member_name = match.group(1)
            member_type = self._clean_js_like_type(match.group(2) or "", match.group(3) or "")
            if member_type:
                member_types[member_name] = member_type

        ctor_pattern = re.compile(r"(?m)^\s*constructor\s*\(([^)]*)\)\s*\{")
        for match in ctor_pattern.finditer(class_body):
            if depth_map[match.start()] != 0:
                continue
            ctor_param_types = self._extract_js_like_param_types(match.group(1) or "")
            for raw_param in (match.group(1) or "").split(","):
                param = raw_param.strip()
                property_match = re.match(
                    r"(?:(?:public|private|protected|readonly)\s+)+([A-Za-z_$][\w$]*)\s*(?::\s*([^=]+))?",
                    param,
                )
                if not property_match:
                    continue
                property_type = self._clean_js_like_type(property_match.group(2) or "")
                if property_type:
                    member_types[property_match.group(1)] = property_type

            open_brace = class_body.find("{", match.end() - 1)
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(class_body, open_brace)
            if close_brace < 0:
                continue
            body = class_body[open_brace + 1:close_brace]
            for field_name, type_name in re.findall(r"\bthis\.([A-Za-z_$][\w$]*)\s*=\s*new\s+([A-Za-z_$][\w$.]*)\s*\(", body):
                cleaned = self._clean_js_like_type(type_name)
                if cleaned:
                    member_types[field_name] = cleaned
            for field_name, source_name in re.findall(r"\bthis\.([A-Za-z_$][\w$]*)\s*=\s*([A-Za-z_$][\w$]*)\s*;", body):
                if source_name in ctor_param_types:
                    member_types[field_name] = ctor_param_types[source_name]

        return member_types

    def _compute_js_like_brace_depths(self, text: str) -> List[int]:
        depths = [0] * (len(text) + 1)
        depth = 0
        quote: Optional[str] = None
        line_comment = False
        block_comment = False
        escaped = False
        index = 0
        while index < len(text):
            depths[index] = depth
            char = text[index]
            nxt = text[index + 1] if index + 1 < len(text) else ""

            if line_comment:
                if char == "\n":
                    line_comment = False
            elif block_comment:
                if char == "*" and nxt == "/":
                    block_comment = False
                    index += 1
            elif quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
            else:
                if char == "/" and nxt == "/":
                    line_comment = True
                    index += 1
                elif char == "/" and nxt == "*":
                    block_comment = True
                    index += 1
                elif char in {"'", '"', "`"}:
                    quote = char
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth = max(0, depth - 1)
            index += 1

        depths[len(text)] = depth
        return depths

    def _find_matching_brace(self, text: str, open_index: int) -> int:
        depth = 0
        quote: Optional[str] = None
        line_comment = False
        block_comment = False
        escaped = False
        index = open_index
        while index < len(text):
            char = text[index]
            nxt = text[index + 1] if index + 1 < len(text) else ""

            if line_comment:
                if char == "\n":
                    line_comment = False
            elif block_comment:
                if char == "*" and nxt == "/":
                    block_comment = False
                    index += 1
            elif quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
            else:
                if char == "/" and nxt == "/":
                    line_comment = True
                    index += 1
                elif char == "/" and nxt == "*":
                    block_comment = True
                    index += 1
                elif char in {"'", '"', "`"}:
                    quote = char
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return index
            index += 1
        return -1

    def _span_to_lines(self, text: str, start_index: int, end_index: int) -> List[int]:
        start_line = text.count("\n", 0, start_index) + 1
        end_line = text.count("\n", 0, end_index + 1) + 1
        return [start_line, end_line]

    def _extract_js_like_top_level_calls(self, fragment: str) -> Set[str]:
        depth_map = self._compute_js_like_brace_depths(fragment)
        filtered = "".join(char if depth_map[index] == 0 else " " for index, char in enumerate(fragment))
        return self._extract_js_like_calls(filtered)

    def _extract_js_like_calls(self, fragment: str) -> Set[str]:
        cleaned = re.sub(r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+[A-Za-z_$][\w$]*\s*\([^)]*\)\s*\{", "", fragment)
        cleaned = re.sub(r"(?m)^\s*(?:public|private|protected|static|async|get|set|\s)*[A-Za-z_$][\w$]*\s*\([^)]*\)\s*\{", "", cleaned)
        cleaned = re.sub(
            r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>\s*\{?",
            "",
            cleaned,
        )

        calls: Set[str] = set()
        for match in re.finditer(r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*\(", cleaned):
            name = match.group(1)
            if name in JS_CALL_KEYWORDS:
                continue
            calls.add(name)
        for match in re.finditer(r"\bnew\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*\(", cleaned):
            calls.add(match.group(1))
        for match in re.finditer(r"<([A-Z][A-Za-z0-9_$]*)\b", cleaned):
            calls.add(match.group(1))
        return calls

    def _parse_js_import_bindings(
        self,
        lhs: str,
        spec: str,
        imports_modules: Dict[str, str],
        imports_symbols: Dict[str, str],
    ) -> None:
        lhs = lhs.strip()
        if not lhs:
            return
        default_match = re.match(r"^([A-Za-z_$][\w$]*)\s*(?:,|$)", lhs)
        if default_match and not lhs.startswith("{") and not lhs.startswith("*"):
            imports_symbols[default_match.group(1)] = f"{spec}#default"
        namespace_match = re.search(r"\*\s+as\s+([A-Za-z_$][\w$]*)", lhs)
        if namespace_match:
            imports_modules[namespace_match.group(1)] = spec
        named_match = re.search(r"\{([^}]+)\}", lhs)
        if not named_match:
            return
        for raw_item in named_match.group(1).split(","):
            item = raw_item.strip()
            if not item:
                continue
            if " as " in item:
                original, alias = [part.strip() for part in item.split(" as ", 1)]
                imports_symbols[alias] = f"{spec}#{original}"
            else:
                imports_symbols[item] = f"{spec}#{item}"

    def _parse_go_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        funcs = re.findall(r"(?m)^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z_]\w*)\s*\(", content)
        types = re.findall(r"(?m)^\s*type\s+([A-Za-z_]\w*)\s+(?:struct|interface|map|chan|func|\[\])", content)
        package_match = re.search(r"(?m)^\s*package\s+([A-Za-z_]\w*)\s*$", content)
        package_name = package_match.group(1) if package_match else ""

        imports_modules: Dict[str, str] = {}
        raw_imports: Set[str] = set()
        for alias, spec in re.findall(
            r'(?m)^\s*import\s+(?:([A-Za-z_]\w*|_|\.)\s+)?\"([^\"]+)\"',
            content,
        ):
            raw_imports.add(spec)
            if alias:
                imports_modules[alias] = spec
        for block in re.findall(r"(?ms)^\s*import\s*\((.*?)\)", content):
            for alias, spec in re.findall(r'(?m)^\s*(?:([A-Za-z_]\w*|_|\.)\s+)?\"([^\"]+)\"', block):
                raw_imports.add(spec)
                if alias:
                    imports_modules[alias] = spec

        return {
            "module": source_group(rel_path, language),
            "qualname": source_qualname(rel_path),
            "kind": "module",
            "imports_modules": imports_modules,
            "imports_symbols": {},
            "package_name": package_name,
            "declared_symbols": self._dedupe(funcs + types)[:20],
            "raw_imports": raw_imports,
            "raw_bases": set(),
        }

    def _parse_java_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        package_match = re.search(r"(?m)^\s*package\s+([A-Za-z0-9_.]+)\s*;", content)
        package_name = package_match.group(1) if package_match else ""
        types = re.findall(r"(?m)^\s*(?:public\s+)?(?:class|interface|enum|record)\s+([A-Za-z_]\w*)\b", content)
        methods = [
            name
            for name in re.findall(
                r"(?m)^\s*(?:public|protected|private)?\s*(?:static\s+)?[A-Za-z0-9_<>\[\], ?]+\s+([A-Za-z_]\w*)\s*\(",
                content,
            )
            if name not in {"if", "for", "while", "switch", "catch", "return", "new"}
        ]
        raw_imports: Set[str] = set()
        imports_symbols: Dict[str, str] = {}
        for spec in re.findall(r"(?m)^\s*import\s+(?:static\s+)?([A-Za-z0-9_.*]+)\s*;", content):
            raw_imports.add(spec)
            if not spec.endswith(".*"):
                imports_symbols[spec.rsplit(".", 1)[-1]] = spec

        raw_bases: Set[str] = set()
        for base in re.findall(
            r"\b(?:class|record)\s+[A-Za-z_]\w*(?:\s*<[^>{}]+>)?\s+extends\s+([A-Za-z0-9_$.<>]+)",
            content,
        ):
            raw_bases.add(re.sub(r"<.*?>", "", base).strip())
        for match in re.findall(
            r"\b(?:class|record)\s+[A-Za-z_]\w*(?:\s*<[^>{}]+>)?\s+implements\s+([A-Za-z0-9_$.<>,\s]+)",
            content,
        ):
            for raw_item in self._split_java_csv(match):
                item = re.sub(r"<.*?>", "", raw_item).strip()
                if item:
                    raw_bases.add(item)
        for match in re.findall(
            r"\binterface\s+[A-Za-z_]\w*(?:\s*<[^>{}]+>)?\s+extends\s+([A-Za-z0-9_$.<>,\s]+)",
            content,
        ):
            for raw_item in self._split_java_csv(match):
                item = re.sub(r"<.*?>", "", raw_item).strip()
                if item:
                    raw_bases.add(item)

        return {
            "module": source_group(rel_path, language, package_name),
            "qualname": source_qualname(rel_path),
            "kind": "module",
            "imports_modules": {},
            "imports_symbols": imports_symbols,
            "package_name": package_name,
            "declared_symbols": self._dedupe(types + methods)[:20],
            "raw_calls": set(),
            "raw_imports": raw_imports,
            "raw_bases": raw_bases,
        }

    def _parse_csharp_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        ns_match = re.search(r"(?m)^namespace\s+([\w.]+)\s*;", content)
        if not ns_match:
            ns_match = re.search(r"(?m)^namespace\s+([\w.]+)\s*\{", content)
        namespace = ns_match.group(1) if ns_match else ""

        raw_imports: Set[str] = set(
            re.findall(r"(?m)^\s*using\s+(?:static\s+)?(?:\w+\s*=\s*)?([\w.]+)\s*;", content)
        )

        declared_symbols = re.findall(
            r"(?m)^\s*(?:(?:public|internal|private|protected|static|abstract|sealed|partial)\s+)*"
            r"(?:class|interface|enum|struct|record)\s+([A-Za-z_]\w*)\b",
            content,
        )[:20]

        raw_bases: Set[str] = set()
        for tail in re.findall(r"(?:class|struct)\s+\w+\s*:\s*([A-Za-z_][\w,\s<>?]*?)\s*(?:\{|where)", content):
            for part in re.split(r",\s*", tail):
                part = re.sub(r"<.*?>", "", part).strip()
                if part and re.match(r"[A-Za-z_]\w*", part):
                    raw_bases.add(part)

        return {
            "module": source_group(rel_path, language, namespace),
            "qualname": source_qualname(rel_path),
            "kind": "module",
            "package_name": namespace,
            "imports_modules": {},
            "imports_symbols": {},
            "declared_symbols": declared_symbols,
            "raw_imports": raw_imports,
            "raw_bases": raw_bases,
        }

    def _parse_kotlin_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        pkg_match = re.search(r"(?m)^\s*package\s+([\w.]+)", content)
        package_name = pkg_match.group(1).strip() if pkg_match else ""

        raw_imports: Set[str] = set(
            re.findall(r"(?m)^\s*import\s+([\w.*]+)", content)
        )

        declared_symbols = re.findall(
            r"(?m)^\s*(?:(?:public|private|protected|internal|open|abstract|sealed|data|"
            r"value|inline|companion|inner|override|suspend)\s+)*"
            r"(?:class|interface|object|enum\s+class|fun)\s+([A-Za-z_]\w*)\b",
            content,
        )[:20]

        raw_bases: Set[str] = set()
        for tail in re.findall(
            r"(?:class|object)\s+\w+(?:\s*<[^>]*>)?(?:\s*\([^)]*\))?\s*:\s*([A-Za-z_][\w(),\s<>?]*?)\s*(?:\{|$)",
            content,
        ):
            for part in re.split(r",\s*", tail):
                part = re.sub(r"<.*?>|\(.*?\)", "", part).strip()
                if part and re.match(r"[A-Za-z_]\w*", part):
                    raw_bases.add(part)

        return {
            "module": source_group(rel_path, language, package_name),
            "qualname": source_qualname(rel_path),
            "kind": "module",
            "package_name": package_name,
            "imports_modules": {},
            "imports_symbols": {},
            "declared_symbols": declared_symbols,
            "raw_imports": raw_imports,
            "raw_bases": raw_bases,
        }

    def _parse_php_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        ns_match = re.search(r"(?m)^\s*namespace\s+([\w\\]+)\s*[;{]", content)
        package_name = ns_match.group(1).replace("\\", ".") if ns_match else ""

        raw_imports: Set[str] = set(
            m.replace("\\", ".")
            for m in re.findall(
                r"(?m)^\s*use\s+(?:function\s+|const\s+)?([\w\\]+)(?:\s+as\s+\w+)?\s*;",
                content,
            )
        )

        declared_symbols = re.findall(
            r"(?m)^\s*(?:(?:abstract|final|readonly)\s+)*"
            r"(?:class|interface|trait|enum)\s+([A-Za-z_]\w*)\b",
            content,
        )[:20]

        raw_bases: Set[str] = set()
        for extend_m in re.findall(r"\bextends\s+([\w\\]+)", content):
            raw_bases.add(extend_m.replace("\\", ".").split(".")[-1])
        for impl_m in re.findall(r"\bimplements\s+([\w\\,\s]+?)(?:\{|$)", content):
            for part in re.split(r",\s*", impl_m.strip()):
                clean = part.strip().replace("\\", ".").split(".")[-1]
                if clean:
                    raw_bases.add(clean)

        return {
            "module": source_group(rel_path, language, package_name),
            "qualname": source_qualname(rel_path),
            "kind": "module",
            "package_name": package_name,
            "imports_modules": {},
            "imports_symbols": {},
            "declared_symbols": declared_symbols,
            "raw_imports": raw_imports,
            "raw_bases": raw_bases,
        }

    def _parse_ruby_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        raw_imports: Set[str] = set()
        for m in re.findall(
            r"(?m)^\s*require(?:_relative)?\s+['\"]([^'\"]+)['\"]", content
        ):
            raw_imports.add(m.rsplit("/", 1)[-1].replace("-", "_"))

        declared_symbols = re.findall(
            r"(?m)^\s*(?:class|module)\s+([A-Z]\w*(?:::[A-Z]\w*)*)", content
        )[:20]

        raw_bases: Set[str] = set()
        for base in re.findall(r"\bclass\s+\w+\s*<\s*([A-Z]\w*(?:::[A-Z]\w*)*)", content):
            raw_bases.add(base.split("::")[-1])

        pkg_match = re.search(r"(?m)^\s*module\s+([A-Z]\w*(?:::[A-Z]\w*)*)", content)
        package_name = pkg_match.group(1).replace("::", ".") if pkg_match else ""

        return {
            "module": source_group(rel_path, language, package_name),
            "qualname": source_qualname(rel_path),
            "kind": "module",
            "package_name": package_name,
            "imports_modules": {},
            "imports_symbols": {},
            "declared_symbols": declared_symbols,
            "raw_imports": raw_imports,
            "raw_bases": raw_bases,
        }

    def _extract_java_symbol_payloads(
        self,
        rel_path: str,
        content: str,
        module_name: str,
        package_name: str,
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []
        depth_map = self._compute_js_like_brace_depths(content)
        type_pattern = re.compile(
            r"(?m)^\s*(?:public|protected|private|abstract|final|static\s+)*\s*(class|interface|enum|record)\s+([A-Za-z_]\w*)\b([^{]*)\{"
        )

        for match in type_pattern.finditer(content):
            if depth_map[match.start()] != 0:
                continue
            type_kind = match.group(1)
            type_name = match.group(2)
            tail = match.group(3) or ""
            open_brace = content.find("{", match.end() - 1)
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(content, open_brace)
            if close_brace < 0:
                continue

            raw_bases: Set[str] = set()
            extends_match = re.search(r"\bextends\s+([A-Za-z0-9_$.<>]+)", tail)
            if extends_match:
                raw_bases.add(re.sub(r"<.*?>", "", extends_match.group(1)).strip())
            implements_match = re.search(r"\bimplements\s+([A-Za-z0-9_$.<>,\s]+)", tail)
            if implements_match:
                for raw_item in self._split_java_csv(implements_match.group(1)):
                    item = re.sub(r"<.*?>", "", raw_item).strip()
                    if item:
                        raw_bases.add(item)

            body = content[open_brace + 1:close_brace]
            field_types, field_qualifiers = self._extract_java_declared_members(body, top_level_only=True)
            constructor_field_qualifiers = self._extract_java_constructor_field_qualifiers(body, type_name, field_types)
            for field_name, qualifier in constructor_field_qualifiers.items():
                field_qualifiers.setdefault(field_name, qualifier)
            annotation_block = self._extract_java_leading_annotation_block(content, match.start())
            annotations, bean_name, di_primary = self._extract_java_component_metadata(type_name, annotation_block)
            payloads.append(
                {
                    "module": module_name,
                    "qualname": type_name,
                    "kind": "class" if type_kind in {"class", "record"} else type_kind,
                    "class_context": type_name,
                    "imports_modules": {},
                    "imports_symbols": dict(imports_symbols),
                    "member_types": field_types,
                    "member_qualifiers": field_qualifiers,
                    "package_name": package_name,
                    "declared_symbols": [],
                    "annotations": annotations,
                    "bean_name": bean_name,
                    "is_abstract": type_kind == "class" and bool(re.search(r"\babstract\b", match.group(0))),
                    "di_primary": di_primary,
                    "raw_calls": self._extract_java_top_level_calls(body),
                    "raw_bases": raw_bases,
                    "lines": self._span_to_lines(content, match.start(), close_brace),
                }
            )

            for method_payload in self._extract_java_method_payloads(
                content,
                body,
                body_offset=open_brace + 1,
                module_name=module_name,
                package_name=package_name,
                class_name=type_name,
                field_types=field_types,
                field_qualifiers=field_qualifiers,
                imports_symbols=imports_symbols,
            ):
                payloads.append(method_payload)

        return payloads

    def _extract_csharp_symbol_payloads(
        self,
        rel_path: str,
        content: str,
        module_name: str,
        namespace: str,
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []
        depth_map = self._compute_js_like_brace_depths(content)
        type_pattern = re.compile(
            r"(?m)^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|readonly)\s+)*"
            r"(class|interface|enum|struct|record)\s+([A-Za-z_]\w*)\b([^{]*)\{"
        )
        method_pattern = re.compile(
            r"(?m)^\s*(?:(?:public|private|protected|internal|static|abstract|virtual|override|"
            r"async|sealed|new|extern|partial)\s+)*"
            r"(?:[\w<>\[\]?,.\s]+?)\s+([A-Za-z_]\w*)\s*(?:<[^>]*>)?\s*\([^)]*\)\s*"
            r"(?:where\s+[\w\s:,<>]+?)?\s*\{"
        )

        for type_match in type_pattern.finditer(content):
            if depth_map[type_match.start()] > 1:
                continue
            type_kind = type_match.group(1)
            type_name = type_match.group(2)
            tail = type_match.group(3) or ""

            open_brace = content.find("{", type_match.end() - 1)
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(content, open_brace)
            if close_brace < 0:
                continue

            raw_bases: Set[str] = set()
            colon_match = re.search(r":\s*([\w,\s<>?]+?)(?:\{|where\b)", tail + " {")
            if colon_match:
                for part in re.split(r",\s*", colon_match.group(1)):
                    part = re.sub(r"<.*?>", "", part).strip()
                    if part and re.match(r"[A-Za-z_]\w*", part):
                        raw_bases.add(part)

            body = content[open_brace + 1:close_brace]
            field_types: Dict[str, str] = {}
            for fm in re.finditer(
                r"(?m)^\s*(?:(?:private|public|protected|internal|static|readonly)\s+)+"
                r"([\w<>?,.\s]+?)\s+([A-Za-z_]\w*)\s*[;={]",
                body,
            ):
                ftype = re.sub(r"\s+", " ", fm.group(1)).strip()
                fname = fm.group(2).strip()
                if fname and ftype and ftype not in {"return", "var", "new"}:
                    field_types[fname] = ftype

            annotation_block = self._extract_java_leading_annotation_block(content, type_match.start())
            annotations = [
                item.strip()
                for item in re.findall(r"\[([A-Za-z_]\w*(?:\([^)]*\))?)\]", annotation_block)
            ]

            payloads.append(
                {
                    "module": module_name,
                    "qualname": type_name,
                    "kind": "class" if type_kind in {"class", "struct", "record"} else type_kind,
                    "class_context": type_name,
                    "package_name": namespace,
                    "imports_symbols": dict(imports_symbols),
                    "member_types": field_types,
                    "member_qualifiers": {},
                    "declared_symbols": [],
                    "annotations": annotations,
                    "bean_name": "",
                    "is_abstract": bool(re.search(r"\babstract\b", type_match.group(0))),
                    "di_primary": False,
                    "raw_calls": set(),
                    "raw_bases": raw_bases,
                    "lines": self._span_to_lines(content, type_match.start(), close_brace),
                }
            )

            body_depth_map = self._compute_js_like_brace_depths(body)
            for method_match in method_pattern.finditer(body):
                method_name = method_match.group(1)
                if method_name in {"if", "for", "while", "foreach", "switch", "catch", "using", "lock", "return", "await", "new", "throw", "var", "get", "set"}:
                    continue
                if body_depth_map[method_match.start()] != 0:
                    continue
                m_open = body.find("{", method_match.end() - 1)
                if m_open < 0:
                    continue
                m_close = self._find_matching_brace(body, m_open)
                if m_close < 0:
                    continue
                method_body = body[m_open + 1:m_close]
                raw_calls: Set[str] = set()
                for cm in re.finditer(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\(", method_body):
                    name = cm.group(1)
                    if not re.match(r"^(?:if|for|while|foreach|switch|catch|using|lock|return|await|new|throw|var|get|set)$", name):
                        raw_calls.add(name)
                m_annotation_block = self._extract_java_leading_annotation_block(body, method_match.start())
                m_annotations = [
                    item.strip()
                    for item in re.findall(r"\[([A-Za-z_]\w*(?:\([^)]*\))?)\]", m_annotation_block)
                ]
                abs_start = open_brace + 1 + method_match.start()
                abs_end = open_brace + 1 + m_close
                payloads.append(
                    {
                        "module": module_name,
                        "qualname": f"{type_name}.{method_name}",
                        "kind": "method",
                        "class_context": type_name,
                        "package_name": namespace,
                        "imports_symbols": dict(imports_symbols),
                        "member_types": dict(field_types),
                        "member_qualifiers": {},
                        "declared_symbols": [],
                        "annotations": m_annotations,
                        "bean_name": "",
                        "is_abstract": False,
                        "di_primary": False,
                        "raw_calls": raw_calls,
                        "raw_bases": set(),
                        "lines": self._span_to_lines(content, abs_start, abs_end),
                    }
                )

        return payloads

    def _extract_kotlin_symbol_payloads(
        self,
        rel_path: str,
        content: str,
        module_name: str,
        package_name: str,
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []
        type_ranges: List[Tuple[int, int]] = []
        depth_map = self._compute_js_like_brace_depths(content)

        type_pattern = re.compile(
            r"(?m)^\s*(?:(?:public|private|protected|internal|open|abstract|sealed|data|"
            r"value|inline|companion|inner|annotation)\s+)*"
            r"(class|interface|object|enum\s+class)\s+([A-Za-z_]\w*)\b([^{]*)\{"
        )
        method_pattern = re.compile(
            r"(?m)^\s*(?:(?:public|private|protected|internal|open|override|abstract|"
            r"suspend|inline|operator|infix|tailrec|external|actual|expect)\s+)*"
            r"fun\s+(?:<[^>]*>\s*)?(?:[\w.]+\s*\.\s*)?([A-Za-z_]\w*)\s*\([^)]*\)"
            r"(?:\s*:\s*[\w<>?,.\s]+)?\s*(?:=\s*[^\n]+|(?:where\s+[\w\s:,<>]+\s*)?\{)"
        )

        for type_match in type_pattern.finditer(content):
            if depth_map[type_match.start()] > 1:
                continue
            type_kind_raw = type_match.group(1)
            type_name = type_match.group(2)
            tail = type_match.group(3) or ""

            open_brace = content.find("{", type_match.end() - 1)
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(content, open_brace)
            if close_brace < 0:
                continue
            type_ranges.append((type_match.start(), close_brace))

            raw_bases: Set[str] = set()
            colon_match = re.search(r":\s*([\w(),\s<>?]+?)(?:\{|where\b)", tail + " {")
            if colon_match:
                for part in re.split(r",\s*", colon_match.group(1)):
                    part = re.sub(r"<.*?>|\(.*?\)", "", part).strip()
                    if part and re.match(r"[A-Za-z_]\w*", part):
                        raw_bases.add(part)

            body = content[open_brace + 1:close_brace]
            type_kind = "class" if "class" in type_kind_raw else type_kind_raw

            payloads.append(
                {
                    "module": module_name,
                    "qualname": type_name,
                    "kind": type_kind,
                    "class_context": type_name,
                    "package_name": package_name,
                    "imports_symbols": dict(imports_symbols),
                    "member_types": {},
                    "member_qualifiers": {},
                    "declared_symbols": [],
                    "annotations": [],
                    "bean_name": "",
                    "is_abstract": bool(re.search(r"\babstract\b", type_match.group(0))),
                    "di_primary": False,
                    "raw_calls": set(),
                    "raw_bases": raw_bases,
                    "lines": self._span_to_lines(content, type_match.start(), close_brace),
                }
            )

            body_depth_map = self._compute_js_like_brace_depths(body)
            body_offset = open_brace + 1
            for method_match in method_pattern.finditer(body):
                method_name = method_match.group(1)
                if method_name in {"if", "for", "while", "when", "catch", "try", "return", "throw", "object", "companion", "init"}:
                    continue
                if body_depth_map[method_match.start()] > 1:
                    continue
                abs_start = body_offset + method_match.start()
                method_open = body.find("{", method_match.start())
                if method_open < 0:
                    method_close = method_match.end()
                else:
                    method_close = self._find_matching_brace(body, method_open)
                abs_end = body_offset + (method_close if method_close >= 0 else method_match.end())
                payloads.append(
                    {
                        "module": module_name,
                        "qualname": f"{type_name}.{method_name}",
                        "kind": "function",
                        "class_context": type_name,
                        "package_name": package_name,
                        "imports_symbols": dict(imports_symbols),
                        "member_types": {},
                        "member_qualifiers": {},
                        "declared_symbols": [],
                        "annotations": [],
                        "bean_name": "",
                        "is_abstract": False,
                        "di_primary": False,
                        "raw_calls": set(),
                        "raw_bases": set(),
                        "lines": self._span_to_lines(content, abs_start, abs_end),
                    }
                )

        for fun_match in method_pattern.finditer(content):
            if depth_map[fun_match.start()] > 1:
                continue
            if any(start <= fun_match.start() <= end for start, end in type_ranges):
                continue
            fun_name = fun_match.group(1)
            if fun_name in {"if", "for", "while", "when", "catch", "try", "return", "throw", "object", "companion", "init"}:
                continue
            fun_open = content.find("{", fun_match.start())
            if fun_open < 0:
                fun_end = fun_match.end()
            else:
                fun_end = self._find_matching_brace(content, fun_open)
            payloads.append(
                {
                    "module": module_name,
                    "qualname": fun_name,
                    "kind": "function",
                    "class_context": "",
                    "package_name": package_name,
                    "imports_symbols": dict(imports_symbols),
                    "member_types": {},
                    "member_qualifiers": {},
                    "declared_symbols": [],
                    "annotations": [],
                    "bean_name": "",
                    "is_abstract": False,
                    "di_primary": False,
                    "raw_calls": set(),
                    "raw_bases": set(),
                    "lines": self._span_to_lines(content, fun_match.start(), fun_end if fun_end >= 0 else fun_match.end()),
                }
            )

        return payloads

    def _extract_php_symbol_payloads(
        self,
        rel_path: str,
        content: str,
        module_name: str,
        package_name: str,
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []
        depth_map = self._compute_js_like_brace_depths(content)

        type_pattern = re.compile(
            r"(?m)^\s*(?:(?:abstract|final|readonly)\s+)*"
            r"(class|interface|trait|enum)\s+([A-Za-z_]\w*)\b([^{]*)\{"
        )
        method_pattern = re.compile(
            r"(?m)^\s*(?:(?:public|protected|private|static|abstract|final)\s+)*"
            r"function\s+([A-Za-z_]\w*)\s*\([^)]*\)\s*(?::\s*[\w?\\|]+\s*)?\{"
        )

        for type_match in type_pattern.finditer(content):
            if depth_map[type_match.start()] > 1:
                continue
            type_kind = type_match.group(1)
            type_name = type_match.group(2)
            tail = type_match.group(3) or ""

            open_brace = content.find("{", type_match.end() - 1)
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(content, open_brace)
            if close_brace < 0:
                continue

            raw_bases: Set[str] = set()
            for m in re.findall(r"\bextends\s+([\w\\]+)", tail):
                raw_bases.add(m.replace("\\", ".").split(".")[-1])
            for m in re.findall(r"\bimplements\s+([\w\\,\s]+?)(?:\{|$)", tail + " {"):
                for part in re.split(r",\s*", m.strip()):
                    clean = part.strip().replace("\\", ".").split(".")[-1]
                    if clean:
                        raw_bases.add(clean)

            body = content[open_brace + 1:close_brace]
            payloads.append({
                "module": module_name,
                "qualname": type_name,
                "kind": "class" if type_kind in {"class", "trait"} else type_kind,
                "class_context": type_name,
                "package_name": package_name,
                "imports_symbols": dict(imports_symbols),
                "member_types": {},
                "member_qualifiers": {},
                "declared_symbols": [],
                "annotations": [],
                "bean_name": "",
                "is_abstract": bool(re.search(r"\babstract\b", type_match.group(0))),
                "di_primary": False,
                "raw_calls": set(),
                "raw_bases": raw_bases,
                "lines": self._span_to_lines(content, type_match.start(), close_brace),
            })

            body_depth_map = self._compute_js_like_brace_depths(body)
            body_offset = open_brace + 1
            for method_match in method_pattern.finditer(body):
                method_name = method_match.group(1)
                if method_name in {"if", "for", "foreach", "while", "switch", "catch",
                                   "match", "try", "return", "throw"}:
                    continue
                if body_depth_map[method_match.start()] > 1:
                    continue
                abs_start = body_offset + method_match.start()
                m_open = body.find("{", method_match.start())
                if m_open < 0:
                    m_close = method_match.end()
                else:
                    m_close = self._find_matching_brace(body, m_open)
                abs_end = body_offset + (m_close if m_close >= 0 else method_match.end())
                payloads.append({
                    "module": module_name,
                    "qualname": f"{type_name}.{method_name}",
                    "kind": "function",
                    "class_context": type_name,
                    "package_name": package_name,
                    "imports_symbols": dict(imports_symbols),
                    "member_types": {},
                    "member_qualifiers": {},
                    "declared_symbols": [],
                    "annotations": [],
                    "bean_name": "",
                    "is_abstract": False,
                    "di_primary": False,
                    "raw_calls": set(),
                    "raw_bases": set(),
                    "lines": self._span_to_lines(content, abs_start, abs_end),
                })

        return payloads

    def _ruby_find_end(self, content: str, start_index: int) -> int:
        """Return the character index just after the closing Ruby 'end'."""
        _OPEN = re.compile(
            r"\b(?:class|module|def|do|begin|if|unless|case|while|until|for)\b"
        )
        _CLOSE = re.compile(r"\bend\b")
        depth = 1
        pos = start_index + 1
        while pos < len(content):
            om = _OPEN.search(content, pos)
            em = _CLOSE.search(content, pos)
            if om is None and em is None:
                break
            if em is None or (om is not None and om.start() < em.start()):
                depth += 1
                pos = om.end()
            else:
                depth -= 1
                if depth == 0:
                    return em.end()
                pos = em.end()
        return len(content)

    def _extract_ruby_symbol_payloads(
        self,
        rel_path: str,
        content: str,
        module_name: str,
        package_name: str,
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []

        type_pattern = re.compile(
            r"(?m)^(\s*)(?:class|module)\s+([A-Z]\w*(?:::[A-Z]\w*)*)\b([^\n]*)"
        )
        method_pattern = re.compile(
            r"(?m)^(\s*)def\s+(self\.)?([a-z_]\w*[?!]?)\s*(?:\([^)]*\))?"
        )

        for type_match in type_pattern.finditer(content):
            indent = len(type_match.group(1))
            if indent > 0:
                continue
            type_name = type_match.group(2).split("::")[-1]
            tail = type_match.group(3) or ""
            raw_bases: Set[str] = set()
            base_m = re.search(r"<\s*([A-Z]\w*(?:::[A-Z]\w*)*)", tail)
            if base_m:
                raw_bases.add(base_m.group(1).split("::")[-1])

            block_end = self._ruby_find_end(content, type_match.start())
            body = content[type_match.end():block_end]
            nested_type_ranges = [
                (nested_match.start(), self._ruby_find_end(body, nested_match.start()))
                for nested_match in type_pattern.finditer(body)
            ]

            payloads.append({
                "module": module_name,
                "qualname": type_name,
                "kind": "class",
                "class_context": type_name,
                "package_name": package_name,
                "imports_symbols": dict(imports_symbols),
                "member_types": {},
                "member_qualifiers": {},
                "declared_symbols": [],
                "annotations": [],
                "bean_name": "",
                "is_abstract": False,
                "di_primary": False,
                "raw_calls": set(),
                "raw_bases": raw_bases,
                "lines": self._span_to_lines(content, type_match.start(), block_end),
            })

            for method_match in method_pattern.finditer(body):
                if any(start <= method_match.start() < end for start, end in nested_type_ranges):
                    continue
                method_indent = len(method_match.group(1))
                if method_indent > 4:
                    continue
                is_class_method = bool(method_match.group(2))
                method_name = method_match.group(3)
                if method_name in {"initialize"}:
                    qualname = f"{type_name}.initialize"
                elif is_class_method:
                    qualname = f"{type_name}.{method_name}"
                else:
                    qualname = f"{type_name}#{method_name}"
                abs_start = type_match.end() + method_match.start()
                mend = self._ruby_find_end(body, method_match.start())
                abs_end = type_match.end() + mend
                payloads.append({
                    "module": module_name,
                    "qualname": qualname,
                    "kind": "function",
                    "class_context": type_name,
                    "package_name": package_name,
                    "imports_symbols": dict(imports_symbols),
                    "member_types": {},
                    "member_qualifiers": {},
                    "declared_symbols": [],
                    "annotations": [],
                    "bean_name": "",
                    "is_abstract": False,
                    "di_primary": False,
                    "raw_calls": set(),
                    "raw_bases": set(),
                    "lines": self._span_to_lines(content, abs_start, abs_end),
                })

        for method_match in method_pattern.finditer(content):
            if len(method_match.group(1)) > 0:
                continue
            method_name = method_match.group(3)
            mend = self._ruby_find_end(content, method_match.start())
            payloads.append({
                "module": module_name,
                "qualname": method_name,
                "kind": "function",
                "class_context": "",
                "package_name": package_name,
                "imports_symbols": dict(imports_symbols),
                "member_types": {},
                "member_qualifiers": {},
                "declared_symbols": [],
                "annotations": [],
                "bean_name": "",
                "is_abstract": False,
                "di_primary": False,
                "raw_calls": set(),
                "raw_bases": set(),
                "lines": self._span_to_lines(content, method_match.start(), mend),
            })

        return payloads

    def _extract_java_method_payloads(
        self,
        full_content: str,
        class_body: str,
        body_offset: int,
        module_name: str,
        package_name: str,
        class_name: str,
        field_types: Dict[str, str],
        field_qualifiers: Dict[str, str],
        imports_symbols: Dict[str, str],
    ) -> List[Dict[str, object]]:
        payloads: List[Dict[str, object]] = []
        depth_map = self._compute_js_like_brace_depths(class_body)
        method_pattern = re.compile(
            r"(?m)^\s*(?:@[A-Za-z_][A-Za-z0-9_$.]*(?:\([^\n]*\))?\s*)*"
            r"(?:(?:public|protected|private|static|final|abstract|synchronized|native|default|strictfp)\s+)*"
            r"(?:<[A-Za-z0-9_<>, ?]+\>\s*)?"
            r"(?:(?:[A-Za-z0-9_<>\[\], ?]+)\s+)?"
            r"([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*(?:throws\s+[A-Za-z0-9_.,\s]+)?\{"
        )

        for match in method_pattern.finditer(class_body):
            if depth_map[match.start()] != 0:
                continue
            method_name = match.group(1)
            param_types, param_qualifiers = self._extract_java_param_details(match.group(2) or "")
            open_brace = class_body.find("{", match.end() - 1)
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(class_body, open_brace)
            if close_brace < 0:
                continue
            body = class_body[open_brace + 1:close_brace]
            local_types = self._extract_java_declared_types(body)
            member_types = dict(field_types)
            member_types.update(param_types)
            member_types.update(local_types)
            member_qualifiers = dict(field_qualifiers)
            member_qualifiers.update(param_qualifiers)
            start_index = body_offset + match.start()
            end_index = body_offset + close_brace
            qualname = f"{class_name}.{method_name}"
            payloads.append(
                {
                    "module": module_name,
                    "qualname": qualname,
                    "kind": "method",
                    "class_context": class_name,
                    "imports_modules": {},
                    "imports_symbols": dict(imports_symbols),
                    "member_types": member_types,
                    "member_qualifiers": member_qualifiers,
                    "package_name": package_name,
                    "declared_symbols": [],
                    "raw_calls": self._extract_java_calls(body),
                    "raw_bases": set(),
                    "lines": self._span_to_lines(full_content, start_index, end_index),
                }
            )
        return payloads

    def _extract_java_top_level_calls(self, class_body: str) -> Set[str]:
        depth_map = self._compute_js_like_brace_depths(class_body)
        filtered = "".join(char if depth_map[index] == 0 else " " for index, char in enumerate(class_body))
        return self._extract_java_calls(filtered)

    def _extract_java_calls(self, fragment: str) -> Set[str]:
        calls: Set[str] = set()
        for match in re.finditer(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\(", fragment):
            name = match.group(1)
            if name in {"if", "for", "while", "switch", "catch", "return", "new", "super", "this"}:
                continue
            calls.add(name)
        for match in re.finditer(r"\bnew\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\(", fragment):
            calls.add(match.group(1))
        return calls

    def _split_java_csv(self, spec: str) -> List[str]:
        items: List[str] = []
        current: List[str] = []
        angle_depth = 0
        paren_depth = 0
        bracket_depth = 0
        brace_depth = 0
        for char in spec:
            if char == "<":
                angle_depth += 1
            elif char == ">" and angle_depth > 0:
                angle_depth -= 1
            elif char == "(":
                paren_depth += 1
            elif char == ")" and paren_depth > 0:
                paren_depth -= 1
            elif char == "[":
                bracket_depth += 1
            elif char == "]" and bracket_depth > 0:
                bracket_depth -= 1
            elif char == "{":
                brace_depth += 1
            elif char == "}" and brace_depth > 0:
                brace_depth -= 1
            elif char == "," and angle_depth == 0 and paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
                item = "".join(current).strip()
                if item:
                    items.append(item)
                current = []
                continue
            current.append(char)
        item = "".join(current).strip()
        if item:
            items.append(item)
        return items

    def _extract_java_annotation_entries(self, fragment: str) -> List[Tuple[str, str]]:
        entries: List[Tuple[str, str]] = []
        for match in re.finditer(r"@([A-Za-z_][A-Za-z0-9_$.]*)(?:\(([^()]*)\))?", fragment):
            entries.append((match.group(1).rsplit(".", 1)[-1], match.group(2) or ""))
        return entries

    def _extract_java_annotation_value(self, args: str) -> str:
        match = re.search(r'"([^"]+)"', args)
        return match.group(1).strip() if match else ""

    def _extract_java_qualifier(self, fragment: str) -> str:
        for name, args in self._extract_java_annotation_entries(fragment):
            if name in JAVA_QUALIFIER_ANNOTATIONS:
                qualifier = self._extract_java_annotation_value(args)
                if qualifier:
                    return qualifier
        return ""

    def _extract_java_leading_annotation_block(self, content: str, start_index: int) -> str:
        lines = content[:start_index].splitlines()
        collected: List[str] = []
        while lines:
            line = lines.pop().strip()
            if not line:
                if collected:
                    break
                continue
            if line.startswith("@"):
                collected.append(line)
                continue
            break
        return "\n".join(reversed(collected))

    def _extract_java_component_metadata(self, type_name: str, annotation_block: str) -> Tuple[List[str], str, bool]:
        entries = self._extract_java_annotation_entries(annotation_block)
        annotations = [name for name, _ in entries]
        bean_name = ""
        for name, args in entries:
            if name in JAVA_COMPONENT_ANNOTATIONS:
                bean_name = self._extract_java_annotation_value(args)
                if bean_name:
                    break
        if not bean_name and type_name and any(name in JAVA_COMPONENT_ANNOTATIONS for name in annotations):
            bean_name = type_name[:1].lower() + type_name[1:]
        return annotations, bean_name, any(name in JAVA_PRIMARY_ANNOTATIONS for name in annotations)

    def _clean_java_type(self, raw_type: str, initializer: str = "") -> str:
        cleaned = re.sub(r"@\w+(?:\([^)]*\))?\s*", " ", raw_type)
        cleaned = cleaned.replace("...", " ")
        cleaned = cleaned.replace("[]", " ")
        cleaned = re.sub(r"<.*?>", "", cleaned)
        cleaned = re.sub(
            r"\b(?:public|protected|private|static|final|transient|volatile|synchronized|native|strictfp)\b",
            " ",
            cleaned,
        )
        cleaned = re.sub(r"\b(?:extends|super)\b", " ", cleaned)
        parts = [part for part in cleaned.split() if part]
        if not parts:
            return ""
        candidate = parts[-1].strip()
        if candidate == "var":
            match = re.search(r"\bnew\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\(", initializer)
            candidate = match.group(1) if match else ""
        if not candidate or candidate in JAVA_NON_SYMBOL_TYPES:
            return ""
        return candidate

    def _extract_java_declared_members(
        self,
        fragment: str,
        top_level_only: bool = False,
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        declared: Dict[str, str] = {}
        qualifiers: Dict[str, str] = {}
        depth_map = self._compute_js_like_brace_depths(fragment) if top_level_only else None
        declaration_pattern = re.compile(
            r"(?m)^\s*((?:@[A-Za-z_][A-Za-z0-9_$.]*(?:\([^)]*\))?\s*)*)"
            r"(?:(?:public|protected|private|static|final|transient|volatile)\s+)*"
            r"([A-Za-z0-9_$.<>\[\], ?]+)\s+([A-Za-z_]\w*)\s*(?:=\s*([^;]+))?;"
        )
        for match in declaration_pattern.finditer(fragment):
            if depth_map is not None and depth_map[match.start()] != 0:
                continue
            variable_name = match.group(3)
            variable_type = self._clean_java_type(match.group(2), match.group(4) or "")
            if variable_type:
                declared[variable_name] = variable_type
                qualifier = self._extract_java_qualifier(match.group(1) or "")
                if qualifier:
                    qualifiers[variable_name] = qualifier
        return declared, qualifiers

    def _extract_java_declared_types(self, fragment: str, top_level_only: bool = False) -> Dict[str, str]:
        declared, _ = self._extract_java_declared_members(fragment, top_level_only=top_level_only)
        return declared

    def _extract_java_constructor_field_qualifiers(
        self,
        class_body: str,
        class_name: str,
        field_types: Dict[str, str],
    ) -> Dict[str, str]:
        field_qualifiers: Dict[str, str] = {}
        depth_map = self._compute_js_like_brace_depths(class_body)
        method_pattern = re.compile(
            r"(?m)^\s*(?:@[A-Za-z_][A-Za-z0-9_$.]*(?:\([^\n]*\))?\s*)*"
            r"(?:(?:public|protected|private|static|final|abstract|synchronized|native|default|strictfp)\s+)*"
            r"(?:<[A-Za-z0-9_<>, ?]+\>\s*)?"
            r"(?:(?:[A-Za-z0-9_<>\[\], ?]+)\s+)?"
            r"([A-Za-z_]\w*)\s*\(([^;{}]*)\)\s*(?:throws\s+[A-Za-z0-9_.,\s]+)?\{"
        )
        assignment_pattern = re.compile(r"(?m)(?:this\.)?([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*;")

        for match in method_pattern.finditer(class_body):
            if depth_map[match.start()] != 0 or match.group(1) != class_name:
                continue
            param_types, param_qualifiers = self._extract_java_param_details(match.group(2) or "")
            if not param_qualifiers:
                continue
            open_brace = class_body.find("{", match.end() - 1)
            if open_brace < 0:
                continue
            close_brace = self._find_matching_brace(class_body, open_brace)
            if close_brace < 0:
                continue
            body = class_body[open_brace + 1:close_brace]
            for assignment in assignment_pattern.finditer(body):
                field_name = assignment.group(1)
                param_name = assignment.group(2)
                if param_name not in param_qualifiers or field_name not in field_types:
                    continue
                if param_name in param_types and field_types[field_name] == param_types[param_name]:
                    field_qualifiers.setdefault(field_name, param_qualifiers[param_name])
        return field_qualifiers

    def _extract_java_param_details(self, params_spec: str) -> Tuple[Dict[str, str], Dict[str, str]]:
        params: Dict[str, str] = {}
        qualifiers: Dict[str, str] = {}
        param_pattern = re.compile(
            r"^\s*((?:@[A-Za-z_][A-Za-z0-9_$.]*(?:\([^)]*\))?\s*)*)"
            r"(?:(?:final)\s+)*(.+?)\s+([A-Za-z_]\w*)\s*$"
        )
        for raw_param in self._split_java_csv(params_spec):
            match = param_pattern.match(raw_param)
            if not match:
                continue
            variable_name = match.group(3)
            variable_type = self._clean_java_type(match.group(2))
            if not variable_type:
                continue
            params[variable_name] = variable_type
            qualifier = self._extract_java_qualifier(match.group(1) or "")
            if qualifier:
                qualifiers[variable_name] = qualifier
        return params, qualifiers

    def _extract_java_param_types(self, params_spec: str) -> Dict[str, str]:
        params, _ = self._extract_java_param_details(params_spec)
        return params

    def _parse_rust_module(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        funcs = re.findall(r"(?m)^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)\s*\(", content)
        types = re.findall(r"(?m)^\s*(?:pub\s+)?(?:struct|enum|trait|mod)\s+([A-Za-z_]\w*)\b", content)
        raw_imports: Set[str] = set()
        for spec in re.findall(r"(?m)^\s*use\s+([^;]+);", content):
            raw_imports.update(self._expand_rust_use_spec(spec))
        for child in re.findall(r"(?m)^\s*(?:pub\s+)?mod\s+([A-Za-z_]\w*)\s*;", content):
            raw_imports.add(f"mod::{child}")

        module_path = self._rust_module_path(rel_path)
        return {
            "module": source_group(rel_path, language),
            "qualname": source_qualname(rel_path),
            "kind": "module",
            "imports_modules": {},
            "imports_symbols": {},
            "package_name": module_path,
            "declared_symbols": self._dedupe(funcs + types)[:20],
            "raw_imports": raw_imports,
            "raw_bases": set(),
        }

    def _expand_rust_use_spec(self, spec: str) -> List[str]:
        compact = "".join(spec.strip().split())
        if "{" not in compact:
            return [compact]
        prefix, rest = compact.split("{", 1)
        inner = rest.rsplit("}", 1)[0]
        prefix = prefix.rstrip(":")
        out: List[str] = []
        for item in inner.split(","):
            if not item:
                continue
            if item == "self":
                out.append(prefix)
            else:
                out.append(f"{prefix}::{item}".strip(":"))
        return out

    def _rust_module_path(self, rel_path: str) -> str:
        normalized = Path(rel_path).as_posix()
        tail = normalized[4:] if normalized.startswith("src/") else normalized
        if tail in {"lib.rs", "main.rs"}:
            return "crate"
        if tail.endswith("/mod.rs"):
            tail = tail[:-7]
        elif tail.endswith(".rs"):
            tail = tail[:-3]
        parts = [part for part in tail.split("/") if part]
        if not parts:
            return "crate"
        return "crate::" + "::".join(parts)

    def _calls_from_body(self, statements: Iterable[ast.stmt]) -> Set[str]:
        collector = CallCollector()
        for stmt in statements:
            collector.visit(stmt)
        return collector.calls

    def _build_indices(self) -> None:
        self.fq_to_id.clear()
        self.short_index.clear()
        self.file_module_node.clear()
        self.file_top_level_symbol_index.clear()
        self.go_dir_to_node.clear()
        self.java_type_to_node.clear()
        self.java_member_to_node.clear()
        self.java_concrete_type_targets.clear()
        self.rust_module_to_node.clear()
        go_candidates: Dict[str, List[str]] = defaultdict(list)
        for node_id, node in self.nodes.items():
            fq = f"{node.module}.{node.qualname}"
            self.fq_to_id[fq] = node_id
            if node.language == "Python":
                short_names = [node.qualname.split(".")[-1]]
            else:
                short_names = [node.qualname.split(".")[-1], Path(node.qualname).stem] + list(node.declared_symbols)
                file_key = Path(node.file).as_posix()
                if node.kind == "module":
                    self.file_module_node[file_key] = node_id
                elif node.language in {"JavaScript", "TypeScript"} and "." not in node.qualname:
                    self.file_top_level_symbol_index[file_key][node.qualname].append(node_id)
                if node.language == "Go":
                    go_candidates[Path(node.file).parent.as_posix()].append(node_id)
                if node.language == "Java":
                    if node.kind in {"class", "interface", "enum"}:
                        fqcn = f"{node.package_name}.{node.qualname}" if node.package_name else node.qualname
                        self.java_type_to_node[fqcn] = node_id
                    elif node.kind == "method" and node.package_name:
                        self.java_member_to_node[f"{node.package_name}.{node.qualname}"] = node_id
                if node.language == "Rust":
                    module_path = node.package_name or self._rust_module_path(node.file)
                    self.rust_module_to_node[module_path] = node_id
            for short in short_names:
                if short:
                    self.short_index[short].append(node_id)

        for directory, candidates in go_candidates.items():
            selected = sorted(
                candidates,
                key=lambda candidate_id: (
                    0 if Path(self.nodes[candidate_id].file).name == "main.go" else 1,
                    0
                    if Path(self.nodes[candidate_id].file).stem == Path(directory).name and Path(directory).name
                    else 1,
                    self.nodes[candidate_id].file,
                ),
            )[0]
            self.go_dir_to_node[directory] = selected

    def _resolution(
        self,
        kind: str,
        reason: str,
        target: Optional[str] = None,
        candidates: Optional[List[str]] = None,
    ) -> ResolutionOutcome:
        score, label = RESOLUTION_CONFIDENCE.get(kind, RESOLUTION_CONFIDENCE["heuristic"])
        return ResolutionOutcome(
            target=target,
            resolution_kind=kind,
            confidence_score=score,
            confidence_label=label,
            resolution_reason=reason,
            candidates=list(candidates or []),
        )

    def _prefer_resolution(
        self,
        current: Optional[ResolutionOutcome],
        new: Optional[ResolutionOutcome],
    ) -> Optional[ResolutionOutcome]:
        if new is None:
            return current
        if current is None:
            return new
        current_key = (current.confidence_score, current.resolution_kind, current.resolution_reason)
        new_key = (new.confidence_score, new.resolution_kind, new.resolution_reason)
        return new if new_key > current_key else current

    def _record_unresolved_call_outcome(self, caller: SymbolNode, raw: str, outcome: ResolutionOutcome) -> None:
        if outcome.candidates:
            caller.heuristic_candidates[raw] = list(outcome.candidates)
        if outcome.resolution_kind:
            caller.unresolved_call_details[raw] = outcome.to_payload()

    def _add_edge(
        self,
        source: str,
        target: str,
        kind: str,
        resolution: Optional[ResolutionOutcome] = None,
    ) -> None:
        self.adj[source].add(target)
        self.edge_kinds[(source, target)].add(kind)
        if resolution and resolution.target == target:
            self.edge_resolution[(source, target)] = self._prefer_resolution(
                self.edge_resolution.get((source, target)),
                resolution,
            ) or resolution

    def _resolve_edges(self) -> None:
        for node_id in self.nodes:
            self.adj[node_id] = set()
        self.edge_kinds.clear()
        self.edge_resolution.clear()

        for node_id, node in self.nodes.items():
            node.resolved_calls.clear()
            node.resolved_bases.clear()
            node.resolved_imports.clear()
            node.external_calls.clear()
            node.external_bases.clear()
            node.external_imports.clear()
            node.unresolved_calls.clear()
            node.unresolved_call_details.clear()
            node.unresolved_bases.clear()
            node.unresolved_imports.clear()
            node.recursive_self_call = False
            node.heuristic_candidates.clear()

        for node_id, node in self.nodes.items():
            if node.kind != "class" and not node.raw_bases:
                continue
            for raw_base in sorted(node.raw_bases):
                outcome = self._resolve_base_outcome(node, raw_base)
                target = outcome.target
                if target is None:
                    base_kind = self._classify_unresolved_base(node, raw_base)
                    if base_kind == "external":
                        node.external_bases.add(raw_base)
                    elif base_kind == "unresolved":
                        node.unresolved_bases.add(raw_base)
                    continue
                if target == node_id:
                    continue
                node.resolved_bases.add(target)
                self._add_edge(node_id, target, "inheritance", outcome)

        self._build_java_concrete_type_targets()

        for node_id, node in self.nodes.items():
            for raw in sorted(node.raw_calls):
                outcome = self._resolve_call_outcome(node, raw)
                target = outcome.target
                if target is None:
                    if outcome.resolution_kind == "ambiguous_candidates":
                        self._record_unresolved_call_outcome(node, raw, outcome)
                    unresolved_kind = self._classify_unresolved_call(node, raw)
                    if unresolved_kind == "external":
                        node.external_calls.add(raw)
                    elif unresolved_kind == "unresolved":
                        node.unresolved_calls.add(raw)
                    continue
                self._add_edge(node_id, target, "call", outcome)
                if target == node_id:
                    node.recursive_self_call = True
                else:
                    node.resolved_calls.add(target)

        for node_id, node in self.nodes.items():
            for raw in sorted(node.raw_imports):
                outcome = self._resolve_import_outcome(node, raw)
                target = outcome.target
                if target is None:
                    import_kind = self._classify_unresolved_import(node, raw)
                    if import_kind == "external":
                        node.external_imports.add(raw)
                    elif import_kind == "unresolved":
                        node.unresolved_imports.add(raw)
                    continue
                if target == node_id:
                    continue
                node.resolved_imports.add(target)
                self._add_edge(node_id, target, "import", outcome)

        indegree: Dict[str, int] = {nid: 0 for nid in self.nodes}
        for src, dsts in self.adj.items():
            for dst in dsts:
                if src != dst:
                    indegree[dst] += 1

        for node_id, node in self.nodes.items():
            node.ca = indegree[node_id]
            node.ce_internal = len({target for target in self.adj[node_id] if target != node_id})
            node.ce_external = len(node.external_calls) + len(node.external_bases) + len(node.external_imports)
            node.ce_total = node.ce_internal + node.ce_external
            internal_total = node.ca + node.ce_internal
            total = node.ca + node.ce_total
            node.instability = round(node.ce_internal / internal_total, 4) if internal_total > 0 else 0.0
            node.instability_total = round(node.ce_total / total, 4) if total > 0 else 0.0

    def _classify_unresolved_call(self, caller: SymbolNode, raw: str) -> str:
        if caller.language in {"JavaScript", "TypeScript"}:
            return self._classify_js_like_call(caller, raw)
        if caller.language == "Java":
            return self._classify_java_call(caller, raw)
        root = raw.split(".", 1)[0]
        if raw == "super()" or root in BUILTIN_NAMES:
            return "ignore"
        if raw.startswith(("self.", "cls.", "super().")):
            return "unresolved"
        if root in caller.imports_modules or root in caller.imports_symbols:
            return "external"
        if raw in caller.imports_symbols:
            return "external"
        return "unresolved"

    def _classify_unresolved_base(self, caller: SymbolNode, raw: str) -> str:
        if caller.language != "Python":
            return self._classify_non_python_base(caller, raw)
        root = raw.split(".", 1)[0]
        if root in BUILTIN_NAMES or raw == "object":
            return "ignore"
        if root in caller.imports_modules or root in caller.imports_symbols:
            return "external"
        if raw in caller.imports_symbols:
            return "external"
        return "unresolved"

    def _resolve_base_outcome(self, caller: SymbolNode, raw: str) -> ResolutionOutcome:
        if caller.language != "Python":
            target = self._resolve_non_python_base(caller, raw)
            if target:
                return self._resolution(target=target, kind="inheritance_exact", reason=f"Resolved base `{raw}` as an internal inherited type.")
            return ResolutionOutcome(target=None)
        module = caller.module
        candidate = f"{module}:{raw}"
        if candidate in self.nodes and self.nodes[candidate].kind == "class":
            return self._resolution(target=candidate, kind="inheritance_exact", reason=f"Resolved base `{raw}` in the same module.")

        if "." in raw:
            head, tail = raw.split(".", 1)
            if head in caller.imports_modules:
                fq = f"{caller.imports_modules[head]}.{tail}"
                target = self.fq_to_id.get(fq)
                if target and self.nodes[target].kind == "class":
                    return self._resolution(target=target, kind="inheritance_exact", reason=f"Resolved base `{raw}` through imported module `{head}`.")
            if head in caller.imports_symbols:
                fq = f"{caller.imports_symbols[head]}.{tail}"
                target = self.fq_to_id.get(fq)
                if target and self.nodes[target].kind == "class":
                    return self._resolution(target=target, kind="inheritance_exact", reason=f"Resolved base `{raw}` through imported symbol `{head}`.")
            direct = self.fq_to_id.get(raw)
            if direct and self.nodes[direct].kind == "class":
                return self._resolution(target=direct, kind="inheritance_exact", reason=f"Resolved base `{raw}` by exact qualified name.")

        if raw in caller.imports_symbols:
            target = self.fq_to_id.get(caller.imports_symbols[raw])
            if target and self.nodes[target].kind == "class":
                return self._resolution(target=target, kind="inheritance_exact", reason=f"Resolved base `{raw}` through exact import.")

        candidates = [node_id for node_id in self.short_index.get(raw, []) if self.nodes[node_id].kind == "class"]
        if len(candidates) == 1:
            return self._resolution(target=candidates[0], kind="heuristic", reason=f"Resolved base `{raw}` via unique short-name class match.")
        return ResolutionOutcome(target=None)

    def _resolve_base(self, caller: SymbolNode, raw: str) -> Optional[str]:
        return self._resolve_base_outcome(caller, raw).target

    def _resolve_call_outcome(self, caller: SymbolNode, raw: str) -> ResolutionOutcome:
        if caller.language in {"JavaScript", "TypeScript"}:
            return self._resolve_js_like_call_outcome(caller, raw)
        if caller.language == "Java":
            return self._resolve_java_call_outcome(caller, raw)
        module = caller.module
        class_ctx = caller.class_context

        # Direct same-module qualified symbol, e.g. Class.method
        candidate = f"{module}:{raw}"
        if candidate in self.nodes:
            return self._resolution(target=candidate, kind="direct_symbol", reason=f"Resolved `{raw}` by exact symbol name in the same module.")

        # self.method / cls.method
        if raw.startswith("self.") or raw.startswith("cls."):
            if class_ctx:
                method = raw.split(".", 1)[1]
                candidate = f"{module}:{class_ctx}.{method}"
                if candidate in self.nodes:
                    return self._resolution(target=candidate, kind="same_class_method", reason=f"Resolved `{raw}` to method `{method}` on the current class.")
            return ResolutionOutcome(target=None)

        # super().method: keep external unless base method exists in same module uniquely
        if raw.startswith("super()."):
            method = raw.split(".", 1)[1]
            target = self._resolve_super_method(module, class_ctx, method)
            if target:
                return self._resolution(target=target, kind="super_dispatch", reason=f"Resolved `{raw}` through base-class dispatch.")
            matches = [nid for nid in self.short_index.get(method, []) if self.nodes[nid].module == module]
            if len(matches) == 1:
                return self._resolution(target=matches[0], kind="heuristic", reason=f"Resolved `{raw}` via unique same-module fallback after super dispatch.")
            return ResolutionOutcome(target=None)

        # Dotted call: alias.module_or_symbol.something
        if "." in raw:
            head, tail = raw.split(".", 1)
            if head in caller.imports_modules:
                fq = f"{caller.imports_modules[head]}.{tail}"
                target = self.fq_to_id.get(fq)
                if target:
                    return self._resolution(target=target, kind="import_exact", reason=f"Resolved `{raw}` through imported module `{head}`.")
            if head in caller.imports_symbols:
                fq = f"{caller.imports_symbols[head]}.{tail}"
                target = self.fq_to_id.get(fq)
                if target:
                    return self._resolution(target=target, kind="import_exact", reason=f"Resolved `{raw}` through imported symbol `{head}`.")
            direct = self.fq_to_id.get(raw)
            if direct:
                return self._resolution(target=direct, kind="direct_symbol", reason=f"Resolved `{raw}` by exact qualified symbol name.")

        # Bare imported symbol
        if raw in caller.imports_symbols:
            fq = caller.imports_symbols[raw]
            target = self.fq_to_id.get(fq)
            if target:
                return self._resolution(target=target, kind="import_exact", reason=f"Resolved `{raw}` through exact import.")

        # Bare same-class method inside class context
        if class_ctx:
            candidate = f"{module}:{class_ctx}.{raw}"
            if candidate in self.nodes:
                return self._resolution(target=candidate, kind="same_class_method", reason=f"Resolved `{raw}` as a method on the current class.")

        # Bare same-module function/class
        candidate = f"{module}:{raw}"
        if candidate in self.nodes:
            return self._resolution(target=candidate, kind="same_module_symbol", reason=f"Resolved `{raw}` as a same-module symbol.")

        # Global unique short name fallback
        candidates = [candidate for candidate in self.short_index.get(raw, []) if self.nodes[candidate].language == "Python"]
        if len(candidates) == 1:
            return self._resolution(target=candidates[0], kind="heuristic", reason=f"Resolved `{raw}` via unique short-name fallback.")

        return ResolutionOutcome(target=None)

    def _resolve_call(self, caller: SymbolNode, raw: str) -> Optional[str]:
        return self._resolve_call_outcome(caller, raw).target

    def _resolve_non_python_base(self, caller: SymbolNode, raw: str) -> Optional[str]:
        root = raw.split(".", 1)[0].split("::", 1)[0]
        if caller.language in {"JavaScript", "TypeScript"}:
            if root in caller.declared_symbols:
                target = self._resolve_js_like_file_symbol(caller.file, root)
                if target and target != caller.node_id:
                    return target
                return caller.node_id
            spec = caller.imports_symbols.get(root) or caller.imports_modules.get(root)
            if spec:
                return self._resolve_import(caller, spec)
            return self._resolve_js_like_file_symbol(caller.file, root)

        if caller.language == "Java":
            cleaned = re.sub(r"<.*?>", "", raw).strip()
            simple = cleaned.rsplit(".", 1)[-1]
            if simple in caller.declared_symbols:
                return caller.node_id
            if cleaned in self.java_type_to_node:
                return self.java_type_to_node[cleaned]
            imported = caller.imports_symbols.get(simple)
            if imported and imported in self.java_type_to_node:
                return self.java_type_to_node[imported]
            if caller.package_name:
                local_fqcn = f"{caller.package_name}.{simple}"
                if local_fqcn in self.java_type_to_node:
                    return self.java_type_to_node[local_fqcn]
            candidates = [node_id for fqcn, node_id in self.java_type_to_node.items() if fqcn.endswith(f".{simple}")]
            return candidates[0] if len(candidates) == 1 else None

        return None

    def _is_java_concrete_type(self, node: SymbolNode) -> bool:
        return node.language == "Java" and node.kind in {"class", "enum"} and not node.is_abstract

    def _build_java_concrete_type_targets(self) -> None:
        self.java_concrete_type_targets.clear()
        java_types = sorted(
            node_id
            for node_id, node in self.nodes.items()
            if node.language == "Java" and node.kind in {"class", "enum", "interface"}
        )
        children: Dict[str, Set[str]] = defaultdict(set)
        for node_id in java_types:
            node = self.nodes[node_id]
            for base_id in node.resolved_bases:
                if base_id in self.nodes and self.nodes[base_id].language == "Java":
                    children[base_id].add(node_id)

        for type_id in java_types:
            concrete_targets: List[str] = []
            if self._is_java_concrete_type(self.nodes[type_id]):
                concrete_targets.append(type_id)
            visited: Set[str] = set()
            queue = deque(sorted(children.get(type_id, set())))
            while queue:
                child_id = queue.popleft()
                if child_id in visited:
                    continue
                visited.add(child_id)
                child_node = self.nodes[child_id]
                if self._is_java_concrete_type(child_node):
                    concrete_targets.append(child_id)
                for nested_id in sorted(children.get(child_id, set())):
                    queue.append(nested_id)
            if concrete_targets:
                self.java_concrete_type_targets[type_id] = sorted(set(concrete_targets))

    def _java_candidate_names(self, candidate_id: str) -> Set[str]:
        if candidate_id not in self.nodes:
            return set()
        node = self.nodes[candidate_id]
        simple_name = node.qualname.split(".")[-1]
        names = {simple_name, simple_name[:1].lower() + simple_name[1:] if simple_name else ""}
        if node.bean_name:
            names.add(node.bean_name)
        return {name for name in names if name}

    def _java_candidate_matches_qualifier(self, candidate_id: str, qualifier: str) -> bool:
        normalized = qualifier.strip().lower()
        if not normalized:
            return False
        return any(name.lower() == normalized for name in self._java_candidate_names(candidate_id))

    def _select_java_di_candidates(
        self,
        caller: SymbolNode,
        declared_target: str,
        member_name: str,
    ) -> List[str]:
        candidates = list(self.java_concrete_type_targets.get(declared_target, []))
        if not candidates:
            return []
        qualifier = caller.member_qualifiers.get(member_name, "")
        if qualifier:
            return sorted(candidate for candidate in candidates if self._java_candidate_matches_qualifier(candidate, qualifier))
        primary_candidates = sorted(candidate for candidate in candidates if self.nodes[candidate].di_primary)
        if primary_candidates:
            return primary_candidates
        return sorted(candidates)

    def _resolve_import_outcome(self, caller: SymbolNode, raw: str) -> ResolutionOutcome:
        if caller.language in {"JavaScript", "TypeScript"}:
            return self._resolve_js_like_import_outcome(caller, raw)
        if caller.language == "Go":
            target = self._resolve_go_import(raw)
            if target:
                return self._resolution(target=target, kind="import_exact", reason=f"Resolved Go import `{raw}` exactly.")
            return ResolutionOutcome(target=None)
        if caller.language == "Java":
            target = self._resolve_java_import(raw)
            if target:
                return self._resolution(target=target, kind="import_exact", reason=f"Resolved Java import `{raw}` exactly.")
            return ResolutionOutcome(target=None)
        if caller.language == "Rust":
            target = self._resolve_rust_import(caller, raw)
            if target:
                return self._resolution(target=target, kind="import_exact", reason=f"Resolved Rust import `{raw}` exactly.")
            return ResolutionOutcome(target=None)
        if caller.language == "CSharp":
            candidates = [
                nid for nid, nd in self.nodes.items()
                if nd.language == "CSharp" and nd.package_name == raw and nd.kind != "module"
            ]
            if len(candidates) == 1:
                return self._resolution(
                    target=candidates[0],
                    kind="import_exact",
                    reason=f"Resolved C# using `{raw}` exactly.",
                )
            return ResolutionOutcome(target=None)
        if caller.language == "Kotlin":
            candidates = [
                nid for nid, nd in self.nodes.items()
                if nd.language == "Kotlin" and nd.package_name
                and (nd.package_name == raw or nd.package_name.startswith(raw + "."))
                and nd.kind != "module"
            ]
            if len(candidates) == 1:
                return self._resolution(
                    target=candidates[0],
                    kind="import_exact",
                    reason=f"Resolved Kotlin import `{raw}` exactly.",
                )
            return ResolutionOutcome(target=None)
        if caller.language == "PHP":
            direct_candidates = [
                nid for nid, nd in self.nodes.items()
                if nd.language == "PHP" and nd.package_name
                and "." not in nd.qualname
                and f"{nd.package_name}.{nd.qualname}" == raw
                and nd.kind != "module"
            ]
            if len(direct_candidates) == 1:
                return self._resolution(
                    target=direct_candidates[0],
                    kind="import_exact",
                    reason=f"Resolved PHP use `{raw}` exactly.",
                )
            candidates = [
                nid for nid, nd in self.nodes.items()
                if nd.language == "PHP" and nd.package_name
                and (nd.package_name == raw or nd.package_name.endswith("." + raw))
                and nd.kind != "module"
            ]
            if len(candidates) == 1:
                return self._resolution(
                    target=candidates[0],
                    kind="import_exact",
                    reason=f"Resolved PHP use `{raw}` exactly.",
                )
            return ResolutionOutcome(target=None)
        if caller.language == "Ruby":
            raw_norm = raw.replace("-", "_").lower()
            direct_candidates = [
                nid for nid, nd in self.nodes.items()
                if nd.language == "Ruby"
                and nd.kind == "class"
                and (
                    Path(nd.file).stem.replace("-", "_").lower() == raw_norm
                    or re.sub(
                        r"(?<!^)(?=[A-Z])",
                        "_",
                        nd.qualname.split("#", 1)[0].split(".", 1)[0].split("::")[-1],
                    ).lower() == raw_norm
                )
            ]
            if len(direct_candidates) == 1:
                return self._resolution(
                    target=direct_candidates[0],
                    kind="import_exact",
                    reason=f"Resolved Ruby require `{raw}` exactly.",
                )
            candidates = [
                nid for nid, nd in self.nodes.items()
                if nd.language == "Ruby"
                and nd.kind != "module"
                and (nd.package_name == raw or nd.package_name.endswith("." + raw))
            ]
            if len(candidates) == 1:
                return self._resolution(
                    target=candidates[0],
                    kind="import_exact",
                    reason=f"Resolved Ruby require `{raw}` exactly.",
                )
            return ResolutionOutcome(target=None)
        return ResolutionOutcome(target=None)

    def _resolve_import(self, caller: SymbolNode, raw: str) -> Optional[str]:
        return self._resolve_import_outcome(caller, raw).target

    def _js_like_import_resolution_kind(self, rel_path: str, spec: str) -> str:
        if not spec or spec.startswith((".", "..")):
            return "import_exact"
        for config in self._js_resolver_configs_for_file(rel_path):
            for alias_pattern in dict(config.get("paths", {})):
                if "*" in alias_pattern:
                    prefix, suffix = alias_pattern.split("*", 1)
                    if spec.startswith(prefix) and (not suffix or spec.endswith(suffix)):
                        return "alias_resolved"
                elif spec == alias_pattern:
                    return "alias_resolved"
        return "import_exact"

    def _resolve_js_like_import_outcome(self, caller: SymbolNode, spec: str) -> ResolutionOutcome:
        if not spec:
            return ResolutionOutcome(target=None)
        binding_name = ""
        if "#" in spec:
            spec, binding_name = spec.split("#", 1)
        path_kind = self._js_like_import_resolution_kind(caller.file, spec)
        resolved: List[Tuple[str, str]] = []
        for target_file in self._resolve_js_like_import_targets(caller.file, spec):
            if binding_name:
                target, used_barrel = self._resolve_js_like_binding_target_with_barrel(target_file, binding_name, visited=set())
            else:
                target, used_barrel = self.file_module_node.get(target_file), False
            if target:
                resolved.append((target, "barrel_reexport" if used_barrel else path_kind))
        unique_targets = sorted({target for target, _ in resolved})
        if len(unique_targets) != 1:
            return ResolutionOutcome(target=None)
        target = unique_targets[0]
        target_kinds = [kind for candidate, kind in resolved if candidate == target]
        resolution_kind = "barrel_reexport" if "barrel_reexport" in target_kinds else target_kinds[0]
        if resolution_kind == "barrel_reexport":
            reason = f"Resolved `{spec}` via barrel re-export."
        elif resolution_kind == "alias_resolved":
            reason = f"Resolved `{spec}` through configured path alias."
        else:
            reason = f"Resolved `{spec}` through exact internal import target."
        return self._resolution(target=target, kind=resolution_kind, reason=reason)

    def _resolve_js_like_import(self, caller: SymbolNode, spec: str) -> Optional[str]:
        return self._resolve_js_like_import_outcome(caller, spec).target

    def _resolve_js_like_import_targets(self, rel_path: str, spec: str) -> List[str]:
        candidates: List[str] = []
        if not spec:
            return candidates
        abs_source = os.path.abspath(os.path.join(self.root_dir, rel_path))
        if spec.startswith((".", "..")):
            base_path = os.path.normpath(os.path.join(os.path.dirname(abs_source), spec.replace("/", os.sep)))
            candidates.extend(self._js_like_candidate_file_keys(base_path))
            return self._dedupe(candidates)

        configs = self._js_resolver_configs_for_file(rel_path)
        for config in configs:
            matched_alias = False
            for alias_pattern, target_patterns in dict(config.get("paths", {})).items():
                wildcard_value: Optional[str] = None
                if "*" in alias_pattern:
                    prefix, suffix = alias_pattern.split("*", 1)
                    if spec.startswith(prefix) and (not suffix or spec.endswith(suffix)):
                        end_index = len(spec) - len(suffix) if suffix else len(spec)
                        wildcard_value = spec[len(prefix):end_index]
                elif spec == alias_pattern:
                    wildcard_value = ""
                if wildcard_value is None:
                    continue
                matched_alias = True
                for target_pattern in target_patterns:
                    resolved_target = target_pattern.replace("*", wildcard_value) if "*" in target_pattern else target_pattern
                    candidates.extend(self._js_like_candidate_file_keys(resolved_target))
            if matched_alias:
                continue
            base_dir = str(config.get("base_dir", ""))
            if base_dir:
                candidates.extend(self._js_like_candidate_file_keys(os.path.normpath(os.path.join(base_dir, spec.replace("/", os.sep)))))
        return self._dedupe(candidates)

    def _js_like_candidate_file_keys(self, base_path: str) -> List[str]:
        out: List[str] = []
        if not base_path:
            return out
        candidate_paths: List[str] = []
        if Path(base_path).suffix.lower() in JS_LIKE_SUFFIXES:
            candidate_paths.append(base_path)
        else:
            for suffix in sorted(JS_LIKE_SUFFIXES):
                candidate_paths.append(base_path + suffix)
            for suffix in sorted(JS_LIKE_SUFFIXES):
                candidate_paths.append(os.path.join(base_path, f"index{suffix}"))

        for candidate in candidate_paths:
            abs_candidate = os.path.abspath(candidate)
            try:
                rel_candidate = os.path.relpath(abs_candidate, self.root_dir)
            except ValueError:
                continue
            if rel_candidate.startswith(".."):
                continue
            normalized = Path(os.path.normpath(rel_candidate)).as_posix()
            if normalized in self.file_module_node:
                out.append(normalized)
        return out

    def _js_resolver_configs_for_file(self, rel_path: str) -> List[Dict[str, object]]:
        abs_file = os.path.abspath(os.path.join(self.root_dir, rel_path))
        applicable = [
            config
            for config in self.js_resolver_configs
            if abs_file == str(config["config_dir"]) or abs_file.startswith(str(config["config_dir"]) + os.sep)
        ]
        return applicable if applicable else self.js_resolver_configs

    def _looks_like_internal_js_spec(self, rel_path: str, spec: str) -> bool:
        if not spec:
            return False
        if spec.startswith((".", "..")):
            return True
        if self._resolve_js_like_import_targets(rel_path, spec):
            return True
        for config in self._js_resolver_configs_for_file(rel_path):
            for alias_pattern in dict(config.get("paths", {})):
                if "*" in alias_pattern:
                    prefix, suffix = alias_pattern.split("*", 1)
                    if spec.startswith(prefix) and (not suffix or spec.endswith(suffix)):
                        return True
                elif spec == alias_pattern:
                    return True
        return False

    def _resolve_js_like_type_ref(self, caller: SymbolNode, raw_type: str) -> Optional[str]:
        cleaned = self._clean_js_like_type(raw_type)
        if not cleaned:
            return None
        if caller.class_context and cleaned == caller.class_context:
            candidate = f"{caller.module}:{caller.class_context}"
            if candidate in self.nodes and self.nodes[candidate].kind == "class":
                return candidate
        target = self._resolve_non_python_base(caller, cleaned)
        if target and self.nodes[target].kind == "class":
            return target
        return None

    def _resolve_js_like_member_target(self, class_target: Optional[str], member_name: str) -> Optional[str]:
        if not class_target or class_target not in self.nodes:
            return None
        if self.nodes[class_target].kind != "class" or "." in member_name:
            return None
        candidate = f"{self.nodes[class_target].module}:{self.nodes[class_target].qualname}.{member_name}"
        return candidate if candidate in self.nodes else None

    def _resolve_js_like_call_outcome(self, caller: SymbolNode, raw: str) -> ResolutionOutcome:
        class_ctx = caller.class_context
        normalized = raw[len("this."):] if raw.startswith("this.") else raw
        if normalized.startswith("super."):
            target = self._resolve_super_method(caller.module, class_ctx, normalized.split(".", 1)[1])
            if target:
                return self._resolution(target=target, kind="super_dispatch", reason=f"Resolved `{raw}` through base-class dispatch.")
            return ResolutionOutcome(target=None)
        if "." in normalized:
            head, tail = normalized.split(".", 1)
            if head in caller.member_types:
                class_target = self._resolve_js_like_type_ref(caller, caller.member_types[head])
                member_target = self._resolve_js_like_member_target(class_target, tail)
                if member_target:
                    return self._resolution(target=member_target, kind="instance_dispatch", reason=f"Resolved `{raw}` through instance member `{head}`.")
            if head in caller.imports_modules:
                outcome = self._resolve_js_like_import_outcome(caller, f"{caller.imports_modules[head]}#{tail}")
                if outcome.target:
                    return outcome
        if normalized in caller.imports_symbols:
            binding = caller.imports_symbols[normalized]
            outcome = self._resolve_js_like_import_outcome(caller, binding)
            if outcome.target:
                return outcome
        if class_ctx:
            candidate = f"{caller.module}:{class_ctx}.{normalized}"
            if candidate in self.nodes:
                return self._resolution(target=candidate, kind="same_class_method", reason=f"Resolved `{raw}` on the current class.")
        target = self._resolve_js_like_file_symbol(caller.file, normalized)
        if target:
            return self._resolution(target=target, kind="same_module_symbol", reason=f"Resolved `{raw}` as a same-file symbol.")
        candidates = [
            candidate
            for candidate in self.short_index.get(normalized, [])
            if self.nodes[candidate].language in {"JavaScript", "TypeScript"}
        ]
        if len(candidates) == 1:
            return self._resolution(target=candidates[0], kind="heuristic", reason=f"Resolved `{raw}` via unique short-name fallback.")
        return ResolutionOutcome(target=None)

    def _resolve_js_like_call(self, caller: SymbolNode, raw: str) -> Optional[str]:
        return self._resolve_js_like_call_outcome(caller, raw).target

    def _resolve_js_like_file_symbol(self, rel_path: str, symbol_name: str) -> Optional[str]:
        file_key = Path(rel_path).as_posix()
        candidates = self.file_top_level_symbol_index.get(file_key, {}).get(symbol_name, [])
        return candidates[0] if len(candidates) == 1 else None

    def _resolve_js_like_binding_reference_with_barrel(
        self,
        file_key: str,
        binding_spec: str,
        visited: Set[Tuple[str, str]],
        _depth: int = 0,
    ) -> Tuple[Optional[str], bool]:
        if _depth > 8:
            return None, False
        spec = binding_spec
        binding_name = ""
        if "#" in binding_spec:
            spec, binding_name = binding_spec.split("#", 1)
        resolved: List[Tuple[str, bool]] = []
        for target_file in self._resolve_js_like_import_targets(file_key, spec):
            if binding_name:
                target, used_barrel = self._resolve_js_like_binding_target_with_barrel(target_file, binding_name, visited=visited, _depth=_depth + 1)
            else:
                target, used_barrel = self.file_module_node.get(target_file), False
            if target:
                resolved.append((target, used_barrel))
        unique_targets = sorted({target for target, _ in resolved})
        if len(unique_targets) != 1:
            return None, False
        target = unique_targets[0]
        return target, any(used_barrel for candidate, used_barrel in resolved if candidate == target)

    def _resolve_js_like_binding_reference(
        self,
        file_key: str,
        binding_spec: str,
        visited: Set[Tuple[str, str]],
    ) -> Optional[str]:
        target, _ = self._resolve_js_like_binding_reference_with_barrel(file_key, binding_spec, visited)
        return target

    def _resolve_js_like_binding_target_with_barrel(
        self,
        file_key: str,
        binding_name: str,
        visited: Optional[Set[Tuple[str, str]]] = None,
        _depth: int = 0,
    ) -> Tuple[Optional[str], bool]:
        if _depth > 8:
            return None, False
        visited = visited or set()
        visit_key = (file_key, binding_name)
        if visit_key in visited:
            return None, False
        visited.add(visit_key)
        symbols = self.file_top_level_symbol_index.get(file_key, {})
        if not binding_name:
            return None, False
        if binding_name not in {"", "default"}:
            candidates = symbols.get(binding_name, [])
            if len(candidates) == 1:
                return candidates[0], False
            barrel_binding = self.js_barrel_bindings.get(file_key, {}).get(binding_name)
            if barrel_binding:
                target, _ = self._resolve_js_like_binding_reference_with_barrel(file_key, barrel_binding, visited, _depth=_depth + 1)
                return (target, True) if target else (None, False)
            star_hits = []
            for spec in self.js_barrel_star_specs.get(file_key, []):
                target, _ = self._resolve_js_like_binding_reference_with_barrel(file_key, f"{spec}#{binding_name}", visited, _depth=_depth + 1)
                if target:
                    star_hits.append(target)
            unique_star_hits = sorted(set(star_hits))
            return (unique_star_hits[0], True) if len(unique_star_hits) == 1 else (None, False)
        stem = Path(file_key).stem
        if stem in symbols and len(symbols[stem]) == 1:
            return symbols[stem][0], False
        default_binding = self.js_barrel_bindings.get(file_key, {}).get("default")
        if default_binding:
            target, _ = self._resolve_js_like_binding_reference_with_barrel(file_key, default_binding, visited, _depth=_depth + 1)
            return (target, True) if target else (None, False)
        top_level_nodes = [candidate for candidates in symbols.values() for candidate in candidates]
        unique_nodes = sorted(set(top_level_nodes))
        return (unique_nodes[0], False) if len(unique_nodes) == 1 else (None, False)

    def _resolve_js_like_binding_target(
        self,
        file_key: str,
        binding_name: str,
        visited: Optional[Set[Tuple[str, str]]] = None,
    ) -> Optional[str]:
        target, _ = self._resolve_js_like_binding_target_with_barrel(file_key, binding_name, visited)
        return target

    def _classify_js_like_call(self, caller: SymbolNode, raw: str) -> str:
        normalized = raw[len("this."):] if raw.startswith("this.") else raw
        root = normalized.split(".", 1)[0]
        if root in JS_GLOBAL_NAMES:
            return "external"
        if raw.startswith(("this.", "super.")):
            return "unresolved"
        if root in caller.member_types:
            return "unresolved"
        if root in caller.imports_modules:
            spec = caller.imports_modules[root]
            return "unresolved" if self._looks_like_internal_js_spec(caller.file, spec) else "external"
        if root in caller.imports_symbols:
            binding = caller.imports_symbols[root]
            spec = binding.split("#", 1)[0]
            return "unresolved" if self._looks_like_internal_js_spec(caller.file, spec) else "external"
        return "unresolved"

    def _resolve_go_import(self, spec: str) -> Optional[str]:
        if not self.go_root_module or not spec.startswith(self.go_root_module):
            return None
        rel_dir = spec[len(self.go_root_module):].lstrip("/") or "."
        rel_dir = Path(rel_dir).as_posix()
        return self.go_dir_to_node.get(rel_dir)

    def _resolve_java_import(self, spec: str) -> Optional[str]:
        if spec.endswith(".*"):
            return None
        return self.java_type_to_node.get(spec) or self.java_member_to_node.get(spec)

    def _resolve_java_type_ref_outcome(
        self,
        caller: SymbolNode,
        raw_type: str,
        member_name: str = "",
        allow_di: bool = False,
        raw_call: str = "",
    ) -> ResolutionOutcome:
        cleaned = self._clean_java_type(raw_type)
        if not cleaned:
            return ResolutionOutcome(target=None)
        if caller.class_context and cleaned == caller.class_context:
            candidate = f"{caller.module}:{caller.class_context}"
            if candidate in self.nodes and self.nodes[candidate].kind in {"class", "enum", "interface"}:
                return self._resolution(target=candidate, kind="instance_dispatch", reason=f"Dispatched `{raw_call or member_name or cleaned}` to the current Java type.")
        target = self._resolve_non_python_base(caller, cleaned)
        if not target or target not in self.nodes or self.nodes[target].language != "Java":
            return ResolutionOutcome(target=None)
        if not allow_di or self._is_java_concrete_type(self.nodes[target]):
            return self._resolution(target=target, kind="instance_dispatch", reason=f"Resolved `{member_name or cleaned}` to concrete Java type `{self.nodes[target].qualname}`.")

        all_candidates = list(self.java_concrete_type_targets.get(target, []))
        qualifier = caller.member_qualifiers.get(member_name, "")
        if qualifier:
            qualifier_candidates = sorted(
                candidate for candidate in all_candidates if self._java_candidate_matches_qualifier(candidate, qualifier)
            )
            if len(qualifier_candidates) == 1:
                selected = qualifier_candidates[0]
                return self._resolution(
                    target=selected,
                    kind="java_di_qualifier",
                    reason=f"Qualifier `{qualifier}` selected Java implementation `{self.nodes[selected].qualname}`.",
                )
            if len(qualifier_candidates) > 1:
                return self._resolution(
                    target=None,
                    kind="ambiguous_candidates",
                    reason=f"Qualifier `{qualifier}` matched multiple Java implementations for `{member_name}`.",
                    candidates=qualifier_candidates,
                )
            return self._resolution(target=target, kind="instance_dispatch", reason=f"Kept declared Java type `{self.nodes[target].qualname}` after qualifier lookup.")

        primary_candidates = sorted(candidate for candidate in all_candidates if self.nodes[candidate].di_primary)
        if len(primary_candidates) == 1:
            selected = primary_candidates[0]
            return self._resolution(
                target=selected,
                kind="java_di_primary",
                reason=f"`@Primary` selected Java implementation `{self.nodes[selected].qualname}`.",
            )
        if len(primary_candidates) > 1:
            return self._resolution(
                target=None,
                kind="ambiguous_candidates",
                reason=f"Multiple `@Primary` Java implementations matched `{member_name}`.",
                candidates=primary_candidates,
            )

        if len(all_candidates) == 1:
            selected = all_candidates[0]
            return self._resolution(
                target=selected,
                kind="java_di_unique_impl",
                reason=f"Unique Java implementation `{self.nodes[selected].qualname}` matched declared type `{cleaned}`.",
            )
        if len(all_candidates) > 1:
            return self._resolution(
                target=None,
                kind="ambiguous_candidates",
                reason=f"Multiple Java implementations matched declared type `{cleaned}`.",
                candidates=all_candidates,
            )
        return self._resolution(target=target, kind="instance_dispatch", reason=f"Kept declared Java type `{self.nodes[target].qualname}` for dispatch.")

    def _resolve_java_type_ref(
        self,
        caller: SymbolNode,
        raw_type: str,
        member_name: str = "",
        allow_di: bool = False,
        raw_call: str = "",
    ) -> Optional[str]:
        return self._resolve_java_type_ref_outcome(
            caller,
            raw_type,
            member_name=member_name,
            allow_di=allow_di,
            raw_call=raw_call,
        ).target

    def _resolve_java_member_target(self, class_target: Optional[str], member_name: str) -> Optional[str]:
        if not class_target or class_target not in self.nodes or "." in member_name:
            return None
        visited: Set[str] = set()
        queue = deque([class_target])
        while queue:
            current_id = queue.popleft()
            if current_id in visited:
                continue
            visited.add(current_id)
            current = self.nodes[current_id]
            if current.language != "Java" or current.kind not in {"class", "enum", "interface"}:
                continue
            candidate = f"{current.module}:{current.qualname}.{member_name}"
            if candidate in self.nodes:
                return candidate
            for base_id in sorted(current.resolved_bases):
                queue.append(base_id)
        return None

    def _resolve_java_call_outcome(self, caller: SymbolNode, raw: str) -> ResolutionOutcome:
        class_ctx = caller.class_context
        normalized = raw[len("this."):] if raw.startswith("this.") else raw
        if normalized.startswith("super."):
            target = self._resolve_super_method(caller.module, class_ctx, normalized.split(".", 1)[1])
            if target:
                return self._resolution(target=target, kind="super_dispatch", reason=f"Resolved `{raw}` through Java super dispatch.")
            return ResolutionOutcome(target=None)
        if normalized in self.java_member_to_node:
            target = self.java_member_to_node[normalized]
            return self._resolution(target=target, kind="direct_symbol", reason=f"Resolved `{raw}` by exact Java member name.")
        if "." in normalized:
            head, tail = normalized.split(".", 1)
            if head in caller.member_types:
                type_outcome = self._resolve_java_type_ref_outcome(
                    caller,
                    caller.member_types[head],
                    member_name=head,
                    allow_di=True,
                    raw_call=normalized,
                )
                member_target = self._resolve_java_member_target(type_outcome.target, tail)
                if member_target:
                    if type_outcome.resolution_kind in {"java_di_primary", "java_di_qualifier", "java_di_unique_impl"}:
                        return self._resolution(
                            target=member_target,
                            kind=type_outcome.resolution_kind,
                            reason=type_outcome.resolution_reason,
                        )
                    return self._resolution(
                        target=member_target,
                        kind="instance_dispatch",
                        reason=f"Resolved `{raw}` through Java instance member `{head}`.",
                    )
                if type_outcome.resolution_kind == "ambiguous_candidates":
                    return type_outcome
            if head in caller.imports_symbols:
                imported = caller.imports_symbols[head]
                target = self._resolve_java_import(imported)
                member_target = self._resolve_java_member_target(target, tail)
                if member_target:
                    return self._resolution(target=member_target, kind="import_exact", reason=f"Resolved `{raw}` through exact Java import `{imported}`.")
                if target:
                    return self._resolution(target=target, kind="import_exact", reason=f"Resolved `{raw}` through exact Java import `{imported}`.")
            class_target = self._resolve_java_type_ref(caller, head)
            member_target = self._resolve_java_member_target(class_target, tail)
            if member_target:
                return self._resolution(target=member_target, kind="direct_symbol", reason=f"Resolved `{raw}` by exact Java type/member reference.")
            return ResolutionOutcome(target=None)
        if normalized in caller.imports_symbols:
            imported = caller.imports_symbols[normalized]
            target = self._resolve_java_import(imported)
            if target:
                return self._resolution(target=target, kind="import_exact", reason=f"Resolved `{raw}` through exact Java import `{imported}`.")
        if class_ctx:
            candidate = f"{caller.module}:{class_ctx}.{normalized}"
            if candidate in self.nodes:
                return self._resolution(target=candidate, kind="same_class_method", reason=f"Resolved `{raw}` on the current Java class.")
        candidates = [
            candidate for candidate in self.short_index.get(normalized, []) if self.nodes[candidate].language == "Java"
        ]
        if len(candidates) == 1:
            return self._resolution(target=candidates[0], kind="heuristic", reason=f"Resolved `{raw}` via unique Java short-name fallback.")
        return ResolutionOutcome(target=None)

    def _resolve_java_call(self, caller: SymbolNode, raw: str) -> Optional[str]:
        return self._resolve_java_call_outcome(caller, raw).target

    def _classify_java_call(self, caller: SymbolNode, raw: str) -> str:
        normalized = raw[len("this."):] if raw.startswith("this.") else raw
        root = normalized.split(".", 1)[0]
        if root in {"System", "Objects", "Collections", "List", "Map", "Set", "Optional", "String", "Math"}:
            return "external"
        if raw.startswith(("this.", "super.")):
            return "unresolved"
        if root in caller.member_types:
            return "unresolved"
        if root in caller.imports_symbols:
            imported = caller.imports_symbols[root]
            return "unresolved" if (imported in self.java_type_to_node or imported in self.java_member_to_node) else "external"
        return "unresolved"

    def _resolve_rust_import(self, caller: SymbolNode, raw: str) -> Optional[str]:
        current_module = caller.package_name or self._rust_module_path(caller.file)
        target = raw
        if raw.startswith("mod::"):
            child = raw.split("::", 1)[1]
            target = f"{current_module}::{child}" if current_module != "crate" else f"crate::{child}"
        elif raw.startswith("self::"):
            suffix = raw[len("self::"):]
            target = f"{current_module}::{suffix}" if current_module != "crate" else f"crate::{suffix}"
        elif raw.startswith("super::"):
            parent = current_module.rsplit("::", 1)[0] if "::" in current_module else "crate"
            suffix = raw[len("super::"):]
            target = f"{parent}::{suffix}" if parent != "crate" else f"crate::{suffix}"
        elif not raw.startswith("crate::"):
            target = f"crate::{raw}"

        parts = target.split("::")
        for size in range(len(parts), 0, -1):
            candidate = "::".join(parts[:size])
            if candidate in self.rust_module_to_node:
                return self.rust_module_to_node[candidate]
        return None

    def _classify_unresolved_import(self, caller: SymbolNode, raw: str) -> str:
        if caller.language in {"JavaScript", "TypeScript"}:
            return "unresolved" if self._looks_like_internal_js_spec(caller.file, raw) else "external"
        if caller.language == "Go":
            if self.go_root_module and raw.startswith(self.go_root_module):
                return "unresolved"
            return "external"
        if caller.language == "Java":
            if raw.endswith(".*"):
                package = raw[:-2]
                if any(fqcn.startswith(f"{package}.") for fqcn in self.java_type_to_node):
                    return "unresolved"
                return "external"
            if raw in self.java_type_to_node:
                return "unresolved"
            simple = raw.rsplit(".", 1)[-1]
            if any(fqcn.endswith(f".{simple}") for fqcn in self.java_type_to_node):
                return "unresolved"
            return "external"
        if caller.language == "Rust":
            if raw.startswith(("crate::", "self::", "super::", "mod::")):
                return "unresolved"
            return "external"
        return "unresolved"

    def _classify_non_python_base(self, caller: SymbolNode, raw: str) -> str:
        root = raw.split(".", 1)[0].split("::", 1)[0]
        if caller.language in {"JavaScript", "TypeScript"}:
            if root in caller.declared_symbols:
                return "ignore"
            spec = caller.imports_symbols.get(root) or caller.imports_modules.get(root)
            if not spec:
                return "unresolved"
            return "unresolved" if self._looks_like_internal_js_spec(caller.file, spec.split("#", 1)[0]) else "external"
        if caller.language == "Java":
            cleaned = re.sub(r"<.*?>", "", raw).strip()
            simple = cleaned.rsplit(".", 1)[-1]
            if simple in caller.declared_symbols:
                return "ignore"
            imported = caller.imports_symbols.get(simple)
            if imported:
                return "unresolved" if imported in self.java_type_to_node else "external"
            if caller.package_name and any(fqcn == f"{caller.package_name}.{simple}" for fqcn in self.java_type_to_node):
                return "unresolved"
            return "external" if "." in cleaned else "unresolved"
        return "unresolved"

    def _resolve_super_method(self, module: str, class_ctx: Optional[str], method: str) -> Optional[str]:
        if not class_ctx:
            return None
        class_id = f"{module}:{class_ctx}"
        if class_id not in self.nodes:
            return None

        visited: Set[str] = set()
        queue = deque(sorted(self.nodes[class_id].resolved_bases))
        while queue:
            base_id = queue.popleft()
            if base_id in visited:
                continue
            visited.add(base_id)
            base_node = self.nodes[base_id]
            candidate = f"{base_node.module}:{base_node.qualname}.{method}"
            if candidate in self.nodes:
                return candidate
            for parent in sorted(base_node.resolved_bases):
                if parent not in visited:
                    queue.append(parent)
        return None

    def _tarjan_scc(self) -> Tuple[List[List[str]], Dict[str, int]]:
        index = 0
        indices: Dict[str, int] = {}
        lowlink: Dict[str, int] = {}
        stack: List[str] = []
        on_stack: Set[str] = set()
        components: List[List[str]] = []

        for node_id in sorted(self.nodes):
            if node_id in indices:
                continue

            indices[node_id] = index
            lowlink[node_id] = index
            index += 1
            stack.append(node_id)
            on_stack.add(node_id)

            call_stack = [(node_id, iter(sorted(self.adj[node_id])), None)]
            while call_stack:
                v, neighbors, child = call_stack[-1]

                if child is not None:
                    lowlink[v] = min(lowlink[v], lowlink[child])
                    call_stack[-1] = (v, neighbors, None)
                    continue

                try:
                    w = next(neighbors)
                except StopIteration:
                    call_stack.pop()
                    if lowlink[v] == indices[v]:
                        comp: List[str] = []
                        while stack:
                            w = stack.pop()
                            on_stack.remove(w)
                            comp.append(w)
                            if w == v:
                                break
                        components.append(sorted(comp))
                    continue

                if w not in indices:
                    indices[w] = index
                    lowlink[w] = index
                    index += 1
                    stack.append(w)
                    on_stack.add(w)
                    call_stack[-1] = (v, neighbors, w)
                    call_stack.append((w, iter(sorted(self.adj[w])), None))
                elif w in on_stack:
                    lowlink[v] = min(lowlink[v], indices[w])

        node_to_scc: Dict[str, int] = {}
        for comp_id, comp in enumerate(components):
            for node_id in comp:
                node_to_scc[node_id] = comp_id
        return components, node_to_scc

    def _apply_scc(self, node_to_scc: Dict[str, int], sccs: List[List[str]]) -> None:
        for node_id, node in self.nodes.items():
            cid = node_to_scc[node_id]
            node.scc_id = cid
            node.scc_size = len(sccs[cid])

    def _compute_layers(self, node_to_scc: Dict[str, int], sccs: List[List[str]]) -> None:
        comp_edges: Dict[int, Set[int]] = defaultdict(set)
        indegree: Dict[int, int] = {i: 0 for i in range(len(sccs))}

        for src, dsts in self.adj.items():
            c_src = node_to_scc[src]
            for dst in dsts:
                c_dst = node_to_scc[dst]
                if c_src == c_dst:
                    continue
                if c_dst not in comp_edges[c_src]:
                    comp_edges[c_src].add(c_dst)
                    indegree[c_dst] += 1

        queue = deque(sorted(cid for cid, deg in indegree.items() if deg == 0))
        depth: Dict[int, int] = {cid: 0 for cid in indegree}
        topo: List[int] = []

        while queue:
            cid = queue.popleft()
            topo.append(cid)
            for nxt in sorted(comp_edges[cid]):
                if depth[nxt] < depth[cid] + 1:
                    depth[nxt] = depth[cid] + 1
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)

        # If graph was disconnected from Kahn roots due to malformed indegrees, keep deterministic fallback.
        if len(topo) < len(sccs):
            for cid in sorted(set(range(len(sccs))) - set(topo)):
                depth.setdefault(cid, 0)

        for node_id, node in self.nodes.items():
            node.layer = depth.get(node_to_scc[node_id], 0)

    def _compute_pagerank(self, damping: float = 0.85, iterations: int = 30) -> None:
        node_ids = sorted(self.nodes)
        n = len(node_ids)
        if n == 0:
            return

        pr: Dict[str, float] = {nid: 1.0 / n for nid in node_ids}
        inbound: Dict[str, Set[str]] = defaultdict(set)
        outdeg: Dict[str, int] = {}

        for nid in node_ids:
            targets = self.adj[nid]
            outdeg[nid] = len(targets)
            for target in targets:
                inbound[target].add(nid)

        base = (1.0 - damping) / n
        for _ in range(iterations):
            sink_total = sum(pr[nid] for nid in node_ids if outdeg[nid] == 0)
            nxt: Dict[str, float] = {}
            for nid in node_ids:
                score = base + damping * sink_total / n
                for src in inbound[nid]:
                    score += damping * pr[src] / outdeg[src]
                nxt[nid] = score
            pr = nxt

        for nid in node_ids:
            self.nodes[nid].pagerank = round(pr[nid], 8)

    def _compute_betweenness(self) -> None:
        node_ids = sorted(self.nodes)
        n = len(node_ids)
        if n < 3:
            for node in self.nodes.values():
                node.betweenness = 0.0
            return

        centrality: Dict[str, float] = {nid: 0.0 for nid in node_ids}
        for source in node_ids:
            stack: List[str] = []
            predecessors: Dict[str, List[str]] = {nid: [] for nid in node_ids}
            sigma: Dict[str, float] = {nid: 0.0 for nid in node_ids}
            sigma[source] = 1.0
            distance: Dict[str, int] = {nid: -1 for nid in node_ids}
            distance[source] = 0
            queue = deque([source])

            while queue:
                vertex = queue.popleft()
                stack.append(vertex)
                for neighbor in sorted(self.adj[vertex]):
                    if distance[neighbor] < 0:
                        queue.append(neighbor)
                        distance[neighbor] = distance[vertex] + 1
                    if distance[neighbor] == distance[vertex] + 1:
                        sigma[neighbor] += sigma[vertex]
                        predecessors[neighbor].append(vertex)

            dependency: Dict[str, float] = {nid: 0.0 for nid in node_ids}
            while stack:
                vertex = stack.pop()
                if sigma[vertex] == 0:
                    continue
                for predecessor in predecessors[vertex]:
                    dependency[predecessor] += (sigma[predecessor] / sigma[vertex]) * (1.0 + dependency[vertex])
                if vertex != source:
                    centrality[vertex] += dependency[vertex]

        scale = 1.0 / ((n - 1) * (n - 2))
        for node_id in node_ids:
            self.nodes[node_id].betweenness = round(centrality[node_id] * scale, 8)

    def _compute_git_hotspots(self, enabled: bool) -> None:
        self.git_hotspot_enabled = False
        self.git_tracked_file_count = 0
        for node in self.nodes.values():
            node.git_commit_count = 0
            node.git_churn = 0
            node.git_hotness = 0.0

        if not enabled:
            return

        try:
            probe = subprocess.run(
                ["git", "-C", self.root_dir, "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return

        if probe.returncode != 0 or probe.stdout.strip() != "true":
            return

        log_result = subprocess.run(
            [
                "git",
                "-C",
                self.root_dir,
                "log",
                "--numstat",
                "--no-renames",
                "--format=tformat:",
                "--relative=.",
                "--",
                ".",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if log_result.returncode != 0:
            return

        file_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"commits": 0, "churn": 0})
        for raw_line in log_result.stdout.splitlines():
            parts = raw_line.split("\t")
            if len(parts) != 3:
                continue
            added, deleted, path = parts
            if added == "-" or deleted == "-":
                continue
            norm_path = os.path.normpath(path)
            if norm_path.startswith("..") or Path(norm_path).suffix.lower() not in LANGUAGE_BY_SUFFIX:
                continue
            try:
                churn = int(added) + int(deleted)
            except ValueError:
                continue
            file_stats[norm_path]["commits"] += 1
            file_stats[norm_path]["churn"] += churn

        if not file_stats:
            return

        raw_scores: Dict[str, float] = {}
        for file_name, stats in file_stats.items():
            raw_scores[file_name] = (math.log1p(stats["churn"]) * 0.7) + (math.log1p(stats["commits"]) * 0.3)

        max_score = max(raw_scores.values()) or 1.0
        self.git_hotspot_enabled = True
        self.git_tracked_file_count = len(file_stats)
        for node in self.nodes.values():
            stats = file_stats.get(os.path.normpath(node.file))
            if not stats:
                continue
            node.git_commit_count = stats["commits"]
            node.git_churn = stats["churn"]
            node.git_hotness = round(raw_scores[os.path.normpath(node.file)] / max_score, 8)

    def _compute_coords(self) -> None:
        modules = sorted({n.module for n in self.nodes.values()})
        if not modules:
            return
        grid = int(math.ceil(math.sqrt(len(modules))))
        base_xy: Dict[str, Tuple[float, float]] = {}
        for idx, mod in enumerate(modules):
            row, col = divmod(idx, grid)
            base_xy[mod] = (col * 20.0, row * 20.0)

        for node_id, node in self.nodes.items():
            bx, by = base_xy[node.module]
            x = round(bx + stable_jitter(node_id, "x"), 3)
            y = round(by + stable_jitter(node_id, "y"), 3)
            z = round(-float(node.layer), 3)
            node.coord = [x, y, z]

    def _compute_risk_scores(self) -> None:
        if not self.nodes:
            return
        max_ca = max((node.ca for node in self.nodes.values()), default=1) or 1
        max_ce_internal = max((node.ce_internal for node in self.nodes.values()), default=1) or 1
        max_ce_external = max((node.ce_external for node in self.nodes.values()), default=1) or 1
        max_pr = max((node.pagerank for node in self.nodes.values()), default=1.0) or 1.0
        max_bridge = max((node.betweenness for node in self.nodes.values()), default=1.0) or 1.0
        max_git_hotness = max((node.git_hotness for node in self.nodes.values()), default=1.0) or 1.0

        for node in self.nodes.values():
            norm_ca = node.ca / max_ca
            norm_ce_internal = node.ce_internal / max_ce_internal
            norm_ce_external = node.ce_external / max_ce_external
            norm_pr = node.pagerank / max_pr
            norm_bridge = node.betweenness / max_bridge
            norm_git_hotness = node.git_hotness / max_git_hotness
            cycle_flag = 1.0 if node.scc_size > 1 else 0.0
            recursion_flag = 1.0 if (node.recursive_self_call and node.ca >= 2) else 0.0
            upper_layer_pressure = 1.0 if (node.layer <= 1 and node.ce_internal >= 2) else 0.0

            risk = (
                0.24 * node.instability
                + 0.20 * norm_ca
                + 0.14 * norm_bridge
                + 0.12 * norm_ce_internal
                + 0.10 * norm_pr
                + 0.08 * norm_git_hotness
                + 0.06 * cycle_flag
                + 0.03 * recursion_flag
                + 0.02 * upper_layer_pressure
                + 0.01 * norm_ce_external
            )
            node.risk_score = round(risk * 100.0, 2)
            node.reasons = self._reasons_for(
                node,
                max_ca=max_ca,
                max_ce_internal=max_ce_internal,
                max_bridge=max_bridge,
            )

    def _reasons_for(self, node: SymbolNode, max_ca: int, max_ce_internal: int, max_bridge: float) -> List[str]:
        reasons: List[str] = []
        if node.instability >= 0.8 and node.ce_internal >= 2:
            reasons.append("High internal instability: many outgoing project dependencies relative to incoming.")
        if node.ca >= max(3, int(math.ceil(max_ca * 0.6))):
            reasons.append("High afferent coupling (Ca): many dependents, high blast radius.")
        if node.ce_internal >= max(3, int(math.ceil(max_ce_internal * 0.6))):
            reasons.append("High internal efferent coupling (Ce): broad dependency surface inside the project.")
        if node.scc_size > 1:
            reasons.append(f"Part of dependency cycle (SCC size {node.scc_size}).")
        if node.betweenness >= max(0.05, max_bridge * 0.6):
            reasons.append("High bridge centrality: change here can disrupt many shortest dependency paths.")
        if node.recursive_self_call and node.ca >= 2:
            reasons.append("Self-recursive and widely depended upon: verify termination and API stability.")
        if node.layer <= 1 and node.ce_internal >= 2:
            reasons.append("High fan-out near upper architectural layers.")
        if node.resolved_bases:
            reasons.append("Inheritance-linked node: verify whether coupling belongs in inheritance or composition.")
        if node.ce_external >= 5 and node.ce_internal >= 1:
            reasons.append("Large external API surface: consider wrapping vendor/library touchpoints.")
        if self.git_hotspot_enabled and node.git_hotness >= 0.7 and (node.ca >= 1 or node.ce_internal >= 2):
            reasons.append("Git hotspot: this file changes often, so structural issues here are more likely to hurt.")
        if not reasons and node.risk_score >= 55.0:
            reasons.append("Combined coupling pressure from multiple metrics.")
        if node.semantic_signals:
            critical = [s for s in node.semantic_signals if s in SEMANTIC_CRITICAL_SIGNALS]
            if critical and (node.instability >= 0.7 or node.ca >= 3 or node.ce_internal >= 3):
                reasons.append(
                    f"Carries critical semantic signals ({', '.join(sorted(critical))}) under structural pressure — verify change safety."
                )
        return reasons

    def _sort_semantic_signals(self, signals: Iterable[str]) -> List[str]:
        unique = {signal for signal in signals if signal}
        return sorted(
            unique,
            key=lambda signal: (-SEMANTIC_SIGNAL_WEIGHTS.get(signal, 0.0), signal),
        )

    def _semantic_ref_sort_key(self, ref: Dict[str, object]) -> Tuple[float, int, int, str, str]:
        lines = ref.get("lines", [0, 0])
        start = int(lines[0]) if isinstance(lines, list) and lines else 0
        end = int(lines[1]) if isinstance(lines, list) and len(lines) > 1 else start
        signal = str(ref.get("signal", ""))
        return (
            -SEMANTIC_SIGNAL_WEIGHTS.get(signal, 0.0),
            start,
            end,
            signal,
            str(ref.get("reason", "")),
        )

    def _dedupe_semantic_refs(self, refs: List[Dict[str, object]], limit: int = 12) -> List[Dict[str, object]]:
        seen: Set[str] = set()
        out: List[Dict[str, object]] = []
        for ref in sorted(refs, key=self._semantic_ref_sort_key):
            key = json.dumps(ref, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            out.append(ref)
            if len(out) >= limit:
                break
        return out

    def _semantic_refs_for_node(self, node_id: str, limit: int = 3) -> List[Dict[str, object]]:
        node = self.nodes.get(node_id)
        if node is None or not node.semantic_evidence_spans:
            return []
        return self._dedupe_semantic_refs(list(node.semantic_evidence_spans), limit=limit)

    def _contained_semantic_refs_for_node(self, node_id: str, limit: int = 4) -> List[Dict[str, object]]:
        node = self.nodes.get(node_id)
        if node is None or not node.contained_semantic_refs:
            return []
        return self._dedupe_semantic_refs(list(node.contained_semantic_refs), limit=limit)

    def _semantic_child_nodes(self, node: SymbolNode) -> List[SymbolNode]:
        children: List[SymbolNode] = []
        start_line = int(node.lines[0])
        end_line = int(node.lines[1])
        for candidate in self.nodes.values():
            if candidate.node_id == node.node_id or candidate.file != node.file:
                continue
            candidate_start = int(candidate.lines[0])
            candidate_end = int(candidate.lines[1])
            if candidate_start < start_line or candidate_end > end_line:
                continue
            if node.kind == "module":
                if candidate.kind == "module":
                    continue
                children.append(candidate)
                continue
            if node.kind not in SEMANTIC_CONTAINER_KINDS:
                continue
            if candidate.kind == "module":
                continue
            if candidate.class_context == node.qualname or candidate.qualname.startswith(f"{node.qualname}."):
                children.append(candidate)
        children.sort(
            key=lambda child: (
                int(child.lines[0]),
                int(child.lines[1]),
                child.kind,
                child.node_id,
            )
        )
        return children

    def _node_source_lines(self, node: SymbolNode, direct_semantics: bool = False) -> List[Tuple[int, str]]:
        lines = self._read_project_lines(node.file)
        if not lines:
            return []
        start = max(1, min(int(node.lines[0]), len(lines)))
        end = max(start, min(int(node.lines[1]), len(lines)))
        if not direct_semantics or node.kind in SEMANTIC_EXECUTABLE_KINDS:
            return [(lineno, lines[lineno - 1]) for lineno in range(start, end + 1)]
        excluded_lines: Set[int] = set()
        for child in self._semantic_child_nodes(node):
            child_start = max(start, int(child.lines[0]))
            child_end = min(end, int(child.lines[1]))
            excluded_lines.update(range(child_start, child_end + 1))
        return [
            (lineno, lines[lineno - 1])
            for lineno in range(start, end + 1)
            if lineno not in excluded_lines
        ]

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

    def _guard_signal_for_window(
        self,
        source_lines: List[Tuple[int, str]],
        index: int,
        lookahead: int = 2,
    ) -> Optional[Tuple[str, int, str]]:
        _, text = source_lines[index]
        if not re.search(r"\bif\b", text):
            return None
        window = source_lines[index:min(len(source_lines), index + lookahead + 1)]
        combined = " ".join(line for _, line in window)
        combined_lower = combined.lower()
        action_lineno = 0
        for lineno, candidate in window:
            candidate_lower = candidate.lower()
            if any(pattern in candidate_lower for pattern in SEMANTIC_GUARD_ACTION_PATTERNS):
                action_lineno = lineno
                break
        if not action_lineno:
            return None
        if any(keyword in combined_lower for keyword in SEMANTIC_AUTH_KEYWORDS):
            return ("auth_guard", action_lineno, "Guard checks authorization or permissions before continuing.")
        if self._looks_like_validation_guard(combined):
            return ("validation_guard", action_lineno, "Guard rejects invalid or missing input before continuing.")
        return None

    def _record_semantic_ref(
        self,
        refs: List[Dict[str, object]],
        node: SymbolNode,
        signal: str,
        start_line: int,
        end_line: int,
        reason: str,
    ) -> None:
        refs.append(
            {
                "signal": signal,
                "file": node.file,
                "lines": [start_line, max(start_line, end_line)],
                "reason": reason,
            }
        )

    def _has_direct_js_like_network_call(self, text: str) -> bool:
        stripped = text.strip()
        if re.match(
            r"^(?:export\s+)?(?:default\s+)?(?:public\s+|private\s+|protected\s+|static\s+|readonly\s+|override\s+)*"
            r"(?:async\s+)?fetch\s*\([^)]*\)\s*\{",
            stripped,
        ):
            return False
        if re.match(
            r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+fetch\s*\(",
            stripped,
        ):
            return False
        if re.search(r"(?<![\w$.])fetch\s*\(", text):
            return True
        if re.search(r"\baxios(?:\.[A-Za-z_]\w*)?\s*\(", text):
            return True
        if re.search(r"\bhttps?\.request\s*\(", text):
            return True
        return False

    def _extract_semantic_signals(self) -> None:
        for node in self.nodes.values():
            node.semantic_signals.clear()
            node.semantic_evidence_spans.clear()
            node.semantic_summary = {}
            node.semantic_weight = 0.0
            node.contained_semantic_signals.clear()
            node.contained_semantic_refs.clear()
            node.contained_semantic_summary = {}
            node.contained_semantic_weight = 0.0

            source_lines = self._node_source_lines(node, direct_semantics=True)
            if not source_lines:
                continue

            refs: List[Dict[str, object]] = []
            if node.language == "Python":
                refs = self._extract_python_semantic_spans(node, source_lines)
            elif node.language == "Java":
                refs = self._extract_java_semantic_spans(node, source_lines)
            elif node.language in {"JavaScript", "TypeScript"}:
                refs = self._extract_js_like_semantic_spans(node, source_lines)
            elif node.language == "Go":
                refs = self._extract_go_semantic_spans(node, source_lines)
            elif node.language == "Rust":
                refs = self._extract_rust_semantic_spans(node, source_lines)
            elif node.language == "CSharp":
                refs = self._extract_csharp_semantic_spans(node, source_lines)
            elif node.language == "Kotlin":
                refs = self._extract_kotlin_semantic_spans(node, source_lines)
            elif node.language == "PHP":
                refs = self._extract_php_semantic_spans(node, source_lines)
            elif node.language == "Ruby":
                refs = self._extract_ruby_semantic_spans(node, source_lines)

            refs = self._dedupe_semantic_refs(refs, limit=12)
            io_refs = [ref for ref in refs if str(ref.get("signal", "")) in SEMANTIC_EXTERNAL_IO_SIGNALS]
            if io_refs and not any(str(ref.get("signal", "")) == "external_io" for ref in refs):
                primary_ref = sorted(io_refs, key=self._semantic_ref_sort_key)[0]
                refs.append(
                    {
                        "signal": "external_io",
                        "file": node.file,
                        "lines": list(primary_ref["lines"]),
                        "reason": f"Touches an external boundary via `{primary_ref['signal']}`.",
                    }
                )
                refs = self._dedupe_semantic_refs(refs, limit=12)

            signals = self._sort_semantic_signals(str(ref.get("signal", "")) for ref in refs)
            node.semantic_signals = signals
            node.semantic_evidence_spans = refs
            node.semantic_weight = round(sum(SEMANTIC_SIGNAL_WEIGHTS.get(signal, 0.0) for signal in signals), 2)
            if signals:
                node.semantic_summary = self._semantic_summary_for_node(node, signals, refs)
        self._populate_contained_semantics()

    def _populate_contained_semantics(self) -> None:
        for node in self.nodes.values():
            if node.kind not in SEMANTIC_CONTAINER_KINDS:
                continue
            refs: List[Dict[str, object]] = []
            descendant_nodes = [
                child
                for child in self._semantic_child_nodes(node)
                if child.semantic_signals
            ]
            for child in descendant_nodes:
                refs.extend(list(child.semantic_evidence_spans))
            refs = self._dedupe_semantic_refs(refs, limit=12)
            signals = self._sort_semantic_signals(str(ref.get("signal", "")) for ref in refs)
            node.contained_semantic_signals = signals
            node.contained_semantic_refs = refs
            node.contained_semantic_weight = round(
                sum(SEMANTIC_SIGNAL_WEIGHTS.get(signal, 0.0) for signal in signals),
                2,
            )
            if signals:
                node.contained_semantic_summary = {
                    "signal_count": len(signals),
                    "evidence_count": len(refs),
                    "descendant_node_count": len(descendant_nodes),
                    "top_signal": signals[0],
                    "boundary_signals": [signal for signal in signals if signal in SEMANTIC_BOUNDARY_SIGNALS],
                    "side_effect_signals": [signal for signal in signals if signal in SEMANTIC_SIDE_EFFECT_SIGNALS],
                    "guard_signals": [signal for signal in signals if signal in SEMANTIC_GUARD_SIGNALS],
                }

    def _extract_python_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            lower = text.lower()
            stripped = lower.strip()
            if (
                re.search(r"\b(?:requests|httpx|urllib(?:\.request)?|aiohttp\.ClientSession)\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bboto3\.(?:client|resource|Session)\s*\(", text)
                or re.search(r"\bbotocore\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bgrpc\.(?:insecure_channel|secure_channel)\s*\(", text)
                or re.search(r"\bgoogle\.cloud\.", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a Python HTTP or cloud client.")
            if (
                re.search(r"\bopen\s*\(", text)
                or re.search(r"\bPath\s*\(", text)
                or re.search(r"\.(?:read_text|write_text|read_bytes|write_bytes)\s*\(", text)
                or re.search(r"\bos\.(?:remove|unlink|rename|replace|makedirs)\s*\(", text)
                or re.search(r"\bshutil\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\baiofiles\.open\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno, "Touches the filesystem from Python code.")
            if (
                re.search(r"\b(?:subprocess\.[A-Za-z_]\w*|os\.(?:system|popen|spawnv|execv)|asyncio\.create_subprocess_(?:exec|shell))\s*\(", text)
                or re.search(r"@(?:\w+\.)?(?:task|shared_task)\s*(?:\(|$)", text)
            ):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno, "Starts or controls a process from Python code.")
            if (
                re.search(r"\b(?:sqlite3|aiosqlite)\.connect\s*\(", text)
                or re.search(r"\b(?:cursor|session|db|conn|connection)\.(?:execute|query|commit|rollback|add|delete|merge|get)\s*\(", text)
                or re.search(r"\.objects\.(?:filter|get|create|update|delete|all|exclude|annotate|aggregate|bulk_create)\s*\(", text)
                or re.search(r"\bself\.[A-Za-z_]\w*\.(?:save|delete)\s*\(\s*\)", text)
                or re.search(r"\b(?:conn|connection)\.(?:fetch|fetchrow|fetchval|execute)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Touches a database or session API.")
            if re.search(r"\bos\.(?:environ|getenv)\b", text) or re.search(r"\b(?:configparser|dotenv)\b", text) or re.search(r"\btomllib\.(?:load|loads)\s*\(", text):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads configuration or environment state.")
            if re.search(r"\b(?:json|pickle|yaml)\.(?:dump|dumps|safe_dump)\s*\(", text):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes structured data.")
            if re.search(r"\b(?:json|pickle|yaml)\.(?:load|loads|safe_load)\s*\(", text):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes structured data.")
            if re.search(r"\b(?:datetime\.(?:now|utcnow)|time\.[A-Za-z_]\w*|random\.[A-Za-z_]\w*|uuid\.[A-Za-z_]\w*|secrets\.[A-Za-z_]\w*)\s*\(", text):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno, "Uses time or randomness sources.")
            if (
                re.search(r"\bself\.[A-Za-z_]\w*\s*=", text)
                or re.search(r"\bself\.[A-Za-z_]\w*\[", text)
                or re.search(r"\bself\.[A-Za-z_]\w*\.(?:append|extend|insert|update|setdefault|pop|remove|clear|add|discard)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates object state via `self`.")
            if (
                re.search(r"\binput\s*\(", text)
                or re.search(r"@\w*(?:route|get|post|put|delete|patch)\b", lower)
                or re.search(r"\brequest\.(?:GET|POST|data|body|json|form|files|args)\b", text)
                or re.search(r"\b(?:Body|Query|Path|Form|Header|Cookie|Depends)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Reads data at an input boundary.")
            if re.search(
                r"\b(?:jsonify|Response|JSONResponse|HTMLResponse|StreamingResponse|FileResponse|"
                r"ORJSONResponse|RedirectResponse|PlainTextResponse|UJSONResponse|"
                r"HttpResponse|JsonResponse|HttpResponseRedirect|StreamingHttpResponse)\s*\(",
                text,
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Produces boundary-facing output.")
            if re.search(r"@(?:login_required|permission_required|jwt_required|token_required|requires_auth|authenticated|auth_required|requires_permission)\b", text):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "Auth/permission decorator guards this callable.")
            if (
                re.search(r"\bmodel_validate(?:_json)?\s*\(", text)
                or re.search(r"\bBaseModel\s*\(", text)
                or re.search(r"\b(?:schema|Schema)\.(?:load|loads|validate)\s*\(", text)
                or re.search(r"\b(?:form|serializer)\.(?:is_valid|validate)\s*\(", text)
                or re.search(r"\.validate_on_submit\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Invokes schema or form validation.")
            if stripped.startswith("try:") or stripped.startswith("except") or re.search(r"\braise\b", lower):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno, "Contains explicit Python error handling.")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs

    def _extract_java_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            lower = text.lower()
            stripped = lower.strip()
            if stripped.startswith("import ") or stripped.startswith("package "):
                continue
            if re.search(r"@(?:RestController|Controller|RequestMapping|GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestParam|RequestBody|PathVariable)\b", text):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Framework annotation marks a request boundary.")
            if (
                re.search(r"@(?:PreAuthorize|RolesAllowed|Secured)\b", text)
                or re.search(r"\bSecurityContextHolder\.getContext\(\)", text)
                or re.search(r"\bauthenticationManager\.authenticate\s*\(", text)
                or re.search(r"\bjwtService\.(?:validate|verify|parseToken|extractUsername)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "Security annotation guards the execution path.")
            if re.search(r"@(?:Valid|Validated|NotNull|NotBlank|NotEmpty|Size|Min|Max|Pattern)\b", text) or "objects.requirenonnull" in lower:
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Validation annotation or guard constrains inputs.")
            if "responseentity" in lower or "@responsebody" in lower or re.search(r"\breturn\s+ResponseEntity\.", text):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Returns a boundary-facing response object.")
            if re.search(r"\b(?:RestTemplate|WebClient|HttpClient|OkHttpClient|Feign|CloseableHttpClient|HttpGet|HttpPost|HttpPut|HttpDelete|HttpPatch)\b", text):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a Java HTTP client.")
            if re.search(r"\b(?:Files|Paths|FileInputStream|FileOutputStream|BufferedWriter|BufferedReader)\b", text):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno, "Touches the filesystem from Java code.")
            if re.search(r"\b(?:ProcessBuilder|Runtime\.getRuntime\(\)\.exec)\b", text):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno, "Starts or controls a process from Java code.")
            if (
                re.search(r"\b(?:System\.getenv|System\.getProperty)\s*\(", text)
                or re.search(r"@(?:Value|ConfigurationProperties)\b", text)
                or re.search(r"\benv\.getProperty\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads configuration or environment state.")
            if re.search(r"\b(?:ObjectMapper|Gson)\.(?:writeValue|writeValueAsString|toJson)\s*\(", text):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes structured data.")
            if re.search(r"\b(?:ObjectMapper|Gson)\.(?:readValue|fromJson)\s*\(", text):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes structured data.")
            if re.search(r"\b(?:Instant\.now|LocalDate(?:Time)?\.now|System\.currentTimeMillis|Random|ThreadLocalRandom|UUID\.randomUUID)\b", text):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno, "Uses time or randomness sources.")
            if re.search(r"\bthis\.[A-Za-z_]\w*\s*=", text):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates object state via `this`.")
            if re.search(r"\b(?:try|catch)\b", text) or re.search(r"\bthrow\b", text):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno, "Contains explicit Java error handling.")
            if re.search(r"\b(?:jdbcTemplate|entityManager)\.[A-Za-z_]\w*\s*\(", text) or re.search(r"\.(?:findById|save|delete|createQuery|queryForObject|query)\s*\(", text):
                repository_match = any(
                    member_type.endswith("Repository")
                    and re.search(rf"\b(?:this\.)?{re.escape(member_name)}\.[A-Za-z_]\w*\s*\(", text)
                    for member_name, member_type in node.member_types.items()
                )
                if repository_match or "jdbctemplate" in lower or "entitymanager" in lower:
                    self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Calls a repository or database-oriented dependency.")
            if re.search(r"@(?:Transactional|Query|Modifying|NamedQuery|NativeQuery)\b", text):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Calls a repository or database-oriented dependency.")
            if re.search(
                r"@(?:KafkaListener|RabbitListener|SqsListener|EventListener|JmsListener)\b",
                text,
            ):
                self._record_semantic_ref(
                    refs, node, "input_boundary", lineno, lineno,
                    "Message-listener annotation marks this method as a queue/event consumer.",
                )
            if re.search(r"@Async\b", text):
                self._record_semantic_ref(
                    refs, node, "process_io", lineno, lineno,
                    "@Async marks a method that runs in a separate thread pool.",
                )
            if re.search(r"@(?:Cacheable|CacheEvict|CachePut|Caching)\b", text):
                self._record_semantic_ref(
                    refs, node, "state_mutation", lineno, lineno,
                    "Spring cache annotation reads or mutates a shared cache store.",
                )
            if re.search(r"@Scheduled\b", text):
                self._record_semantic_ref(
                    refs, node, "time_or_randomness", lineno, lineno,
                    "@Scheduled drives execution by a time-based trigger.",
                )
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs

    def _extract_js_like_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            lower = text.lower()
            if self._has_direct_js_like_network_call(text):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a JavaScript/TypeScript network client.")
            if re.search(r"\b(?:fs|fs/promises)\b", lower) or re.search(r"\b(?:readFile|writeFile|appendFile|mkdir|unlink|rm)\s*\(", text):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno, "Touches the filesystem from JS/TS code.")
            if re.search(r"\b(?:child_process|exec|execSync|spawn|spawnSync|fork)\s*\(", text):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno, "Starts or controls a process from JS/TS code.")
            if "process.env" in lower or "import.meta.env" in lower:
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads runtime configuration or environment variables.")
            if re.search(r"\bJSON\.stringify\s*\(", text):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes data to JSON.")
            if re.search(r"\bJSON\.parse\s*\(", text) or re.search(r"\bresponse\.json\s*\(", lower):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes data from JSON.")
            if re.search(r"\b(?:Date\.now|new Date|Math\.random|crypto\.randomUUID)\b", text):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno, "Uses time or randomness sources.")
            if re.search(r"\bthis\.[A-Za-z_$][\w$]*\s*=", text):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates object state via `this`.")
            if re.search(r"\b(?:try|catch)\b", text) or re.search(r"\bthrow\b", text):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno, "Contains explicit JS/TS error handling.")
            if re.search(r"\b(?:function|async function)\b", text) and re.search(r"\((?:[^)]*\b(?:req|request|res|response)\b[^)]*)\)", text):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Handler signature accepts request/response boundary objects.")
            if re.search(r"\b(?:req|request)\.(?:body|query|params|headers)\b", lower) or re.search(r"\brequest\.(?:json|formData)\s*\(", text):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Reads request-boundary input data.")
            if (
                re.search(r"@(?:Get|Post|Put|Delete|Patch|Options|Head)\s*\(", text)
                or re.search(r"@(?:Body|Param|Query|Headers|Req|Res|UploadedFile)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "NestJS route or parameter decorator marks an input boundary.")
            if re.search(r"\b(?:res\.(?:json|send|status|render|sendFile|download|redirect)|NextResponse|Response\.json|new Response)\b", text):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Produces boundary-facing output.")
            if (
                re.search(r"\bprisma\.[A-Za-z_]\w*\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\b(?:mongoose|Model)\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\b(?:getRepository|getConnection|createQueryBuilder)\s*\(", text)
                or re.search(r"\bknex\s*\(", text)
                or re.search(r"\b(?:pool|client|db)\.(?:query|execute|connect)\s*\(", text)
                or re.search(r"\bdrizzle\s*\(", text)
                or re.search(r"\bdb\.(?:select|insert|update|delete)\s*\(\s*\)", text)
                or re.search(r"\bnew (?:Redis|IORedis)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Calls a JS/TS database client.")
            if (
                re.search(r"\bjwt\.(?:verify|decode|sign)\s*\(", text)
                or re.search(r"\bpassport\.(?:authenticate|authorize)\s*\(", text)
                or re.search(r"\b(?:verifyToken|checkAuth|requireAuth|isAuthenticated|ensureLoggedIn)\s*\(", text)
                or re.search(r"\bbcrypt\.(?:hash|compare|hashSync|compareSync)\s*\(", text)
                or re.search(r"\bargon2\.(?:hash|verify)\s*\(", text)
                or re.search(r"@UseGuards\s*\(", text)
                or re.search(r"\bsupabase\.auth\.[A-Za-z_]\w*\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "Enforces authentication or token verification.")
            if (
                re.search(r"\bz\.[a-z]\w*\(\s*\)\.(?:parse|safeParse|parseAsync)\s*\(", text)
                or re.search(r"\bz\.(?:parse|safeParse)\s*\(", text)
                or re.search(r"\b(?:schema|Schema)\.(?:parse|validate|validateSync|validateAsync)\s*\(", text)
                or re.search(r"\bjoi\.[a-z]\w*\(\s*\)\.validate\s*\(", text)
                or re.search(r"\b(?:yup\.|Yup\.)\w+\(\s*\)\.validate\s*\(", text)
                or re.search(
                    r"@(?:IsEmail|IsString|IsNumber|IsInt|IsBoolean|IsDate|IsOptional|IsNotEmpty|"
                    r"IsArray|IsUUID|Length|MinLength|MaxLength|IsEnum|Matches|IsNotEmptyObject)\s*\(",
                    text,
                )
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Invokes schema validation (Zod/Joi/Yup).")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs

    def _extract_go_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            if (
                re.search(r"\bhttp\.(?:Get|Post|Head|PostForm|NewRequest)\s*\(", text)
                or re.search(r"\bclient\.(?:Do|Get|Post|Head)\s*\(", text)
                or re.search(r"\bresty\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bgrpc\.(?:Dial|NewClient)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a Go HTTP or gRPC client.")
            if (
                re.search(r"\b(?:db\.(?:Query|Exec)|sql\.Open)\s*\(", text)
                or re.search(r"\bdb\.(?:Where|Find|First|Last|Create|Save|Delete|Update|Updates|Preload|Joins)\s*\(", text)
                or re.search(r"\b(?:pgxpool|pgx)\.(?:New|Connect)\s*\(", text)
                or re.search(r"\b(?:pool|conn)\.(?:QueryRow|Query|Exec|Begin|SendBatch)\s*\(", text)
                or re.search(r"\bredis\.NewClient\s*\(", text)
                or re.search(r"\bmongo\.(?:Connect|NewClient)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Touches a Go database handle.")
            if re.search(r"\b(?:os\.Open|os\.Create|os\.WriteFile|os\.ReadFile|ioutil\.ReadFile|bufio\.New(?:Reader|Writer|Scanner))\s*\(", text):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno, "Touches the filesystem from Go code.")
            if re.search(r"\bexec\.Command\s*\(", text):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno, "Starts a process from Go code.")
            if (
                re.search(r"\bos\.(?:Getenv|LookupEnv)\s*\(", text)
                or re.search(r"\bviper\.(?:Get|GetString|GetInt(?:Slice)?|GetBool|GetFloat64|GetDuration|GetStringSlice|GetStringMap|GetStringMapString)\s*\(", text)
                or re.search(r"\bgodotenv\.(?:Load|Overload|Read)\s*\(", text)
                or re.search(r"\benvconfig\.Process\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads environment or configuration state.")
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
            if "if err != nil" in text:
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno, "Contains explicit Go error handling.")
            if re.search(r"\b(?:time\.Now|rand\.)\b", text):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno, "Uses time or randomness sources.")
            if (
                re.search(r"\br\.Header\.Get\s*\(\s*[\"']Authorization", text)
                or re.search(r"\bjwt\.(?:Parse|ParseWithClaims|Valid)\b", text)
                or re.search(r"\b(?:Middleware|middleware)\.(?:Auth|JWT|Token|Bearer)\b", text)
                or re.search(r"\bctx\.Value\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "Enforces authentication in Go code.")
            if (
                re.search(r"\bvalidate\.(?:Struct|Var|StructPartial|StructExcept|VarWithValue)\s*\(", text)
                or re.search(r"\bvalidation\.(?:Validate|ValidateStruct|ValidateMap)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Invokes Go struct/field validation (go-playground/validator or ozzo-validation).")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
            if (
                re.search(r"\b(?:w\.Write|w\.WriteHeader|json\.NewEncoder\s*\(\s*w\s*\)\.Encode|http\.(?:Error|Redirect|ServeFile|ServeContent))\s*\(", text)
                or re.search(r"\bc\.(?:JSON|String|HTML|XML|File|Redirect|Status|Send|SendString|SendStatus|NoContent|Render|Blob|Attachment|AbortWithStatus(?:JSON)?|IndentedJSON|PureJSON|JSONP)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Writes an HTTP response from Go code.")
            if re.search(r"\bjson\.Marshal(?:Indent)?\s*\(", text):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes structured data in Go.")
            if re.search(r"\bjson\.(?:Unmarshal|NewDecoder)\s*\(", text):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes structured data in Go.")
            if re.search(r"\b[a-z]\w*\.[A-Za-z_]\w*\s*=(?!=)", text):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates a struct field in Go.")
        return refs

    def _extract_rust_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            if (
                re.search(r"\breqwest::\b", text)
                or re.search(r"\bclient\.(?:execute|get|post|put|delete|head|request)\s*\(", text)
                or re.search(r"\bhyper::\b", text)
                or re.search(r"\bsurf::\b", text)
                or re.search(r"\bureq::\b", text)
                or re.search(r"\btonic::\b", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "Calls a Rust HTTP or gRPC client.")
            if re.search(r"\b(?:std::fs::|tokio::fs::|async_std::fs::|File::(?:open|create))\b", text):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno, "Touches the filesystem from Rust code.")
            if re.search(r"\bCommand::new\s*\(", text):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno, "Starts a process from Rust code.")
            if (
                re.search(r"\bstd::env::(?:var|var_os)\s*\(", text)
                or re.search(r"\bdotenv::dotenv\s*\(", text)
                or re.search(r"\benvy::(?:from_env|prefixed)\s*\(", text)
                or re.search(r"\bconfig::Config\b", text)
                or re.search(r"\bfigment::Figment\b", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads environment or configuration state.")
            if re.search(r"\b(?:SystemTime::now|rand::)\b", text) or re.search(r"\buuid::Uuid::new_v\d\b", text):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno, "Uses time or randomness sources.")
            if re.search(r"\.(?:unwrap|expect)\s*\(", text) or re.search(r"\?\s*(?:;|$)", text.rstrip()) or re.search(r"\bErr\s*\(", text):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno, "Contains explicit Rust error handling.")
            if (
                re.search(r"\b(?:diesel::|sqlx::|tokio_postgres::|sea_orm::|rusqlite::)\b", text)
                or re.search(r"\.(?:execute|query|query_as|fetch_one|fetch_all|fetch_optional)\s*\(", text)
                or re.search(r"\bEntityTrait::[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bredis::(?:Client|Connection|Commands|AsyncCommands)\b", text)
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Touches a Rust database client.")
            if re.search(r"\bserde_json::(?:to_string|to_vec|to_writer)\s*\(", text):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes structured data in Rust.")
            if re.search(r"\bserde_json::(?:from_str|from_reader|from_slice|from_value)\s*\(", text):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes structured data in Rust.")
            if re.search(r"\bself\.[A-Za-z_]\w*\s*=(?!=)", text):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates self state in Rust.")
            if (
                re.search(r"#\[(?:get|post|put|delete|patch|head|options)\s*\(", text)
                or re.search(r"\b(?:web::Path|web::Json|web::Query|web::Form|HttpRequest)\b", text)
                or re.search(r"\baxum::extract::\b", text)
                or re.search(r"\bextract::(?:Json|Path|Query|Form|State|TypedHeader)\b", text)
                or re.search(r"\baxum::routing::\b", text)
                or re.search(r"\blapin::\b", text)
                or re.search(r"\brdkafka::consumer::\b", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "Declares a Rust HTTP input boundary.")
            if (
                re.search(r"\bHttpResponse::(?:Ok|Created|BadRequest|Unauthorized|Forbidden|NotFound|InternalServerError)\s*\(", text)
                or re.search(r"\bweb::Json\s*\(", text)
                or re.search(r"\bimpl\s+Responder\b", text)
                or re.search(r"\bimpl\s+IntoResponse\b", text)
                or re.search(r"\baxum::response::", text)
                or re.search(r"\bStatusCode::[A-Z_]{2,}\b", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Produces a Rust HTTP response.")
            if (
                re.search(r"\bbearer_token\b", text)
                or re.search(r"\bjwt::decode\s*::<", text)
                or re.search(r"Authorization.*Bearer\b", text)
                or re.search(r"\bIdentity::(?:identity|remember|forget)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "Enforces authentication in Rust code.")
            if (
                re.search(r"\bValidate::validate\s*\(", text)
                or re.search(r"\bvalidate\.(?:Struct|Var|StructPartial)\s*\(", text)
                or re.search(r"\.validate\s*\(\s*&\s*\(\s*\)\s*\)", text)
                or re.search(r"\bvalidator::validate_\w+\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Invokes Rust struct/field validation (validator/garde crate).")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs

    def _extract_csharp_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            lower = text.lower()
            if re.search(r"\[(?:HttpGet|HttpPost|HttpPut|HttpDelete|HttpPatch|Route|ApiController|FromBody|FromRoute|FromQuery|FromForm|FromHeader)\b", text):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "ASP.NET Core route or parameter attribute marks an input boundary.")
            if (
                re.search(r"\[(?:Authorize|RequireAuthorization)\b", text)
                or re.search(r"\bjwtHandler\.ValidateToken\s*\(", text)
                or re.search(r"\bTokenValidationParameters\b", text)
                or re.search(r"\bClaimsPrincipal\b", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "ASP.NET Core authorization attribute or JWT validation.")
            if (
                re.search(r"\[(?:Required|StringLength|Range|RegularExpression|EmailAddress|MinLength|MaxLength|Phone|Url|Compare)\b", text)
                or re.search(r"\bModelState\.IsValid\b", text)
                or re.search(r"\bValidationContext\b", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Data-annotation attribute or ModelState validation.")
            if (
                re.search(r"\b_?[Cc]ontext\.[A-Za-z_]\w*\.(?:Add|Remove|Update|Find|FindAsync|FirstOrDefault|FirstOrDefaultAsync|ToList|ToListAsync|Where|Any|Count|Single|SingleOrDefault|SaveChanges|SaveChangesAsync)\s*\(", text)
                or re.search(r"\bDbContext\b", text)
                or re.search(r"\bIDbConnection\b", text)
                or re.search(r"\b\.ExecuteNonQuery\s*\(|\b\.ExecuteScalar\s*\(|\b\.ExecuteReader\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Entity Framework or ADO.NET database access.")
            if (
                re.search(r"\b_?[Hh]ttp[Cc]lient\.(?:GetAsync|PostAsync|SendAsync|PutAsync|DeleteAsync|PatchAsync)\s*\(", text)
                or re.search(r"\bnew HttpClient\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "HttpClient network call.")
            if (
                re.search(r"\bFile\.(?:ReadAllText|WriteAllText|ReadAllLines|WriteAllLines|ReadAllBytes|WriteAllBytes|AppendAllText|Open|Create|Delete|Exists|Copy|Move)\s*\(", text)
                or re.search(r"\bDirectory\.[A-Za-z_]\w*\s*\(", text)
                or re.search(r"\bnew (?:FileStream|StreamReader|StreamWriter|BinaryReader|BinaryWriter)\s*\(", text)
                or re.search(r"\bPath\.(?:Combine|GetFullPath|GetFileName|GetDirectoryName)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno, "File system access in C# code.")
            if re.search(r"\bProcess\.Start\s*\(", text):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno, "Process.Start spawns an OS process.")
            if (
                re.search(r"\bEnvironment\.GetEnvironmentVariable\s*\(", text)
                or re.search(r"\bIConfiguration\b", text)
                or re.search(r"\bconfiguration\[", lower)
                or re.search(r"\.GetSection\s*\(|\.GetValue\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads configuration or environment state.")
            if re.search(r"\bJsonSerializer\.(?:Serialize|SerializeAsync)\s*\(|\bJsonConvert\.SerializeObject\s*\(", text):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes data to JSON.")
            if re.search(r"\bJsonSerializer\.(?:Deserialize|DeserializeAsync)\s*\(|\bJsonConvert\.DeserializeObject\s*\(", text):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes data from JSON.")
            if (
                re.search(r"\bDateTime\.(?:Now|UtcNow)\b", text)
                or re.search(r"\bGuid\.NewGuid\s*\(", text)
                or re.search(r"\bnew Random\s*\(|\bRandomNumberGenerator\b", text)
                or re.search(r"\bDateTimeOffset\.(?:Now|UtcNow)\b", text)
            ):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno, "Uses time or randomness sources.")
            if (
                re.search(r"\bthis\.[A-Za-z_]\w*\s*=(?!=)", text)
                or re.search(r"\b_[A-Za-z_]\w*\s*=(?!=)", text)
            ):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Mutates instance state in C#.")
            if re.search(r"\b(?:try|catch|throw)\b", text):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno, "Contains explicit C# error handling.")
            if (
                re.search(r"\breturn\s+(?:Ok|Created|BadRequest|NotFound|Unauthorized|Forbidden|NoContent|Conflict|StatusCode)\s*\(", text)
                or re.search(r"\bIActionResult\b|\bActionResult\b", text)
                or re.search(r"\bContentResult\b|\bJsonResult\b|\bObjectResult\b", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "ASP.NET Core action returns a boundary-facing response.")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs

    def _extract_kotlin_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            if re.search(
                r"@(?:GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|"
                r"RequestMapping|RestController|Controller|KafkaListener|"
                r"RabbitListener|SqsListener|EventListener|JmsListener)\b",
                text,
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno, "HTTP route or message-listener annotation marks an input boundary.")
            if re.search(
                r"@(?:Secured|PreAuthorize|PostAuthorize|RolesAllowed)\b"
                r"|SecurityContextHolder\b"
                r"|\bAuthentication\b",
                text,
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno, "Spring Security annotation or context access.")
            if re.search(
                r"@(?:Valid|Validated|NotNull|NotEmpty|NotBlank|Size|Min|Max|Email|Pattern|"
                r"Positive|Negative|DecimalMin|DecimalMax|AssertTrue|AssertFalse)\b",
                text,
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno, "Bean Validation annotation enforces input constraints.")
            if re.search(
                r"@(?:Query|Insert|Update|Delete|Dao|Entity|Repository)\b"
                r"|\bRoom\.databaseBuilder\s*\("
                r"|\bJdbcTemplate\b"
                r"|\btransaction\s*\{"
                r"|\bDatabase\.connect\s*\(",
                text,
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno, "Database access via Room/JPA/Exposed.")
            if (
                re.search(r"\bHttpClient\s*\(|\bnew HttpClient\b", text)
                or re.search(r"\bOkHttpClient\s*\(", text)
                or re.search(r"\bRetrofit\.Builder\s*\(", text)
                or re.search(r"\b(?:WebClient|RestTemplate)\b", text)
                or re.search(r"client\.(?:get|post|put|delete|patch)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno, "HTTP client network call.")
            if (
                re.search(r"\bFile\s*\(", text)
                or re.search(r"\.readText\s*\(|\.writeText\s*\(|\.readLines\s*\(|\.appendText\s*\(", text)
                or re.search(r"\bPaths\.get\s*\(|\bFiles\.\w+\s*\(", text)
                or re.search(r"\bnew FileInputStream\b|\bnew FileOutputStream\b", text)
            ):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno, "File system access in Kotlin code.")
            if re.search(
                r"\b(?:launch|async|runBlocking|withContext|GlobalScope\.launch|"
                r"CoroutineScope|supervisorScope|coroutineScope)\s*[{\(]",
                text,
            ):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno, "Coroutine builder creates a concurrent execution context.")
            if (
                re.search(r"@(?:Value|ConfigurationProperties)\b", text)
                or re.search(r"\bSystem\.getenv\s*\(", text)
                or re.search(r"\benvironment\.getProperty\s*\(|\benvironment\.getRequiredProperty\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno, "Reads configuration or environment variable.")
            if (
                re.search(r"\bJson\.encodeToString\s*\(", text)
                or re.search(r"\bjacksonObjectMapper\s*\(\)|\.writeValueAsString\s*\(", text)
                or re.search(r"\bGson\s*\(\)\.toJson\s*\(", text)
                or re.search(r"@Serializable\b", text)
            ):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno, "Serializes object to JSON.")
            if (
                re.search(r"\bJson\.decodeFromString\s*\(", text)
                or re.search(r"\.readValue\s*\(", text)
                or re.search(r"\bGson\s*\(\)\.fromJson\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno, "Deserializes object from JSON.")
            if (
                re.search(r"\bSystem\.currentTimeMillis\s*\(|\bSystem\.nanoTime\s*\(", text)
                or re.search(r"\bLocalDateTime\.now\s*\(|\bInstant\.now\s*\(|\bClock\.systemUTC\s*\(", text)
                or re.search(r"\bUUID\.randomUUID\s*\(", text)
                or re.search(r"\bRandom\.nextInt\b|\bRandom\.nextLong\b|\bkotlin\.random\.Random\b", text)
                or re.search(r"@Scheduled\b", text)
            ):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno, "Uses time or randomness sources.")
            if re.search(r"@(?:Cacheable|CacheEvict|CachePut|Caching)\b", text):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno, "Spring cache annotation mutates a shared cache store.")
            if (
                re.search(r"\b(?:try|catch|throw)\b", text)
                or re.search(r"\brun[Cc]atching\s*\{", text)
                or re.search(r"\.onFailure\s*\{|\.getOrThrow\s*\(|\.getOrElse\s*\{", text)
            ):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno, "Contains explicit Kotlin error handling.")
            if (
                re.search(r"\b(?:println|print)\s*\(", text)
                or re.search(r"\blog(?:ger)?\.(?:info|warn|error|debug|trace)\s*\(", text)
                or re.search(r"\bResponseEntity\b|\bcall\.respond\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno, "Produces observable output (log, response).")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs

    def _extract_php_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            if (
                re.search(r"\bRoute::(?:get|post|put|delete|patch|any)\s*\(", text)
                or re.search(r"#\[(?:Route|Get|Post|Put|Delete|Patch)\b", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno,
                                          "Laravel route definition or HTTP attribute marks an input boundary.")
            if (
                re.search(r"\bAuth::(?:check|user|guard|id)\s*\(", text)
                or re.search(r"\bauth\s*\(\s*\)->(?:user|check|id)\s*\(", text)
                or re.search(r"\$request->user\s*\(", text)
                or re.search(r"#\[Authorize\b", text)
                or re.search(r"->middleware\s*\(\s*['\"]auth", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno,
                                          "Laravel Auth guard or authorization middleware.")
            if (
                re.search(r"\$request->validate\s*\(", text)
                or re.search(r"\bValidator::make\s*\(", text)
                or re.search(r"#\[Rule\b", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno,
                                          "Laravel/Symfony validation enforces input constraints.")
            if (
                re.search(r"\bnew\s+PDO\s*\(", text)
                or re.search(r"\$(?:pdo|db)->(?:query|prepare|exec|execute|fetchAll|fetch)\s*\(", text)
                or re.search(r"\bmysqli_\w+\s*\(|\$mysqli->(?:query|prepare|execute)\s*\(", text)
                or re.search(r"\bDB::(?:select|insert|update|delete|table|statement)\s*\(", text)
                or re.search(r"::(?:find|findOrFail|where|create|update|delete|first|all|save)\s*\(", text)
                or re.search(r"->(?:where|select|from|join|orderBy|groupBy|having|get|first|count|save)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno,
                                          "Database access via PDO/MySQLi/Eloquent/Doctrine.")
            if (
                re.search(r"\bcurl_(?:init|exec|setopt)\s*\(", text)
                or re.search(r"\$(?:http)?[Cc]lient->(?:get|post|put|delete|request|send)\s*\(", text)
                or re.search(r"\bHttp::(?:get|post|put|delete|withHeaders|withToken)\s*\(", text)
                or re.search(r"\bfile_get_contents\s*\(\s*['\"]https?://", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno,
                                          "HTTP client or remote file fetch.")
            if (
                re.search(r"\bfile_(?:get_contents|put_contents|exists|delete)\s*\(", text)
                or re.search(r"\b(?:fopen|fclose|fwrite|fread|fgets|fputs)\s*\(", text)
                or re.search(r"\b(?:unlink|mkdir|rmdir|glob|scandir|opendir|readdir)\s*\(", text)
                or re.search(r"\bStorage::(?:put|get|delete|disk|exists|download)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno,
                                          "File system access in PHP code.")
            if re.search(r"\b(?:exec|shell_exec|system|passthru|proc_open|popen)\s*\(", text):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno,
                                          "PHP shell-execution function spawns an OS process.")
            if (
                re.search(r"\bgetenv\s*\(", text)
                or re.search(r"\$_(?:ENV|SERVER)\b", text)
                or re.search(r"\bconfig\s*\(\s*['\"]", text)
                or re.search(r"\benv\s*\(\s*['\"]", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno,
                                          "Reads configuration or environment variable.")
            if re.search(r"\bjson_encode\s*\(|\bserialize\s*\(", text):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno,
                                          "Serializes data to JSON or PHP format.")
            if re.search(r"\bjson_decode\s*\(|\bunserialize\s*\(", text):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno,
                                          "Deserializes data from JSON or PHP format.")
            if (
                re.search(r"\btime\s*\(\s*\)|\bmicrotime\s*\(|\bdate\s*\(|\bstrtotime\s*\(", text)
                or re.search(r"\brand\s*\(|\bmt_rand\s*\(|\brandom_int\s*\(|\brandom_bytes\s*\(", text)
                or re.search(r"\bStr::(?:uuid|random|orderedUuid)\s*\(", text)
                or re.search(r"\bCarbon::(?:now|today|parse)\s*\(", text)
                or re.search(r"\bnew\s+\\\?DateTime\s*\(|\bnew\s+DateTimeImmutable\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno,
                                          "Uses time or randomness sources.")
            if (
                re.search(r"\$_SESSION\b", text)
                or re.search(r"\bCache::(?:put|forget|forever|remember)\s*\(", text)
                or re.search(r"\bcache\s*\(\s*\)->(?:put|forget|remember)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno,
                                          "Mutates session or cache state.")
            if re.search(r"\b(?:try|catch|throw)\b", text):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno,
                                          "Contains explicit PHP error handling.")
            if (
                re.search(r"\becho\b|\bprint\b", text)
                or re.search(r"\bresponse\s*\(\s*\)->json\s*\(", text)
                or re.search(r"\breturn\s+response\s*\(", text)
                or re.search(r"\breturn\s+(?:new\s+)?JsonResponse\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno,
                                          "Produces observable output (echo, response).")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs

    def _extract_ruby_semantic_spans(
        self,
        node: SymbolNode,
        source_lines: List[Tuple[int, str]],
    ) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for index, (lineno, text) in enumerate(source_lines):
            if (
                re.search(r"\b(?:get|post|put|delete|patch|resources?|namespace)\s+['\"/]", text)
                or re.search(r"\bRoutes\.draw\b", text)
            ):
                self._record_semantic_ref(refs, node, "input_boundary", lineno, lineno,
                                          "Rails/Sinatra route definition marks an input boundary.")
            if (
                re.search(r"\bbefore_action\s+:authenticate_user[!?]?", text)
                or re.search(r"\bauthenticate_user[!?]\s*\(", text)
                or re.search(r"\bauthorize[!?]?\s*\(", text)
                or re.search(r"\bcurrent_user\b", text)
                or re.search(r"\buser_signed_in\?\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "auth_guard", lineno, lineno,
                                          "Devise/CanCanCan authentication or authorization check.")
            if (
                re.search(r"\bvalidates\s+:", text)
                or re.search(r"\bvalidate\s+:", text)
                or re.search(r"\bvalid\?\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "validation_guard", lineno, lineno,
                                          "ActiveRecord validation enforces data constraints.")
            if (
                re.search(r"\b(?:ActiveRecord::Base|ApplicationRecord)\b", text)
                or re.search(r"\.(?:where|find|find_by|create|save[!?]?|update[!?]?|destroy[!?]?|first|last|all|count|exists\?)\s*[(\{]", text)
                or re.search(r"\b(?:where|find|find_by|create|save[!?]?|update[!?]?|destroy[!?]?|exists\?)\s*[(\{]", text)
                or re.search(r"\bconnection\.execute\s*\(", text)
                or re.search(r"\bDB\[|Sequel\.connect\b", text)
            ):
                self._record_semantic_ref(refs, node, "database_io", lineno, lineno,
                                          "ActiveRecord or Sequel database access.")
            if (
                re.search(r"\bNet::HTTP\b", text)
                or re.search(r"\bFaraday\.new\b|\bfaraday\b", text)
                or re.search(r"\bHTTParty\.(?:get|post|put|delete)\b", text)
                or re.search(r"\bRestClient\.(?:get|post|put|delete)\b", text)
                or re.search(r"\bopen\s*\(\s*['\"]https?://", text)
                or re.search(r"\bURI\.open\b|\bURI\.parse\b", text)
            ):
                self._record_semantic_ref(refs, node, "network_io", lineno, lineno,
                                          "HTTP client or remote URI access.")
            if (
                re.search(r"\bFile\.(?:read|write|open|exist[s]?|delete|rename|expand_path|join)\s*\(", text)
                or re.search(r"\bDir\.(?:glob|mkdir|entries|foreach)\s*\(", text)
                or re.search(r"\bFileUtils\.\w+\s*\(", text)
                or re.search(r"\bIO\.(?:read|write|popen)\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "filesystem_io", lineno, lineno,
                                          "File system access in Ruby code.")
            if (
                re.search(r"`[^`]+`", text)
                or re.search(r"\b(?:system|exec|spawn)\s*\(", text)
                or re.search(r"\bOpen3\.(?:popen\d?|capture\d|pipeline)\b", text)
                or re.search(r"\bProcess\.spawn\b", text)
            ):
                self._record_semantic_ref(refs, node, "process_io", lineno, lineno,
                                          "Shell command execution in Ruby.")
            if (
                re.search(r"\bENV\s*\[", text)
                or re.search(r"\bRails\.application\.config\b", text)
                or re.search(r"\bRails\.env\b", text)
                or re.search(r"\bRails\.configuration\b", text)
            ):
                self._record_semantic_ref(refs, node, "config_access", lineno, lineno,
                                          "Reads configuration or environment variable.")
            if (
                re.search(r"\.to_json\b", text)
                or re.search(r"\bJSON\.(?:generate|dump)\s*\(", text)
                or re.search(r"\bMarshal\.dump\s*\(", text)
                or re.search(r"\.to_xml\b|\bActiveSupport::JSON\.encode\b", text)
            ):
                self._record_semantic_ref(refs, node, "serialization", lineno, lineno,
                                          "Serializes data to JSON/XML.")
            if (
                re.search(r"\bJSON\.parse\s*\(", text)
                or re.search(r"\bMarshal\.load\s*\(", text)
                or re.search(r"\bActiveSupport::JSON\.decode\b", text)
            ):
                self._record_semantic_ref(refs, node, "deserialization", lineno, lineno,
                                          "Deserializes data from JSON.")
            if (
                re.search(r"\bTime\.(?:now|current|zone\.now)\b", text)
                or re.search(r"\bDateTime\.(?:now|current)\b", text)
                or re.search(r"\bDate\.today\b", text)
                or re.search(r"\bSecureRandom\.(?:uuid|hex|random_bytes)\s*\(", text)
                or re.search(r"\brand\s*\(|\bRandom\.rand\s*\(", text)
            ):
                self._record_semantic_ref(refs, node, "time_or_randomness", lineno, lineno,
                                          "Uses time or randomness sources.")
            if (
                re.search(r"\bRails\.cache\.(?:write|fetch|delete)\s*\(", text)
                or re.search(r"\bsession\s*\[", text)
            ):
                self._record_semantic_ref(refs, node, "state_mutation", lineno, lineno,
                                          "Mutates Rails cache or session state.")
            if re.search(r"\brescue\b|\braise\b", text):
                self._record_semantic_ref(refs, node, "error_handling", lineno, lineno,
                                          "Contains explicit Ruby error handling.")
            if (
                re.search(r"\brender\s+(?:json:|template:|partial:|html:|nothing:)", text)
                or re.search(r"\bredirect_to\s*\(", text)
                or re.search(r"\bputs\s*\(|\bp\s+\w", text)
                or re.search(r"\bRails\.logger\.\w+\b|\blogger\.\w+\b", text)
            ):
                self._record_semantic_ref(refs, node, "output_boundary", lineno, lineno,
                                          "Produces observable output (render, log, puts).")
            guard = self._guard_signal_for_window(source_lines, index)
            if guard is not None:
                signal, end_line, reason = guard
                self._record_semantic_ref(refs, node, signal, lineno, end_line, reason)
        return refs

    def _semantic_summary_for_node(
        self,
        node: SymbolNode,
        signals: List[str],
        refs: List[Dict[str, object]],
    ) -> Dict[str, object]:
        return {
            "signal_count": len(signals),
            "evidence_count": len(refs),
            "top_signal": signals[0] if signals else "",
            "boundary_signals": [signal for signal in signals if signal in SEMANTIC_BOUNDARY_SIGNALS],
            "side_effect_signals": [signal for signal in signals if signal in SEMANTIC_SIDE_EFFECT_SIGNALS],
            "guard_signals": [signal for signal in signals if signal in SEMANTIC_GUARD_SIGNALS],
            "ambiguity_count": len(node.unresolved_call_details),
        }

    def _behavioral_step_sort_key(self, step: Dict[str, object]) -> Tuple[int, int, int, str, str]:
        lines = step.get("lines", [0, 0])
        start = int(lines[0]) if isinstance(lines, list) and lines else 0
        end = int(lines[1]) if isinstance(lines, list) and len(lines) > 1 else start
        step_kind = str(step.get("step_kind", ""))
        return (
            start,
            end,
            BEHAVIORAL_FLOW_STEP_ORDER.get(step_kind, 999),
            step_kind,
            str(step.get("reason", "")),
        )

    def _dedupe_behavioral_flow_steps(
        self,
        steps: List[Dict[str, object]],
        limit: int = 12,
    ) -> List[Dict[str, object]]:
        seen: Set[str] = set()
        out: List[Dict[str, object]] = []
        for step in sorted(steps, key=self._behavioral_step_sort_key):
            key = json.dumps(
                {
                    "step_kind": step.get("step_kind", ""),
                    "file": step.get("file", ""),
                    "lines": step.get("lines", []),
                    "semantic_signal": step.get("semantic_signal", ""),
                    "anchor_symbol": step.get("anchor_symbol", ""),
                },
                sort_keys=True,
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(step)
            if len(out) >= limit:
                break
        return out

    def _compact_behavioral_step_kinds(self, step_kinds: Iterable[str]) -> List[str]:
        ordered: List[str] = []
        for step_kind in step_kinds:
            if not step_kind:
                continue
            if not ordered or ordered[-1] != step_kind:
                ordered.append(step_kind)
        return ordered

    def _build_behavioral_flow_steps(self, node: SymbolNode) -> List[Dict[str, object]]:
        if node.kind not in SEMANTIC_EXECUTABLE_KINDS or not node.semantic_evidence_spans:
            return []
        raw_steps: List[Dict[str, object]] = []
        for ref in node.semantic_evidence_spans:
            signal = str(ref.get("signal", ""))
            if signal not in BEHAVIORAL_FLOW_STEP_SIGNALS:
                continue
            lines = list(ref.get("lines", [node.lines[0], node.lines[0]]))
            start_line = int(lines[0])
            end_line = int(lines[1]) if len(lines) > 1 else start_line
            reason = str(ref.get("reason", ""))
            if (
                signal == "output_boundary"
                and start_line <= int(node.lines[0])
                and "response object" in reason.lower()
            ):
                continue
            raw_steps.append(
                {
                    "step_kind": signal,
                    "file": node.file,
                    "lines": [start_line, end_line],
                    "reason": reason,
                    "semantic_signal": signal,
                    "anchor_symbol": node.node_id,
                    "provenance_kind": "semantic_evidence",
                }
            )
        steps = self._dedupe_behavioral_flow_steps(raw_steps, limit=12)
        earliest_side_effect_line = min(
            (
                int(step["lines"][0])
                for step in steps
                if str(step.get("step_kind", "")) in SEMANTIC_SIDE_EFFECT_SIGNALS
            ),
            default=0,
        )
        if earliest_side_effect_line:
            steps = [
                step
                for step in steps
                if not (
                    str(step.get("step_kind", "")) == "output_boundary"
                    and int(step["lines"][0]) < earliest_side_effect_line
                    and any(
                        other is not step
                        and list(other.get("lines", [])) == list(step.get("lines", []))
                        and str(other.get("step_kind", "")) != "output_boundary"
                        for other in steps
                    )
                )
            ]
        for index, step in enumerate(steps, start=1):
            start_line = int(step["lines"][0])
            end_line = int(step["lines"][1])
            step["order_index"] = index
            step["step_id"] = f"{node.node_id}::flow_step::{index:02d}:{step['step_kind']}:{start_line}-{end_line}"
        return steps

    def _behavioral_flow_summary_for_node(
        self,
        node: SymbolNode,
        steps: List[Dict[str, object]],
    ) -> Dict[str, object]:
        ordered_step_kinds = self._compact_behavioral_step_kinds(str(step.get("step_kind", "")) for step in steps)
        side_effect_steps = [step for step in steps if str(step.get("step_kind", "")) in SEMANTIC_SIDE_EFFECT_SIGNALS]
        guard_steps = [step for step in steps if str(step.get("step_kind", "")) in {"validation_guard", "auth_guard"}]
        boundary_steps = [step for step in steps if str(step.get("step_kind", "")) in SEMANTIC_BOUNDARY_SIGNALS]
        first_boundary = boundary_steps[0] if boundary_steps else None
        first_side_effect = side_effect_steps[0] if side_effect_steps else None
        output_indexes = [index for index, step_kind in enumerate(ordered_step_kinds) if step_kind == "output_boundary"]
        side_effect_indexes = [
            index
            for index, step_kind in enumerate(ordered_step_kinds)
            if step_kind in SEMANTIC_SIDE_EFFECT_SIGNALS
        ]
        has_terminal_output = bool(output_indexes and (not side_effect_indexes or output_indexes[-1] > side_effect_indexes[-1]))
        return {
            "step_count": len(steps),
            "ordered_step_kinds": ordered_step_kinds,
            "boundary_to_side_effect": bool(first_boundary and first_side_effect and int(first_boundary["order_index"]) < int(first_side_effect["order_index"])),
            "first_boundary_step_kind": str(first_boundary.get("step_kind", "")) if first_boundary else "",
            "first_side_effect_step_kind": str(first_side_effect.get("step_kind", "")) if first_side_effect else "",
            "guard_count": len(guard_steps),
            "side_effect_count": len(side_effect_steps),
            "has_terminal_output": has_terminal_output,
            "has_error_path": "error_handling" in ordered_step_kinds,
            "flow_compact_string": " -> ".join(ordered_step_kinds),
        }

    def _extract_behavioral_flows(self) -> None:
        for node in self.nodes.values():
            node.behavioral_flow_steps = []
            node.behavioral_flow_summary = {}
            if node.kind not in SEMANTIC_EXECUTABLE_KINDS:
                continue
            steps = self._build_behavioral_flow_steps(node)
            if not steps:
                continue
            node.behavioral_flow_steps = steps
            node.behavioral_flow_summary = self._behavioral_flow_summary_for_node(node, steps)

    def _node_payload(self, node: SymbolNode) -> Dict[str, object]:
        return {
            "id": node.node_id,
            "language": node.language,
            "kind": node.kind,
            "module": node.module,
            "qualname": node.qualname,
            "file": node.file,
            "lines": node.lines,
            "class_context": node.class_context,
            "package_name": node.package_name,
            "declared_symbols": node.declared_symbols,
            "member_types": {key: node.member_types[key] for key in sorted(node.member_types)},
            "member_qualifiers": {key: node.member_qualifiers[key] for key in sorted(node.member_qualifiers)},
            "annotations": node.annotations,
            "bean_name": node.bean_name,
            "is_abstract": node.is_abstract,
            "di_primary": node.di_primary,
            "coord": node.coord,
            "metrics": {
                "ca": node.ca,
                "ce_internal": node.ce_internal,
                "ce_external": node.ce_external,
                "ce_total": node.ce_total,
                "inheritance_internal": len(node.resolved_bases),
                "inheritance_external": len(node.external_bases),
                "instability": round(node.instability, 4),
                "instability_total": round(node.instability_total, 4),
                "layer": node.layer,
                "pagerank": node.pagerank,
                "betweenness": node.betweenness,
                "git_commit_count": node.git_commit_count,
                "git_churn": node.git_churn,
                "git_hotness": node.git_hotness,
                "scc_id": node.scc_id,
                "scc_size": node.scc_size,
                "recursive_self_call": node.recursive_self_call,
                "resolved_import_count": len(node.resolved_imports),
                "external_import_count": len(node.external_imports),
                "unresolved_import_count": len(node.unresolved_imports),
                "unresolved_call_count": len(node.unresolved_calls),
                "unresolved_base_count": len(node.unresolved_bases),
                "heuristic_candidate_count": len(node.heuristic_candidates),
                "semantic_signal_count": len(node.semantic_signals),
                "contained_semantic_signal_count": len(node.contained_semantic_signals),
                "behavioral_flow_step_count": len(node.behavioral_flow_steps),
            },
            "risk_score": node.risk_score,
            "reasons": node.reasons,
            "semantic_signals": list(node.semantic_signals),
            "semantic_evidence_spans": list(node.semantic_evidence_spans),
            "semantic_summary": dict(node.semantic_summary),
            "semantic_weight": node.semantic_weight,
            "contained_semantic_signals": list(node.contained_semantic_signals),
            "contained_semantic_refs": list(node.contained_semantic_refs),
            "contained_semantic_summary": dict(node.contained_semantic_summary),
            "contained_semantic_weight": node.contained_semantic_weight,
            "behavioral_flow_steps": list(node.behavioral_flow_steps),
            "behavioral_flow_summary": dict(node.behavioral_flow_summary),
            "resolved_imports": sorted(node.resolved_imports),
            "resolved_calls": sorted(node.resolved_calls),
            "resolved_bases": sorted(node.resolved_bases),
            "external_imports": sorted(node.external_imports),
            "external_calls": sorted(node.external_calls),
            "external_bases": sorted(node.external_bases),
            "unresolved_imports": sorted(node.unresolved_imports),
            "unresolved_calls": sorted(node.unresolved_calls),
            "unresolved_call_details": {key: node.unresolved_call_details[key] for key in sorted(node.unresolved_call_details)},
            "unresolved_bases": sorted(node.unresolved_bases),
            "heuristic_candidates": {key: node.heuristic_candidates[key] for key in sorted(node.heuristic_candidates)},
        }

    def _top_risks(self, top_n: int) -> List[Dict[str, object]]:
        ranked = sorted(
            self.nodes.values(),
            key=lambda n: (-n.risk_score, -n.ca, -n.ce_total, n.node_id),
        )
        top: List[Dict[str, object]] = []
        for node in ranked[:top_n]:
            top.append(
                {
                    "symbol": node.node_id,
                    "language": node.language,
                    "kind": node.kind,
                    "risk_score": node.risk_score,
                    "single_point_of_failure": bool(node.ca >= 3 and node.risk_score >= 60.0),
                    "metrics": {
                        "ca": node.ca,
                        "ce_internal": node.ce_internal,
                        "ce_external": node.ce_external,
                        "ce_total": node.ce_total,
                        "inheritance_internal": len(node.resolved_bases),
                        "inheritance_external": len(node.external_bases),
                        "instability": round(node.instability, 4),
                        "instability_total": round(node.instability_total, 4),
                        "layer": node.layer,
                        "pagerank": node.pagerank,
                        "betweenness": node.betweenness,
                        "git_hotness": node.git_hotness,
                        "scc_size": node.scc_size,
                    },
                    "location": {
                        "file": node.file,
                        "lines": node.lines,
                    },
                    "coord": node.coord,
                    "reasons": node.reasons,
                    "semantic_signals": list(node.semantic_signals),
                    "semantic_summary": dict(node.semantic_summary),
                    "semantic_weight": node.semantic_weight,
                    "contained_semantic_signals": list(node.contained_semantic_signals),
                    "contained_semantic_summary": dict(node.contained_semantic_summary),
                    "contained_semantic_weight": node.contained_semantic_weight,
                    "behavioral_flow_summary": dict(node.behavioral_flow_summary),
                    "behavioral_flow_steps": list(node.behavioral_flow_steps[:6]),
                }
            )
        return top

    def _module_report(self) -> List[Dict[str, object]]:
        modules = sorted({n.module for n in self.nodes.values()})
        outgoing: Dict[str, Set[str]] = {m: set() for m in modules}
        incoming: Dict[str, Set[str]] = {m: set() for m in modules}

        for src, dsts in self.adj.items():
            src_mod = self.nodes[src].module
            for dst in dsts:
                dst_mod = self.nodes[dst].module
                if src_mod == dst_mod:
                    continue
                outgoing[src_mod].add(dst_mod)
                incoming[dst_mod].add(src_mod)

        out: List[Dict[str, object]] = []
        max_ca = max((len(incoming[m]) for m in modules), default=1) or 1
        for mod in modules:
            ca = len(incoming[mod])
            ce = len(outgoing[mod])
            total = ca + ce
            instability = round(ce / total, 4) if total else 0.0
            risk = round((0.6 * instability + 0.4 * (ca / max_ca)) * 100.0, 2)
            out.append(
                {
                    "module": mod,
                    "metrics": {"ca": ca, "ce": ce, "instability": instability},
                    "risk_score": risk,
                }
            )
        return sorted(out, key=lambda x: (-x["risk_score"], x["module"]))

    def _build_project_inventory(self) -> Dict[str, object]:
        extension_counts: Dict[str, int] = defaultdict(int)
        candidate_files: List[str] = []
        key_files = {
            "pyproject.toml",
            "requirements.txt",
            "requirements-dev.txt",
            "setup.py",
            "setup.cfg",
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "yarn.lock",
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            ".env",
            ".env.example",
            "README.md",
            "Makefile",
            "go.mod",
            "Cargo.toml",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
        }
        total_file_count = 0
        project_files = self._iter_project_files()

        for rel_path in project_files:
            file_name = os.path.basename(rel_path)
            total_file_count += 1
            suffix = Path(file_name).suffix.lower() or "<no_ext>"
            extension_counts[suffix] += 1
            if file_name in key_files and rel_path not in candidate_files:
                candidate_files.append(rel_path)

        top_extensions = sorted(
            (
                {"extension": ext, "count": count}
                for ext, count in extension_counts.items()
            ),
            key=lambda item: (-item["count"], item["extension"]),
        )[:12]

        top_modules = sorted(
            (
                {"module": item["module"], "risk_score": item["risk_score"]}
                for item in self._module_report()[:8]
            ),
            key=lambda item: (-item["risk_score"], item["module"]),
        )
        language_summary, source_file_insights = self._build_source_file_insights(project_files)
        top_source_files = source_file_insights[:12]

        technologies, manifest_summary = self._detect_project_technologies(project_files, sorted(candidate_files))
        entrypoints = self._detect_project_entrypoints(project_files)
        docs = self._detect_documentation_files(project_files)

        return {
            "total_file_count": total_file_count,
            "graph_node_count": len(self.nodes),
            "python_symbol_count": sum(1 for node in self.nodes.values() if node.language == "Python"),
            "top_extensions": top_extensions,
            "key_files": sorted(candidate_files),
            "likely_technologies": technologies,
            "language_summary": language_summary,
            "entrypoints": entrypoints,
            "documentation_files": docs,
            "manifest_summary": manifest_summary,
            "source_file_insights": source_file_insights,
            "top_source_files": top_source_files,
            "top_modules": top_modules,
        }

    def _detect_project_technologies(
        self,
        project_files: List[str],
        key_files: List[str],
    ) -> Tuple[List[str], Dict[str, object]]:
        technologies: Set[str] = set()
        manifest_summary: Dict[str, object] = {}

        if any(node.language == "Python" for node in self.nodes.values()):
            technologies.add("Python")

        package_json_path = os.path.join(self.root_dir, "package.json")
        if os.path.exists(package_json_path):
            try:
                with open(package_json_path, "r", encoding="utf-8") as handle:
                    package_data = json.load(handle)
                deps = {}
                deps.update(package_data.get("dependencies", {}))
                deps.update(package_data.get("devDependencies", {}))
                dep_names = sorted(deps)
                technologies.add("Node.js")
                if "react" in deps:
                    technologies.add("React")
                if "next" in deps:
                    technologies.add("Next.js")
                if "vite" in deps:
                    technologies.add("Vite")
                if "express" in deps:
                    technologies.add("Express")
                if "@nestjs/core" in deps:
                    technologies.add("NestJS")
                if "vue" in deps:
                    technologies.add("Vue")
                if "nuxt" in deps:
                    technologies.add("Nuxt")
                if "svelte" in deps:
                    technologies.add("Svelte")
                manifest_summary["package_json"] = {
                    "name": package_data.get("name", ""),
                    "scripts": sorted(package_data.get("scripts", {}).keys())[:10],
                    "dependencies": dep_names[:20],
                }
            except (OSError, json.JSONDecodeError):
                manifest_summary["package_json"] = {"error": "Could not parse package.json"}

        if self.js_resolver_configs:
            manifest_summary["js_resolver_configs"] = [
                {
                    "file": str(config.get("config_file", "")),
                    "base_dir": Path(
                        os.path.relpath(str(config.get("base_dir", self.root_dir)), self.root_dir)
                    ).as_posix(),
                    "aliases": sorted(dict(config.get("paths", {})).keys()),
                }
                for config in self.js_resolver_configs[:10]
            ]

        pyproject_path = os.path.join(self.root_dir, "pyproject.toml")
        if tomllib is not None and os.path.exists(pyproject_path):
            try:
                with open(pyproject_path, "rb") as handle:
                    pyproject_data = tomllib.load(handle)
                project_section = pyproject_data.get("project", {})
                poetry_section = pyproject_data.get("tool", {}).get("poetry", {})
                deps = project_section.get("dependencies", [])
                poetry_deps = sorted(k for k in poetry_section.get("dependencies", {}).keys() if k != "python")
                flattened_deps = [str(item) for item in deps] + poetry_deps
                dep_blob = " ".join(flattened_deps).lower()
                if "fastapi" in dep_blob:
                    technologies.add("FastAPI")
                if "flask" in dep_blob:
                    technologies.add("Flask")
                if "django" in dep_blob:
                    technologies.add("Django")
                if "pytest" in dep_blob:
                    technologies.add("pytest")
                manifest_summary["pyproject"] = {
                    "name": project_section.get("name") or poetry_section.get("name", ""),
                    "dependencies": flattened_deps[:20],
                }
            except (OSError, ValueError, TypeError):
                manifest_summary["pyproject"] = {"error": "Could not parse pyproject.toml"}

        requirements_files = [
            rel_path
            for rel_path in key_files
            if os.path.basename(rel_path) in {"requirements.txt", "requirements-dev.txt"}
        ]
        if requirements_files:
            reqs: List[str] = []
            for rel_path in requirements_files:
                try:
                    with open(os.path.join(self.root_dir, rel_path), "r", encoding="utf-8") as handle:
                        for raw_line in handle:
                            line = raw_line.strip()
                            if not line or line.startswith("#"):
                                continue
                            reqs.append(re.split(r"[<>=!~]", line, maxsplit=1)[0].strip())
                except OSError:
                    continue
            req_blob = " ".join(reqs).lower()
            if "fastapi" in req_blob:
                technologies.add("FastAPI")
            if "flask" in req_blob:
                technologies.add("Flask")
            if "django" in req_blob:
                technologies.add("Django")
            if "pytest" in req_blob:
                technologies.add("pytest")
            manifest_summary["requirements"] = sorted(set(reqs))[:20]

        if os.path.exists(os.path.join(self.root_dir, "Dockerfile")):
            technologies.add("Docker")

        go_mod_path = os.path.join(self.root_dir, "go.mod")
        if os.path.exists(go_mod_path):
            technologies.add("Go")
            try:
                with open(go_mod_path, "r", encoding="utf-8") as handle:
                    content = handle.read()
                module_match = re.search(r"(?m)^\s*module\s+(.+?)\s*$", content)
                deps = []
                for line in content.splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith("//"):
                        continue
                    stripped = re.sub(r"^require\s+", "", stripped)
                    stripped = stripped.strip("() ").strip()
                    match = re.match(r"^([A-Za-z0-9./_-]+)\s+v[0-9][^\s]*$", stripped)
                    if match:
                        deps.append(match.group(1))
                dep_blob = " ".join(deps).lower()
                if "gin-gonic" in dep_blob:
                    technologies.add("Gin")
                if "spf13/cobra" in dep_blob:
                    technologies.add("Cobra")
                manifest_summary["go_mod"] = {
                    "module": module_match.group(1).strip() if module_match else "",
                    "dependencies": deps[:20],
                }
            except OSError:
                manifest_summary["go_mod"] = {"error": "Could not parse go.mod"}

        cargo_path = os.path.join(self.root_dir, "Cargo.toml")
        if tomllib is not None and os.path.exists(cargo_path):
            technologies.add("Rust")
            try:
                with open(cargo_path, "rb") as handle:
                    cargo_data = tomllib.load(handle)
                deps = sorted(cargo_data.get("dependencies", {}).keys())
                dep_blob = " ".join(deps).lower()
                if "tokio" in dep_blob:
                    technologies.add("Tokio")
                if "actix-web" in dep_blob:
                    technologies.add("Actix Web")
                if "axum" in dep_blob:
                    technologies.add("Axum")
                manifest_summary["cargo_toml"] = {
                    "package": cargo_data.get("package", {}).get("name", ""),
                    "dependencies": deps[:20],
                }
            except (OSError, ValueError, TypeError):
                manifest_summary["cargo_toml"] = {"error": "Could not parse Cargo.toml"}

        pom_path = os.path.join(self.root_dir, "pom.xml")
        if os.path.exists(pom_path):
            technologies.add("Java")
            try:
                tree = ElementTree.parse(pom_path)
                root = tree.getroot()
                artifact = self._xml_find_text(root, "artifactId")
                deps = self._xml_find_all_text(root, "artifactId")
                dep_blob = " ".join(deps).lower()
                if "spring-boot" in dep_blob:
                    technologies.add("Spring Boot")
                if "junit" in dep_blob:
                    technologies.add("JUnit")
                manifest_summary["pom_xml"] = {
                    "artifact_id": artifact,
                    "artifacts": deps[:20],
                }
            except (OSError, ElementTree.ParseError):
                manifest_summary["pom_xml"] = {"error": "Could not parse pom.xml"}

        for rel_path in project_files:
            suffix = Path(rel_path).suffix.lower()
            if suffix in {".ts", ".tsx"}:
                technologies.add("TypeScript")
            if suffix in {".js", ".jsx"}:
                technologies.add("JavaScript")
            if suffix == ".tsx":
                technologies.add("React")
            if suffix == ".go":
                technologies.add("Go")
            if suffix == ".java":
                technologies.add("Java")
            if suffix == ".rs":
                technologies.add("Rust")

        return sorted(technologies), manifest_summary

    def _detect_project_entrypoints(self, project_files: List[str]) -> List[Dict[str, str]]:
        candidates = {
            "main.py": "Common Python entrypoint",
            "app.py": "Common Python application bootstrap",
            "manage.py": "Typical Django entrypoint",
            "wsgi.py": "WSGI application entrypoint",
            "asgi.py": "ASGI application entrypoint",
            "cli.py": "CLI-style Python entrypoint",
            "__main__.py": "Python package entrypoint",
            "package.json": "Node.js manifest with runnable scripts",
            "src/main.ts": "Common frontend bootstrap",
            "src/main.tsx": "Common React bootstrap",
            "src/index.ts": "Common TypeScript bootstrap",
            "src/index.tsx": "Common React bootstrap",
            "src/index.js": "Common JavaScript bootstrap",
            "server.js": "Common Node server entrypoint",
            "server.ts": "Common TypeScript server entrypoint",
            "main.go": "Common Go entrypoint",
            "src/main.rs": "Common Rust binary entrypoint",
            "src/lib.rs": "Common Rust library root",
            "go.mod": "Go module manifest",
            "Cargo.toml": "Rust package manifest",
            "pom.xml": "Java/Maven project manifest",
        }
        out: List[Dict[str, str]] = []
        seen = set()
        for rel_path in project_files:
            normalized = rel_path.replace("\\", "/")
            for candidate, reason in candidates.items():
                if normalized == candidate and normalized not in seen:
                    out.append({"file": rel_path, "reason": reason})
                    seen.add(normalized)
            if re.fullmatch(r"cmd/[^/]+/main\.go", normalized) and normalized not in seen:
                out.append({"file": rel_path, "reason": "Go command entrypoint under cmd/."})
                seen.add(normalized)
            if normalized.endswith("Application.java") and normalized not in seen:
                out.append({"file": rel_path, "reason": "Likely Java application bootstrap."})
                seen.add(normalized)
        return sorted(out, key=lambda item: item["file"])

    def _detect_documentation_files(self, project_files: List[str]) -> List[str]:
        docs: List[str] = []
        for rel_path in project_files:
            normalized = rel_path.replace("\\", "/").lower()
            if normalized in {"readme.md", "readme.txt"}:
                docs.append(rel_path)
            elif normalized.startswith("docs/") and normalized.endswith((".md", ".txt", ".rst")):
                docs.append(rel_path)
        return sorted(docs)[:12]

    def _build_source_file_insights(
        self,
        project_files: List[str],
    ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
        python_nodes_by_file: Dict[str, List[SymbolNode]] = defaultdict(list)
        for node in self.nodes.values():
            python_nodes_by_file[node.file].append(node)

        insights: List[Dict[str, object]] = []
        lang_agg: Dict[str, Dict[str, float]] = defaultdict(lambda: {"file_count": 0, "symbol_count": 0, "entrypoints": 0})
        for rel_path in project_files:
            language = LANGUAGE_BY_SUFFIX.get(Path(rel_path).suffix.lower())
            if not language:
                continue
            insight = self._analyze_source_file(rel_path, language, python_nodes_by_file.get(rel_path, []))
            if not insight:
                continue
            insights.append(insight)
            lang_agg[language]["file_count"] += 1
            lang_agg[language]["symbol_count"] += int(insight["symbol_count"])
            if insight["entrypoint_reason"]:
                lang_agg[language]["entrypoints"] += 1

        insights.sort(
            key=lambda item: (
                -int(bool(item["entrypoint_reason"])),
                -float(item["semantic_score"]),
                item["file"],
            )
        )
        language_summary = [
            {
                "language": language,
                "file_count": int(data["file_count"]),
                "symbol_count": int(data["symbol_count"]),
                "entrypoint_count": int(data["entrypoints"]),
            }
            for language, data in sorted(lang_agg.items(), key=lambda item: (-item[1]["file_count"], item[0]))
        ]
        return language_summary, insights[:20]

    def _analyze_source_file(
        self,
        rel_path: str,
        language: str,
        python_nodes: List[SymbolNode],
    ) -> Optional[Dict[str, object]]:
        content = self._read_project_text(rel_path)
        if content is None:
            return None

        if language == "Python":
            return self._analyze_python_source(rel_path, content, python_nodes)
        if language in {"JavaScript", "TypeScript"}:
            return self._analyze_js_like_source(rel_path, content, language)
        if language == "Go":
            return self._analyze_go_source(rel_path, content)
        if language == "Java":
            return self._analyze_java_source(rel_path, content)
        if language == "Rust":
            return self._analyze_rust_source(rel_path, content)
        return None

    def _analyze_python_source(
        self,
        rel_path: str,
        content: str,
        python_nodes: List[SymbolNode],
    ) -> Dict[str, object]:
        classes = sum(1 for node in python_nodes if node.kind == "class")
        functions = sum(1 for node in python_nodes if node.kind != "class")
        symbols = sorted(node.qualname for node in python_nodes)[:8]
        import_count = len(re.findall(r"(?m)^\s*(?:from|import)\s+", content))
        entrypoint_reason = ""
        if "__name__" in content and "__main__" in content:
            entrypoint_reason = "Contains a Python main guard."
        elif os.path.basename(rel_path) in {"main.py", "app.py", "manage.py"}:
            entrypoint_reason = "Filename suggests a Python entrypoint."
        summary = f"{len(python_nodes)} symbols, {classes} classes, {functions} functions."
        semantic_score = float(len(python_nodes) + import_count + (4 if entrypoint_reason else 0))
        return self._source_insight(
            rel_path,
            "Python",
            len(python_nodes),
            import_count,
            0,
            entrypoint_reason,
            semantic_score,
            symbols,
            summary,
        )

    def _analyze_js_like_source(self, rel_path: str, content: str, language: str) -> Dict[str, object]:
        function_names = re.findall(r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)\s*\(", content)
        class_names = re.findall(r"(?m)^\s*(?:export\s+)?class\s+([A-Za-z_]\w*)\b", content)
        arrow_names = re.findall(
            r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_]\w*)\s*=>",
            content,
        )
        type_names = re.findall(r"(?m)^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_]\w*)\b", content)
        imports = len(re.findall(r"(?m)^\s*import\s+", content)) + len(re.findall(r"\brequire\s*\(", content))
        exports = len(re.findall(r"(?m)^\s*export\s+", content)) + len(re.findall(r"\bmodule\.exports\b", content))
        symbols = self._dedupe(function_names + class_names + arrow_names + type_names)[:10]

        entrypoint_reason = ""
        normalized = rel_path.replace("\\", "/")
        if normalized in {"src/main.ts", "src/main.tsx", "src/index.ts", "src/index.tsx", "src/index.js", "server.js", "server.ts"}:
            entrypoint_reason = "Common frontend or server bootstrap file."
        elif re.search(r"\b(app|server)\.listen\s*\(", content):
            entrypoint_reason = "Starts an HTTP listener."
        elif re.search(r"\bcreateRoot\s*\(", content) or "ReactDOM.render" in content:
            entrypoint_reason = "Bootstraps a React application."

        tags: List[str] = []
        if language == "TypeScript":
            tags.append("typed")
        if Path(rel_path).suffix.lower() in {".jsx", ".tsx"}:
            tags.append("react-ish")
        summary = f"{len(symbols)} named symbols, {imports} imports, {exports} exports."
        semantic_score = float(len(symbols) + imports + exports + (4 if entrypoint_reason else 0))
        return self._source_insight(
            rel_path,
            language,
            len(symbols),
            imports,
            exports,
            entrypoint_reason,
            semantic_score,
            symbols,
            summary,
            tags,
        )

    def _analyze_go_source(self, rel_path: str, content: str) -> Dict[str, object]:
        funcs = re.findall(r"(?m)^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z_]\w*)\s*\(", content)
        types = re.findall(r"(?m)^\s*type\s+([A-Za-z_]\w*)\s+(?:struct|interface|map|chan|func|\[\])", content)
        imports = len(re.findall(r"(?m)^\s*import\s+", content))
        symbols = self._dedupe(funcs + types)[:10]
        entrypoint_reason = ""
        if os.path.basename(rel_path) == "main.go" and re.search(r"(?m)^\s*package\s+main\s*$", content):
            entrypoint_reason = "Go main package entrypoint."
        elif re.search(r"(?m)^\s*func\s+main\s*\(", content):
            entrypoint_reason = "Contains func main()."
        summary = f"{len(symbols)} named declarations, {imports} import sections."
        semantic_score = float(len(symbols) + imports + (4 if entrypoint_reason else 0))
        return self._source_insight(rel_path, "Go", len(symbols), imports, 0, entrypoint_reason, semantic_score, symbols, summary)

    def _analyze_java_source(self, rel_path: str, content: str) -> Dict[str, object]:
        types = re.findall(r"(?m)^\s*(?:public\s+)?(?:class|interface|enum|record)\s+([A-Za-z_]\w*)\b", content)
        methods = [
            name
            for name in re.findall(
                r"(?m)^\s*(?:public|protected|private)?\s*(?:static\s+)?[A-Za-z0-9_<>\[\], ?]+\s+([A-Za-z_]\w*)\s*\(",
                content,
            )
            if name not in {"if", "for", "while", "switch", "catch", "return", "new"}
        ]
        imports = len(re.findall(r"(?m)^\s*import\s+", content))
        symbols = self._dedupe(types + methods)[:10]
        entrypoint_reason = ""
        if "public static void main" in content:
            entrypoint_reason = "Contains a Java main method."
        elif "@SpringBootApplication" in content:
            entrypoint_reason = "Likely Spring Boot application bootstrap."
        summary = f"{len(symbols)} named declarations, {imports} imports."
        semantic_score = float(len(symbols) + imports + (4 if entrypoint_reason else 0))
        tags = ["spring"] if "@SpringBootApplication" in content or "@RestController" in content else []
        return self._source_insight(rel_path, "Java", len(symbols), imports, 0, entrypoint_reason, semantic_score, symbols, summary, tags)

    def _analyze_rust_source(self, rel_path: str, content: str) -> Dict[str, object]:
        funcs = re.findall(r"(?m)^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)\s*\(", content)
        types = re.findall(r"(?m)^\s*(?:pub\s+)?(?:struct|enum|trait|mod)\s+([A-Za-z_]\w*)\b", content)
        imports = len(re.findall(r"(?m)^\s*use\s+", content))
        symbols = self._dedupe(funcs + types)[:10]
        entrypoint_reason = ""
        if re.search(r"(?m)^\s*fn\s+main\s*\(", content):
            entrypoint_reason = "Rust binary entrypoint."
        elif rel_path.replace("\\", "/") == "src/lib.rs":
            entrypoint_reason = "Rust library root."
        summary = f"{len(symbols)} named declarations, {imports} use statements."
        semantic_score = float(len(symbols) + imports + (4 if entrypoint_reason else 0))
        return self._source_insight(rel_path, "Rust", len(symbols), imports, 0, entrypoint_reason, semantic_score, symbols, summary)

    def _source_insight(
        self,
        rel_path: str,
        language: str,
        symbol_count: int,
        import_count: int,
        export_count: int,
        entrypoint_reason: str,
        semantic_score: float,
        symbols: List[str],
        summary: str,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, object]:
        line_count = len((self._read_project_text(rel_path) or "").splitlines())
        return {
            "file": rel_path,
            "language": language,
            "symbol_count": symbol_count,
            "import_count": import_count,
            "export_count": export_count,
            "line_count": line_count,
            "entrypoint_reason": entrypoint_reason,
            "semantic_score": round(semantic_score, 2),
            "top_symbols": symbols,
            "summary": summary,
            "tags": tags or [],
        }

    def _read_project_text(self, rel_path: str) -> Optional[str]:
        if rel_path in self.project_text_cache:
            return self.project_text_cache[rel_path]
        full_path = os.path.join(self.root_dir, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except (OSError, UnicodeDecodeError):
            content = None
        self.project_text_cache[rel_path] = content
        return content

    def _read_project_lines(self, rel_path: str) -> List[str]:
        if rel_path not in self.project_lines_cache:
            content = self._read_project_text(rel_path)
            self.project_lines_cache[rel_path] = content.splitlines() if content is not None else []
        return self.project_lines_cache[rel_path]

    def _xml_find_text(self, root: ElementTree.Element, local_name: str) -> str:
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == local_name and element.text:
                return element.text.strip()
        return ""

    def _xml_find_all_text(self, root: ElementTree.Element, local_name: str) -> List[str]:
        out: List[str] = []
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == local_name and element.text:
                out.append(element.text.strip())
        return out

    def _dedupe(self, values: List[str]) -> List[str]:
        seen: Set[str] = set()
        out: List[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    def _iter_project_files(self) -> List[str]:
        files: List[str] = []
        for root, dirs, file_names in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if not should_ignore_dir(d)]
            for file_name in file_names:
                files.append(os.path.relpath(os.path.join(root, file_name), self.root_dir))
        return sorted(files)

    def _build_llm_context_slices(
        self,
        evidence_candidates: List[Dict[str, object]],
        inbound: Dict[str, List],
        path_refs_by_anchor: Dict[str, List],
        path_bonus_by_anchor: Dict[str, float],
        ambiguity_watchlist: List[Dict[str, object]],
        line_budget: int,
        primary_budget: int,
    ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
        slice_specs: List[Dict[str, object]] = []
        deferred: List[Dict[str, object]] = []
        focus_symbols: List[Dict[str, object]] = []
        used_lines = 0
        selected_nodes: Set[str] = set()

        for candidate in evidence_candidates:
            node_id = str(candidate["node_id"])
            node = self.nodes[node_id]
            primary_slice = self._annotate_slice_path_refs(dict(candidate["suggested_slices"][0]), path_refs_by_anchor)
            line_count = int(primary_slice["end_line"]) - int(primary_slice["start_line"]) + 1
            must_include = len(selected_nodes) < min(3, len(evidence_candidates))

            selected_for_context = False
            if must_include or used_lines + line_count <= primary_budget:
                slice_specs.append(primary_slice)
                used_lines += line_count
                selected_nodes.add(node_id)
                selected_for_context = True
            else:
                deferred.append(
                    self._build_deferred_request_for_symbol(
                        node_id,
                        "This risk node was deferred because the initial slice budget was exhausted.",
                    )
                )

            focus_symbols.append(
                {
                    "rank": candidate["rank"],
                    "symbol": node_id,
                    "risk_score": candidate["risk_score"],
                    "bundle_priority": candidate["bundle_priority"],
                    "file": node.file,
                    "lines": node.lines,
                    "why": list(candidate["why_selected"]),
                    "dependencies": self._rank_neighbors(self.adj.get(node_id, set())),
                    "dependents": self._rank_neighbors(inbound.get(node_id, set())),
                    "supporting_edge_confidence": candidate["supporting_edge_confidence"],
                    "ambiguity_count": len(candidate["ambiguity_flags"]),
                    "semantic_signals": list(node.semantic_signals),
                    "semantic_summary": dict(node.semantic_summary),
                    "semantic_weight": node.semantic_weight,
                    "contained_semantic_signals": list(node.contained_semantic_signals),
                    "contained_semantic_summary": dict(node.contained_semantic_summary),
                    "contained_semantic_weight": node.contained_semantic_weight,
                    "selected_for_context": selected_for_context,
                }
            )
            deferred.extend(list(candidate["deferred_if_needed"]))

        support_pool: List[Dict[str, object]] = []
        for candidate in evidence_candidates:
            if str(candidate["node_id"]) not in selected_nodes:
                continue
            support_pool.extend(
                self._annotate_slice_path_refs(dict(spec), path_refs_by_anchor)
                for spec in candidate["suggested_slices"][1:]
            )

        for item in ambiguity_watchlist[:4]:
            deferred.append(self._build_deferred_request_for_ambiguity(item))

        support_pool.sort(
            key=lambda spec: (
                -(float(spec.get("selection_score", 0.0)) + max(path_bonus_by_anchor.get(str(symbol), 0.0) for symbol in spec.get("symbols", []) or [""])),
                str(spec.get("selection_confidence_label", "")),
                str(spec.get("file", "")),
                int(spec.get("start_line", 0)),
            )
        )

        for spec in support_pool:
            line_count = int(spec["end_line"]) - int(spec["start_line"]) + 1
            if used_lines + line_count > line_budget:
                continue
            slice_specs.append(spec)
            used_lines += line_count

        return slice_specs, deferred, focus_symbols

    def _build_llm_context_pack(self, top_risks: List[Dict[str, object]], line_budget: int) -> Dict[str, object]:
        inbound = self._inbound_adj()
        confidence_summary = self._build_confidence_summary()
        ambiguity_watchlist = self._build_ambiguity_watchlist()
        evidence_candidates = self._build_evidence_candidates(top_risks, inbound)
        semantic_candidates = self._build_semantic_candidates(limit=10)
        semantic_watchlist = self._build_semantic_watchlist(limit=6)
        evidence_paths = self._build_evidence_paths(evidence_candidates, inbound)[:12]
        path_refs_by_anchor = self._path_refs_by_anchor(evidence_paths)
        path_bonus_by_anchor: Dict[str, float] = defaultdict(float)
        for path in evidence_paths:
            bonus = (float(path.get("path_confidence", 0.0)) * 10.0) + float(len(path.get("hops", [])))
            for item in path.get("recommended_slices", [])[1:]:
                anchor_symbol = str(item.get("anchor_symbol", ""))
                if anchor_symbol:
                    path_bonus_by_anchor[anchor_symbol] = max(path_bonus_by_anchor[anchor_symbol], bonus)
        primary_budget = max(1, int(line_budget * 0.72))
        slice_specs, deferred, focus_symbols = self._build_llm_context_slices(
            evidence_candidates,
            inbound,
            path_refs_by_anchor,
            path_bonus_by_anchor,
            ambiguity_watchlist,
            line_budget,
            primary_budget,
        )

        merged_slices = self._merge_slice_specs(slice_specs)
        merged_slices = [
            self._annotate_slice_path_refs(spec, path_refs_by_anchor)
            for spec in merged_slices
        ]
        selected_symbols = {symbol for spec in merged_slices for symbol in spec["symbols"]}
        best_paths_by_risk_node = self._best_paths_by_risk_node(evidence_paths)
        for risk_node in sorted(best_paths_by_risk_node):
            if risk_node not in selected_symbols:
                continue
            path = best_paths_by_risk_node[risk_node]
            request = self._build_deferred_request_for_path(path, selected_symbols)
            if request is not None:
                deferred.append(request)
        for item in semantic_watchlist[:3]:
            request = self._build_deferred_request_for_semantic_item(item, merged_slices)
            if request is not None:
                deferred.append(request)
        support_chains = [
            candidate["support_chain"]
            for candidate in evidence_candidates
            if str(candidate["node_id"]) in selected_symbols
        ][:8]
        deferred = self._dedupe_object_list(deferred)
        return {
            "strategy": (
                "Read the selected slices first, prefer high-confidence support chains, keep ambiguity compact, "
                "then use short evidence_paths plus semantic signals to justify claims. Request only the smallest "
                "missing structural or semantic follow-up slice when the current evidence is insufficient."
            ),
            "budget": {
                "line_budget": max(1, line_budget),
                "selected_line_count": sum(spec["end_line"] - spec["start_line"] + 1 for spec in merged_slices),
                "selected_symbol_count": len(selected_symbols),
                "deferred_symbol_count": len(deferred),
            },
            "confidence_summary": confidence_summary,
            "focus_symbols": focus_symbols,
            "evidence_candidates": evidence_candidates[:10],
            "semantic_candidates": semantic_candidates,
            "support_chains": support_chains,
            "evidence_paths": evidence_paths,
            "ambiguity_watchlist": ambiguity_watchlist,
            "semantic_watchlist": semantic_watchlist,
            "context_slices": merged_slices,
            "deferred_requests": deferred,
            "audit_prompt": self._build_audit_prompt(),
        }

    def _build_project_context_pack(self, inventory: Dict[str, object]) -> Dict[str, object]:
        recommended_reads: List[Dict[str, str]] = []
        for item in inventory["entrypoints"][:6]:
            recommended_reads.append({"file": item["file"], "why": item["reason"]})
        for rel_path in inventory["documentation_files"][:4]:
            if all(entry["file"] != rel_path for entry in recommended_reads):
                recommended_reads.append({"file": rel_path, "why": "Project documentation or onboarding context."})
        for rel_path in inventory["key_files"][:6]:
            if all(entry["file"] != rel_path for entry in recommended_reads):
                recommended_reads.append({"file": rel_path, "why": "Key manifest or configuration file."})
        for item in inventory["top_source_files"][:4]:
            if all(entry["file"] != item["file"] for entry in recommended_reads):
                recommended_reads.append(
                    {
                        "file": item["file"],
                        "why": (
                            f"Representative {item['language']} source file with {item['symbol_count']} discovered "
                            f"symbols. {item['summary']}"
                        ),
                    }
                )
        for item in self._build_semantic_entrypoints(limit=4):
            if all(entry["file"] != item["file"] for entry in recommended_reads):
                recommended_reads.append(
                    {
                        "file": item["file"],
                        "why": (
                            f"Semantic entrypoint with {', '.join(item['semantic_signals'][:3])} evidence."
                        ),
                    }
                )

        inbound = self._inbound_adj()
        confidence_summary = self._build_confidence_summary()
        ambiguity_watchlist = self._build_ambiguity_watchlist(limit=6)
        semantic_overview = self._build_semantic_overview(limit=8)
        semantic_entrypoints = self._build_semantic_entrypoints(limit=8)
        architecture_evidence = self._build_project_architecture_evidence(recommended_reads, limit=8)
        architecture_evidence_paths = self._build_project_architecture_paths(recommended_reads, inbound, limit=6)
        project_file_slices = self._build_project_file_slices(recommended_reads, architecture_evidence_paths)
        return {
            "strategy": (
                "Understand the project shell first: read stack clues, entrypoints, and key manifests before "
                "descending into implementation details. Use the architecture_evidence, architecture_evidence_paths, "
                "ambiguity_watchlist, direct semantic_entrypoints, and the contained file-level semantic_overview to "
                "decide where confidence is high enough to trust the summary versus where targeted evidence is still needed."
            ),
            "likely_technologies": inventory["likely_technologies"],
            "confidence_summary": confidence_summary,
            "semantic_overview": semantic_overview,
            "semantic_entrypoints": semantic_entrypoints,
            "recommended_reads": recommended_reads[:10],
            "architecture_evidence": architecture_evidence,
            "architecture_evidence_paths": architecture_evidence_paths,
            "ambiguity_watchlist": ambiguity_watchlist,
            "file_slices": project_file_slices,
            "project_prompt": self._build_project_prompt(inventory, recommended_reads[:10]),
        }

    def _build_project_file_slices(
        self,
        reads: List[Dict[str, str]],
        architecture_evidence_paths: Optional[List[Dict[str, object]]] = None,
        max_chars: int = 2200,
    ) -> List[Dict[str, object]]:
        path_refs_by_file: Dict[str, Set[str]] = defaultdict(set)
        for path in architecture_evidence_paths or []:
            path_id = str(path.get("path_id", ""))
            for item in path.get("recommended_slices", []):
                file_name = str(item.get("file", ""))
                if file_name and path_id:
                    path_refs_by_file[file_name].add(path_id)
        slices: List[Dict[str, object]] = []
        for item in reads[:10]:
            rel_path = item["file"]
            full_path = os.path.join(self.root_dir, rel_path)
            try:
                with open(full_path, "r", encoding="utf-8") as handle:
                    content = handle.read()
            except OSError:
                continue

            excerpt = content[:max_chars].strip()
            if len(content) > max_chars:
                excerpt += "\n..."
            line_count = min(len(content.splitlines()), 80)
            semantic_refs = self._semantic_refs_for_file(rel_path, limit=4)
            slices.append(
                {
                    "file": rel_path,
                    "why": item["why"],
                    "excerpt": excerpt,
                    "line_hint": line_count,
                    "language": self._language_for_file(rel_path),
                    "semantic_refs": semantic_refs,
                    "evidence_groups": [
                        self._make_evidence_group(
                            anchor_symbol=f"file::{rel_path}",
                            role="file_context",
                            why=[item["why"]],
                            evidence_path_refs=sorted(path_refs_by_file.get(rel_path, set())),
                            semantic_refs=semantic_refs,
                        )
                    ],
                    "evidence_path_refs": sorted(path_refs_by_file.get(rel_path, set())),
                }
            )
        return slices

    def _build_project_prompt(self, inventory: Dict[str, object], reads: List[Dict[str, str]]) -> str:
        tech = ", ".join(inventory["likely_technologies"]) if inventory["likely_technologies"] else "unknown stack"
        languages = ", ".join(item["language"] for item in inventory["language_summary"][:4]) or "unknown languages"
        files = ", ".join(item["file"] for item in reads[:6]) if reads else "no obvious entry files"
        return (
            "Start with the project shell. Infer the architecture, runtime shape, and likely developer workflow from "
            f"the manifests and entrypoints first. Stack guess: {tech}. Languages seen: {languages}. "
            f"Recommended first files: {files}. "
            "Then use the confidence-aware evidence, semantic entrypoints, and ambiguity signals before requesting additional files."
        )

    def _compact_text(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", text.lower())

    def _split_identifier_tokens(self, text: str) -> List[str]:
        tokens: List[str] = []
        for part in re.split(r"[^A-Za-z0-9]+", text):
            if not part:
                continue
            lowered = part.lower()
            tokens.append(lowered)
            matches = re.findall(r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+", part)
            if matches:
                tokens.extend(match.lower() for match in matches)
        return self._dedupe([token for token in tokens if token])

    def _query_tokens(self, text: str) -> List[str]:
        raw_tokens = re.findall(r"[A-Za-z0-9]+", text.lower())
        tokens = self._dedupe(raw_tokens + self._split_identifier_tokens(text))
        return [
            token
            for token in tokens
            if token and (len(token) > 2 or token == "di") and token not in QUERY_STOPWORDS
        ]

    def _strict_query_tokens(self, text: str) -> Set[str]:
        return {
            token
            for token in re.findall(r"[A-Za-z0-9]+", text.lower())
            if token and (len(token) > 2 or token == "di") and token not in QUERY_STOPWORDS
        }

    def _query_contains_keyword(self, normalized_query: str, token_set: Set[str], keyword: str) -> bool:
        normalized_keyword = re.sub(r"[^a-z0-9]+", " ", keyword.lower()).strip()
        if not normalized_keyword:
            return False
        if " " in normalized_keyword:
            return normalized_keyword in normalized_query
        return normalized_keyword in token_set

    def _query_mentioned_symbols(self, normalized_query: str, tokens: Set[str], limit: int = 8) -> List[str]:
        matches: List[Tuple[float, str]] = []
        for node in self.nodes.values():
            candidates = [
                node.qualname,
                node.qualname.split(".")[-1],
                node.node_id,
                Path(node.file).stem,
            ]
            best_score = 0.0
            for index, value in enumerate(candidates):
                if not value:
                    continue
                normalized_value = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
                candidate_tokens = [token for token in normalized_value.split() if token]
                compact = self._compact_text(value)
                if normalized_value and " " in normalized_value and normalized_value in normalized_query:
                    best_score = max(best_score, 14.0 - index)
                elif (
                    len(candidate_tokens) == 1
                    and candidate_tokens[0] in tokens
                    and candidate_tokens[0] not in QUERY_GENERIC_MENTION_TOKENS
                    and len(candidate_tokens[0]) >= 5
                ):
                    best_score = max(best_score, 9.0 - index)
                elif compact and len(compact) >= 5 and compact == self._compact_text(normalized_query):
                    best_score = max(best_score, 11.0 - index)
            if not best_score:
                overlap = sorted(
                    token
                    for token in (tokens & set(self._split_identifier_tokens(node.qualname)))
                    if token not in QUERY_GENERIC_MENTION_TOKENS
                )
                if len(overlap) >= 2:
                    best_score = min(6.0, float(len(overlap)) * 1.5)
                elif overlap and len(overlap[0]) >= 8:
                    best_score = 3.5
            if best_score > 0.0:
                matches.append(
                    (
                        -best_score,
                        0 if node.kind in SEMANTIC_EXECUTABLE_KINDS else 1,
                        node.lines[1] - node.lines[0],
                        node.node_id,
                    )
                )
        ordered = sorted(matches)
        out: List[str] = []
        for _, _, _, node_id in ordered:
            if node_id not in out:
                out.append(node_id)
            if len(out) >= limit:
                break
        return out

    def _query_mentioned_files(self, normalized_query: str, tokens: Set[str], limit: int = 6) -> List[str]:
        matches: List[Tuple[float, str]] = []
        for rel_path in sorted({node.file for node in self.nodes.values()}):
            basename = Path(rel_path).name.lower()
            stem = Path(rel_path).stem.lower()
            normalized_basename = re.sub(r"[^a-z0-9]+", " ", basename).strip()
            normalized_stem = re.sub(r"[^a-z0-9]+", " ", stem).strip()
            score = 0.0
            if normalized_basename and " " in normalized_basename and normalized_basename in normalized_query:
                score = max(score, 12.0)
            if normalized_stem and normalized_stem in tokens:
                score = max(score, 10.0)
            compact_stem = self._compact_text(stem)
            if compact_stem and len(compact_stem) >= 5 and compact_stem == self._compact_text(normalized_query):
                score = max(score, 8.0)
            if score > 0.0:
                matches.append((-score, rel_path))
        return [rel_path for _, rel_path in sorted(matches)[:limit]]

    def _infer_query_scope_preference(
        self,
        normalized_query: str,
        inferred_intents: List[str],
        matched_signals: List[str],
        ambiguity_sensitive: bool,
    ) -> str:
        if ambiguity_sensitive or "smallest slice" in normalized_query:
            return "symbol"
        if any(keyword in normalized_query for keyword in ("how", "path", "flow", "reach", "before", "after")):
            return "path"
        if {"auth", "validation"} & set(inferred_intents) or set(matched_signals) & (SEMANTIC_BOUNDARY_SIGNALS | {"auth_guard", "validation_guard"}):
            return "boundary"
        if "architecture" in inferred_intents:
            return "risk"
        if matched_signals:
            return "semantic"
        return "symbol"

    def _build_query_analysis(self, query: str) -> Dict[str, object]:
        normalized_query = re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()
        query_tokens = self._query_tokens(query)
        strict_query_tokens = self._strict_query_tokens(query)
        token_set = set(query_tokens)
        matched_keywords: Set[str] = set()
        inferred_intents: List[str] = []
        for intent, keywords in QUERY_INTENT_KEYWORDS.items():
            hits = [keyword for keyword in keywords if self._query_contains_keyword(normalized_query, token_set, keyword)]
            if hits:
                inferred_intents.append(intent)
                matched_keywords.update(hits)
        matched_signals = [
            signal
            for signal, keywords in QUERY_SIGNAL_KEYWORDS.items()
            if any(self._query_contains_keyword(normalized_query, token_set, keyword) for keyword in keywords)
        ]
        ambiguity_sensitive = bool(
            "ambiguity_resolution" in inferred_intents
            or any(
                self._query_contains_keyword(normalized_query, token_set, keyword)
                for keyword in ("ambiguous", "unresolved", "candidate", "di")
            )
        )
        mentioned_symbols = self._query_mentioned_symbols(normalized_query, strict_query_tokens)
        mentioned_files = self._query_mentioned_files(normalized_query, strict_query_tokens)
        return {
            "raw_query": query,
            "normalized_query": normalized_query,
            "query_tokens": query_tokens,
            "strict_query_tokens": sorted(strict_query_tokens),
            "inferred_intents": inferred_intents,
            "mentioned_symbols": mentioned_symbols,
            "mentioned_files": mentioned_files,
            "matched_semantic_signals": self._sort_semantic_signals(matched_signals),
            "matched_keywords": sorted(matched_keywords),
            "ambiguity_sensitive": ambiguity_sensitive,
            "scope_preference": self._infer_query_scope_preference(
                normalized_query,
                inferred_intents,
                matched_signals,
                ambiguity_sensitive,
            ),
        }

    def _node_query_terms(self, node: SymbolNode) -> Set[str]:
        values = [
            node.node_id,
            node.module,
            node.qualname,
            node.qualname.split(".")[-1],
            node.file,
            Path(node.file).name,
            Path(node.file).stem,
        ]
        out: Set[str] = set()
        for value in values:
            out.update(self._split_identifier_tokens(value))
        return out

    def _query_lexical_match_details(
        self,
        node: SymbolNode,
        analysis: Dict[str, object],
    ) -> Tuple[float, List[str], List[str]]:
        query_tokens = set(str(token) for token in analysis.get("query_tokens", []))
        informative_query_tokens = {token for token in query_tokens if token not in QUERY_GENERIC_MENTION_TOKENS}
        mentioned_symbols = set(str(item) for item in analysis.get("mentioned_symbols", []))
        mentioned_files = set(str(item) for item in analysis.get("mentioned_files", []))
        compact_query = self._compact_text(str(analysis.get("normalized_query", "")))
        score = 0.0
        reasons: List[str] = []
        overlap = sorted(informative_query_tokens & self._node_query_terms(node))
        if node.node_id in mentioned_symbols:
            score += 16.0
            reasons.append("Exact symbol mention in the query.")
        elif self._compact_text(node.qualname.split(".")[-1]) and self._compact_text(node.qualname.split(".")[-1]) in compact_query:
            score += 9.0
            reasons.append("Query mentions the target symbol name.")
        if node.file in mentioned_files:
            score += 9.0
            reasons.append("Query mentions the target file.")
        elif self._compact_text(Path(node.file).stem) and self._compact_text(Path(node.file).stem) in compact_query:
            score += 4.0
            reasons.append("Query mentions the file stem.")
        if overlap:
            score += min(6.0, float(len(overlap)) * 1.5)
            reasons.append(f"Lexical overlap with query tokens: {', '.join(overlap[:4])}.")
        return score, reasons, overlap

    def _query_relevant_semantic_refs(
        self,
        refs: List[Dict[str, object]],
        matched_signals: Set[str],
        limit: int = 4,
    ) -> List[Dict[str, object]]:
        if matched_signals:
            filtered = [ref for ref in refs if str(ref.get("signal", "")) in matched_signals]
            if filtered:
                return self._dedupe_semantic_refs(filtered, limit=limit)
        return self._dedupe_semantic_refs(list(refs), limit=limit)

    def _best_support_edge_for_node(
        self,
        node_id: str,
        inbound: Dict[str, Set[str]],
    ) -> Optional[Dict[str, object]]:
        edges = self._support_edges_for_node(node_id, inbound, limit=4)
        return edges[0] if edges else None

    def _build_query_target_candidate(
        self,
        node_id: str,
        analysis: Dict[str, object],
        inbound: Dict[str, Set[str]],
    ) -> Dict[str, object]:
        node = self.nodes[node_id]
        mentioned_symbols = set(str(item) for item in analysis.get("mentioned_symbols", []))
        mentioned_files = set(str(item) for item in analysis.get("mentioned_files", []))
        matched_signals = set(str(item) for item in analysis.get("matched_semantic_signals", []))
        matched_signal_count = max(1, len(matched_signals))
        direct_match = self._sort_semantic_signals(signal for signal in node.semantic_signals if signal in matched_signals)
        contained_match = self._sort_semantic_signals(signal for signal in node.contained_semantic_signals if signal in matched_signals)
        direct_coverage = float(len(direct_match)) / float(matched_signal_count) if matched_signals else 0.0
        contained_coverage = float(len(contained_match)) / float(matched_signal_count) if matched_signals else 0.0
        direct_refs = self._query_relevant_semantic_refs(list(node.semantic_evidence_spans), matched_signals, limit=4)
        contained_refs = self._query_relevant_semantic_refs(list(node.contained_semantic_refs), matched_signals, limit=4)
        lexical_score, lexical_reasons, lexical_overlap = self._query_lexical_match_details(node, analysis)
        has_strong_query_anchor = bool(
            node_id in mentioned_symbols
            or node.file in mentioned_files
            or len(lexical_overlap) >= 2
            or any(len(token) >= 8 for token in lexical_overlap)
        )
        best_support = self._best_support_edge_for_node(node_id, inbound)
        support_score = float(best_support.get("confidence_score", 0.0)) if best_support else 0.0
        support_label = str(best_support.get("confidence_label", "")) if best_support else ""
        match_reasons = list(lexical_reasons)
        if direct_match:
            match_reasons.append(f"Direct semantic match: {', '.join(direct_match[:4])}.")
        if contained_match and not direct_match:
            match_reasons.append(f"Contained semantic match only: {', '.join(contained_match[:4])}.")
        if best_support is not None:
            match_reasons.append(
                f"Best supporting edge is `{best_support['resolution_kind']}` with `{best_support['confidence_label']}` confidence."
            )
        ambiguity_relevance = bool(
            node.unresolved_call_details
            and (
                bool(analysis.get("ambiguity_sensitive"))
                or node_id in set(str(item) for item in analysis.get("mentioned_symbols", []))
            )
        )
        if ambiguity_relevance:
            match_reasons.append("Relevant unresolved ambiguity is attached to this node.")
        executable_bonus = 3.5 if node.kind in SEMANTIC_EXECUTABLE_KINDS else (0.5 if node.kind in {"class", "interface", "enum", "record"} else -2.0)
        scope_preference = str(analysis.get("scope_preference", "symbol"))
        selection_score = (
            lexical_score
            + (float(len(direct_match)) * 8.0)
            + (float(len(contained_match)) * 3.0)
            + min(node.risk_score / 18.0, 5.0)
            + (support_score * 2.5)
            + (direct_coverage * 4.0)
            + (contained_coverage * 1.5)
            + executable_bonus
            + (5.0 if ambiguity_relevance else 0.0)
        )
        if not direct_match and contained_match:
            selection_score -= 2.0
        if len(matched_signals) > 1:
            if direct_coverage >= 0.99:
                selection_score += 10.0
                match_reasons.append("Direct semantic coverage matches all requested query signals.")
            elif direct_match:
                selection_score -= (1.0 - direct_coverage) * 8.0
                if scope_preference == "path" and not has_strong_query_anchor:
                    selection_score -= 10.0
                    match_reasons.append("Only partial semantic coverage and no strong lexical/path anchor for this multi-signal query.")
                else:
                    match_reasons.append("Only partial direct semantic coverage for the multi-signal query.")
            elif contained_coverage >= 0.99:
                selection_score += 1.5
                if scope_preference == "path":
                    selection_score -= 3.0
                match_reasons.append("Contained semantics cover all requested signals, but only indirectly.")
            elif contained_match:
                selection_score -= (1.0 - contained_coverage) * 6.0 + 4.0
                if scope_preference == "path" and not has_strong_query_anchor:
                    selection_score -= 6.0
                match_reasons.append("Only partial contained semantic coverage for the multi-signal query.")
            elif scope_preference == "path" and not has_strong_query_anchor:
                selection_score -= 3.0
        if scope_preference == "path" and node.kind in SEMANTIC_EXECUTABLE_KINDS and self.adj.get(node_id):
            selection_score += 1.5
        if scope_preference == "boundary" and set(direct_match) & (SEMANTIC_BOUNDARY_SIGNALS | {"auth_guard", "validation_guard"}):
            selection_score += 2.0
        if scope_preference == "semantic" and direct_match:
            selection_score += 2.0
        if scope_preference == "symbol" and node_id in set(str(item) for item in analysis.get("mentioned_symbols", [])):
            selection_score += 2.0
        return {
            "node_id": node_id,
            "file": node.file,
            "lines": node.lines,
            "kind": node.kind,
            "language": node.language,
            "risk_score": node.risk_score,
            "lexical_overlap": lexical_overlap,
            "match_reasons": match_reasons,
            "direct_semantic_match": direct_match,
            "contained_semantic_match": contained_match,
            "direct_semantic_refs": direct_refs,
            "contained_semantic_refs": contained_refs,
            "semantic_signals": list(node.semantic_signals),
            "contained_semantic_signals": list(node.contained_semantic_signals),
            "direct_semantic_coverage": round(direct_coverage, 2),
            "contained_semantic_coverage": round(contained_coverage, 2),
            "has_strong_query_anchor": has_strong_query_anchor,
            "best_support_label": support_label,
            "best_support_score": round(support_score, 2),
            "ambiguity_relevance": ambiguity_relevance,
            "base_selection_score": round(selection_score, 2),
        }

    def _build_query_evidence_paths(
        self,
        candidates: List[Dict[str, object]],
        inbound: Dict[str, Set[str]],
        analysis: Dict[str, object],
        limit: int = 8,
    ) -> List[Dict[str, object]]:
        paths: List[Dict[str, object]] = []
        mentioned_symbols = set(str(item) for item in analysis.get("mentioned_symbols", []))
        mentioned_files = set(str(item) for item in analysis.get("mentioned_files", []))
        query_tokens = set(str(item) for item in analysis.get("query_tokens", []))
        matched_signals = set(str(item) for item in analysis.get("matched_semantic_signals", []))
        matched_signal_keywords = {
            keyword
            for signal in matched_signals
            for keyword in QUERY_SIGNAL_KEYWORDS.get(signal, ())
        }
        matched_signal_count = max(1, len(matched_signals))
        full_coverage_present = any(
            float(candidate.get("direct_semantic_coverage", 0.0)) >= 0.99
            or float(candidate.get("contained_semantic_coverage", 0.0)) >= 0.99
            for candidate in candidates
        )
        for candidate in candidates[:8]:
            candidate_coverage = max(
                float(candidate.get("direct_semantic_coverage", 0.0)),
                float(candidate.get("contained_semantic_coverage", 0.0)) * 0.7,
            )
            candidate_has_strong_anchor = bool(candidate.get("has_strong_query_anchor"))
            if (
                len(matched_signals) > 1
                and full_coverage_present
                and candidate_coverage < 0.99
                and not candidate_has_strong_anchor
            ):
                continue
            faux_candidate = {
                "node_id": candidate["node_id"],
                "bundle_priority": candidate["base_selection_score"],
                "ambiguity_flags": [{}] if candidate["ambiguity_relevance"] else [],
            }
            for path in self._build_evidence_paths_for_candidate(faux_candidate, inbound, limit=2):
                path_signals = set(str(item) for item in path.get("semantic_signals", []))
                signal_matches = self._sort_semantic_signals(path_signals & matched_signals)
                path_nodes = {str(path.get("risk_node", ""))}
                for hop in path.get("hops", []):
                    path_nodes.add(str(hop.get("source", "")))
                    path_nodes.add(str(hop.get("target", "")))
                lexical_hits = [node_id for node_id in sorted(path_nodes) if node_id in mentioned_symbols]
                file_hits = [
                    self.nodes[node_id].file
                    for node_id in sorted(path_nodes)
                    if node_id in self.nodes and self.nodes[node_id].file in mentioned_files
                ]
                path_term_overlap = sorted(
                    token
                    for node_id in path_nodes
                    if node_id in self.nodes
                    for token in (query_tokens & self._node_query_terms(self.nodes[node_id]))
                )
                signal_keyword_hits = sorted(
                    token
                    for node_id in path_nodes
                    if node_id in self.nodes
                    for token in (matched_signal_keywords & self._node_query_terms(self.nodes[node_id]))
                )
                has_query_anchor = bool(signal_matches or lexical_hits or file_hits or path_term_overlap or signal_keyword_hits)
                if not has_query_anchor:
                    continue
                signal_coverage = float(len(signal_matches)) / float(matched_signal_count) if matched_signals else 0.0
                score = (
                    (float(len(signal_matches)) * 5.0)
                    + (float(len(lexical_hits)) * 3.0)
                    + min(4.0, float(len(set(file_hits))) * 2.0)
                    + min(4.0, float(len(set(path_term_overlap))) * 1.0)
                    + min(4.0, float(len(set(signal_keyword_hits))) * 1.5)
                    + (float(path.get("path_confidence", 0.0)) * 4.0)
                    + (signal_coverage * 6.0)
                    + (2.0 if str(analysis.get("scope_preference", "")) == "path" else 0.0)
                    + (1.5 if len(path.get("hops", [])) > 1 else 0.0)
                )
                if len(matched_signals) > 1:
                    if signal_coverage >= 0.99:
                        score += 6.0
                    elif signal_matches:
                        score -= (1.0 - signal_coverage) * 7.0
                        if str(analysis.get("scope_preference", "")) == "path" and not (lexical_hits or file_hits):
                            score -= 5.0
                    elif signal_keyword_hits:
                        if str(analysis.get("scope_preference", "")) == "path" and not (lexical_hits or file_hits):
                            score -= 2.0
                    elif full_coverage_present:
                        score -= 8.0
                    elif str(analysis.get("scope_preference", "")) == "path":
                        score -= 6.0
                elif matched_signals and not signal_matches and not signal_keyword_hits and str(analysis.get("scope_preference", "")) == "path":
                    score -= 4.0
                reasons: List[str] = []
                if signal_matches:
                    reasons.append(f"Path semantic match: {', '.join(signal_matches[:4])}.")
                if lexical_hits:
                    reasons.append("Path includes a lexically mentioned symbol.")
                if file_hits:
                    reasons.append("Path includes a mentioned file.")
                if path_term_overlap:
                    reasons.append(f"Path overlaps query tokens: {', '.join(sorted(set(path_term_overlap))[:4])}.")
                if signal_keyword_hits:
                    reasons.append(f"Path overlaps semantic hint terms: {', '.join(sorted(set(signal_keyword_hits))[:4])}.")
                enriched = dict(path)
                enriched["query_match_score"] = round(score, 2)
                enriched["query_match_reasons"] = reasons
                enriched["query_match_signals"] = signal_matches
                paths.append(enriched)
        paths.sort(
            key=lambda item: (
                -float(item.get("query_match_score", 0.0)),
                -float(item.get("path_confidence", 0.0)),
                -len(item.get("hops", [])),
                str(item.get("path_id", "")),
            )
        )
        return paths[:limit]

    def _build_query_ambiguity_watchlist(
        self,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        limit: int = 4,
    ) -> List[Dict[str, object]]:
        mentioned_symbols = set(str(item) for item in analysis.get("mentioned_symbols", [])) | {
            str(item["node_id"]) for item in ranked_targets[:6]
        }
        mentioned_files = set(str(item) for item in analysis.get("mentioned_files", []))
        query_tokens = set(str(item) for item in analysis.get("query_tokens", []))
        items: List[Dict[str, object]] = []
        for item in self._build_ambiguity_watchlist(limit=50):
            score = 0.0
            reasons: List[str] = []
            if bool(analysis.get("ambiguity_sensitive")):
                score += 8.0
                reasons.append("Query explicitly asks for ambiguity handling.")
            if str(item["source_node"]) in mentioned_symbols:
                score += 6.0
                reasons.append("Ambiguous source node is directly relevant to the query.")
            if str(item["file"]) in mentioned_files:
                score += 3.0
                reasons.append("Ambiguous file is mentioned in the query.")
            raw_blob = " ".join(
                [str(item.get("source_node", "")), str(item.get("raw_call", ""))]
                + [str(candidate) for candidate in item.get("candidates", [])]
            ).lower()
            if any(token in raw_blob for token in query_tokens):
                score += 2.0
                reasons.append("Ambiguity details overlap the query terms.")
            if score <= 0.0 and not (bool(analysis.get("ambiguity_sensitive")) and len(self._build_ambiguity_watchlist(limit=50)) == 1):
                continue
            enriched = dict(item)
            enriched["query_match_score"] = round(score, 2)
            enriched["query_match_reasons"] = reasons
            items.append(enriched)
        items.sort(
            key=lambda item: (
                -float(item.get("query_match_score", 0.0)),
                -float(self.nodes[item["source_node"]].risk_score),
                str(item["source_node"]),
            )
        )
        return items[:limit]

    def _build_query_slice_spec(
        self,
        node_id: str,
        why: List[str],
        selection_score: float,
        selection_confidence_label: str,
        supporting_edges: Optional[List[Dict[str, object]]] = None,
        ambiguity_flags: Optional[List[Dict[str, object]]] = None,
        role: str = "query_target",
        evidence_path_refs: Optional[List[str]] = None,
        semantic_refs: Optional[List[Dict[str, object]]] = None,
    ) -> Dict[str, object]:
        node = self.nodes[node_id]
        file_lines = self._read_project_lines(node.file)
        file_end = len(file_lines) if file_lines else int(node.lines[1])
        focus_refs = self._dedupe_semantic_refs(list(semantic_refs or []), limit=4)
        if focus_refs:
            start_line = max(1, min(int(ref["lines"][0]) for ref in focus_refs) - 1)
            end_line = min(file_end, max(int(ref["lines"][1]) for ref in focus_refs) + 1)
        else:
            start_line = max(1, int(node.lines[0]) - 1)
            end_line = min(file_end, int(node.lines[1]) + 1)
        labels = self._sort_confidence_labels([selection_confidence_label or "medium"])
        return {
            "file": node.file,
            "start_line": start_line,
            "end_line": max(start_line, end_line),
            "symbols": [node_id],
            "why": list(why),
            "selection_score": round(selection_score, 2),
            "selection_confidence_label": selection_confidence_label or "medium",
            "selection_confidence_labels": labels,
            "supporting_edges": list(supporting_edges or []),
            "ambiguity_flags": list(ambiguity_flags or []),
            "semantic_refs": focus_refs,
            "evidence_path_refs": sorted(set(str(item) for item in evidence_path_refs or [] if item)),
            "evidence_groups": [
                self._make_evidence_group(
                    anchor_symbol=node_id,
                    role=role,
                    why=why,
                    supporting_edges=supporting_edges,
                    selection_confidence_labels=labels,
                    ambiguity_flags=ambiguity_flags,
                    selection_score=selection_score,
                    evidence_path_refs=evidence_path_refs,
                    semantic_refs=focus_refs,
                )
            ],
        }

    def _slice_ref(self, spec: Dict[str, object]) -> str:
        return f"{spec['file']}:{spec['start_line']}-{spec['end_line']}"

    def _flow_node_label(self, node_id: str) -> str:
        node = self.nodes.get(node_id)
        if node is None:
            return node_id
        if node.kind == "module":
            return Path(node.file).name
        tail = node.qualname.split(".")[-1] if node.qualname else ""
        return tail or Path(node.file).stem or node.node_id

    def _slice_refs_by_symbol(self, slices: List[Dict[str, object]]) -> Dict[str, List[str]]:
        mapping: Dict[str, List[str]] = defaultdict(list)
        for spec in slices:
            slice_ref = self._slice_ref(spec)
            for symbol in spec.get("symbols", []):
                mapping[str(symbol)].append(slice_ref)
        return {
            symbol: sorted(set(refs))
            for symbol, refs in mapping.items()
        }

    def _flow_completeness_label(
        self,
        step_kinds: List[str],
        matched_signals: Set[str],
    ) -> str:
        if not step_kinds:
            return "missing"
        if not matched_signals:
            return "context_only"
        covered = set(step_kinds) & matched_signals
        if covered >= matched_signals:
            return "complete"
        if covered:
            return "partial"
        return "context_only"

    def _ordered_path_nodes(self, path: Dict[str, object]) -> List[str]:
        hop_pairs = [
            (str(hop.get("source", "")), str(hop.get("target", "")))
            for hop in path.get("hops", [])
            if str(hop.get("source", "")) in self.nodes and str(hop.get("target", "")) in self.nodes
        ]
        nodes = {str(path.get("risk_node", ""))} | {source for source, _ in hop_pairs} | {target for _, target in hop_pairs}
        nodes = {node_id for node_id in nodes if node_id in self.nodes}
        if not nodes:
            return []

        outgoing: Dict[str, List[str]] = defaultdict(list)
        indegree: Dict[str, int] = {node_id: 0 for node_id in nodes}
        for source, target in hop_pairs:
            outgoing[source].append(target)
            indegree[target] = indegree.get(target, 0) + 1
            indegree.setdefault(source, 0)

        for source in outgoing:
            outgoing[source] = sorted(set(outgoing[source]), key=lambda node_id: (self._flow_node_label(node_id), node_id))

        starts = sorted(
            [node_id for node_id, degree in indegree.items() if degree == 0],
            key=lambda node_id: (0 if self.nodes[node_id].kind in SEMANTIC_EXECUTABLE_KINDS else 1, self._flow_node_label(node_id), node_id),
        )
        if not starts:
            ordered = sorted(nodes, key=lambda node_id: (self._flow_node_label(node_id), node_id))
            risk_node = str(path.get("risk_node", ""))
            if risk_node in ordered:
                ordered.remove(risk_node)
                ordered.insert(0, risk_node)
            return ordered

        ordered: List[str] = []
        visited: Set[str] = set()
        current = starts[0]
        while current and current not in visited:
            ordered.append(current)
            visited.add(current)
            next_nodes = [node_id for node_id in outgoing.get(current, []) if node_id not in visited]
            current = next_nodes[0] if next_nodes else ""

        for node_id in sorted(nodes - set(ordered), key=lambda item: (self._flow_node_label(item), item)):
            ordered.append(node_id)
        return ordered

    def _build_flow_chain_compact_string(
        self,
        ordered_nodes: List[str],
        stitched_step_kinds: List[str],
        matched_signals: Set[str],
    ) -> str:
        if len(ordered_nodes) <= 1 and stitched_step_kinds:
            return " -> ".join(stitched_step_kinds)
        if matched_signals and set(stitched_step_kinds) >= matched_signals and len(stitched_step_kinds) >= max(2, len(matched_signals)):
            return " -> ".join(stitched_step_kinds)
        node_labels = [self._flow_node_label(node_id) for node_id in ordered_nodes]
        if stitched_step_kinds:
            return " -> ".join(node_labels + stitched_step_kinds)
        return " -> ".join(node_labels)

    def _build_selected_flow_summaries(
        self,
        ranked_targets: List[Dict[str, object]],
        merged_slices: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
        analysis: Dict[str, object],
        limit: int = 6,
    ) -> List[Dict[str, object]]:
        selected_symbols = {str(symbol) for spec in merged_slices for symbol in spec.get("symbols", [])}
        slice_refs_by_symbol = self._slice_refs_by_symbol(merged_slices)
        path_refs_by_symbol: Dict[str, List[str]] = defaultdict(list)
        path_map = {
            str(path.get("path_id", "")): path
            for path in selected_paths
            if path.get("path_id")
        }
        for path in selected_paths:
            path_id = str(path.get("path_id", ""))
            for node_id in self._ordered_path_nodes(path):
                path_refs_by_symbol[node_id].append(path_id)

        out: List[Dict[str, object]] = []
        seen: Set[str] = set()
        matched_signals = set(str(item) for item in analysis.get("matched_semantic_signals", []))
        ordered_candidates = [str(item["node_id"]) for item in ranked_targets] + sorted(selected_symbols)
        for node_id in ordered_candidates:
            if node_id in seen or node_id not in selected_symbols or node_id not in self.nodes:
                continue
            node = self.nodes[node_id]
            if node.kind not in SEMANTIC_EXECUTABLE_KINDS or not node.behavioral_flow_summary:
                continue
            ordered_step_kinds = list(node.behavioral_flow_summary.get("ordered_step_kinds", []))
            matched_step_kinds = self._sort_semantic_signals(set(ordered_step_kinds) & matched_signals)
            completeness = self._flow_completeness_label(ordered_step_kinds, matched_signals)
            supporting_path_refs = sorted(set(path_refs_by_symbol.get(node_id, [])))
            if matched_signals and completeness == "context_only" and not supporting_path_refs:
                continue
            if (
                matched_signals
                and completeness == "context_only"
                and supporting_path_refs
                and not any(
                    path_map.get(path_id, {}).get("query_match_signals", [])
                    for path_id in supporting_path_refs
                )
            ):
                continue
            out.append(
                {
                    "node_id": node_id,
                    "file": node.file,
                    "lines": list(node.lines),
                    "ordered_step_kinds": ordered_step_kinds,
                    "matched_step_kinds": matched_step_kinds,
                    "flow_compact_string": str(node.behavioral_flow_summary.get("flow_compact_string", "")),
                    "guard_count": int(node.behavioral_flow_summary.get("guard_count", 0)),
                    "side_effect_count": int(node.behavioral_flow_summary.get("side_effect_count", 0)),
                    "has_terminal_output": bool(node.behavioral_flow_summary.get("has_terminal_output", False)),
                    "has_error_path": bool(node.behavioral_flow_summary.get("has_error_path", False)),
                    "completeness": completeness,
                    "supporting_slice_refs": slice_refs_by_symbol.get(node_id, []),
                    "supporting_path_refs": supporting_path_refs,
                    "behavioral_flow_steps": list(node.behavioral_flow_steps[:8]),
                }
            )
            seen.add(node_id)
            if len(out) >= limit:
                break
        return out

    def _build_selected_flow_chains(
        self,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
        merged_slices: List[Dict[str, object]],
        selected_flow_summaries: List[Dict[str, object]],
        limit: int = 4,
    ) -> List[Dict[str, object]]:
        slice_refs_by_symbol = self._slice_refs_by_symbol(merged_slices)
        selected_summary_map = {str(item["node_id"]): item for item in selected_flow_summaries}
        matched_signals = set(str(item) for item in analysis.get("matched_semantic_signals", []))
        mentioned_symbols = set(str(item) for item in analysis.get("mentioned_symbols", []))
        mentioned_files = set(str(item) for item in analysis.get("mentioned_files", []))
        rank_by_node = {
            str(item["node_id"]): index
            for index, item in enumerate(ranked_targets, start=1)
        }
        matched_signal_keywords = {
            keyword
            for signal in matched_signals
            for keyword in QUERY_SIGNAL_KEYWORDS.get(signal, ())
        }
        chains: List[Dict[str, object]] = []
        seen: Set[str] = set()

        def append_chain(
            chain_id: str,
            query_anchor: str,
            ordered_nodes: List[str],
            stitched_step_kinds: List[str],
            supporting_path_refs: List[str],
            stop_reason: str,
        ) -> None:
            if not ordered_nodes or (not stitched_step_kinds and len(ordered_nodes) < 2):
                return
            completeness = self._flow_completeness_label(stitched_step_kinds, matched_signals)
            if completeness == "context_only" and matched_signals and not supporting_path_refs:
                return
            supporting_slice_refs: List[str] = []
            seen_slice_refs: Set[str] = set()
            for node_id in ordered_nodes:
                for ref in slice_refs_by_symbol.get(node_id, []):
                    ref = str(ref)
                    if ref in seen_slice_refs:
                        continue
                    seen_slice_refs.add(ref)
                    supporting_slice_refs.append(ref)
            signature = json.dumps(
                {
                    "query_anchor": query_anchor,
                    "nodes": ordered_nodes,
                    "steps": stitched_step_kinds,
                },
                sort_keys=True,
            )
            if signature in seen:
                return
            seen.add(signature)
            mentioned_match_count = sum(
                1
                for node_id in ordered_nodes
                if node_id in mentioned_symbols
                or (node_id in self.nodes and self.nodes[node_id].file in mentioned_files)
            )
            matched_step_count = len(set(str(item) for item in stitched_step_kinds) & matched_signals)
            chains.append(
                {
                    "chain_id": chain_id,
                    "query_anchor": query_anchor,
                    "nodes": ordered_nodes,
                    "stitched_step_kinds": stitched_step_kinds,
                    "flow_compact_string": self._build_flow_chain_compact_string(ordered_nodes, stitched_step_kinds, matched_signals),
                    "supporting_path_refs": supporting_path_refs,
                    "supporting_slice_refs": supporting_slice_refs,
                    "completeness": completeness,
                    "stop_reason": stop_reason,
                    "_query_anchor_rank": int(rank_by_node.get(query_anchor, 999)),
                    "_mentioned_match_count": mentioned_match_count,
                    "_matched_step_count": matched_step_count,
                    "_node_count": len(ordered_nodes),
                }
            )

        for index, path in enumerate(selected_paths, start=1):
            raw_ordered_nodes = self._ordered_path_nodes(path)
            if (
                (mentioned_symbols or mentioned_files)
                and not any(
                    node_id in mentioned_symbols
                    or (node_id in self.nodes and self.nodes[node_id].file in mentioned_files)
                    for node_id in raw_ordered_nodes
                )
                and int(rank_by_node.get(str(path.get("risk_node", "")), 999)) > 3
            ):
                continue
            ordered_nodes = [
                node_id
                for node_id in raw_ordered_nodes
                if node_id in self.nodes and self.nodes[node_id].kind in SEMANTIC_EXECUTABLE_KINDS
            ]
            flow_nodes = [node_id for node_id in ordered_nodes if node_id in selected_summary_map]
            if not flow_nodes:
                continue
            first_flow = selected_summary_map[flow_nodes[0]]
            if matched_signals and len(ordered_nodes) > 1:
                flow_start_index = ordered_nodes.index(flow_nodes[0])
                downstream_nodes = ordered_nodes[flow_start_index + 1 :]
                downstream_relevance = any(
                    node_id in self.nodes
                    and (
                        bool(set(str(item) for item in self.nodes[node_id].semantic_signals) & matched_signals)
                        or bool(set(self._node_query_terms(self.nodes[node_id])) & matched_signal_keywords)
                        or node_id in mentioned_symbols
                        or self.nodes[node_id].file in mentioned_files
                    )
                    for node_id in downstream_nodes
                )
                if not downstream_relevance:
                    if flow_start_index == 0:
                        continue
                    ordered_nodes = ordered_nodes[: flow_start_index + 1]
                    flow_nodes = [node_id for node_id in ordered_nodes if node_id in selected_summary_map]
                    if not flow_nodes:
                        continue
                    first_flow = selected_summary_map[flow_nodes[0]]
            if len(ordered_nodes) == 1:
                stitched_step_kinds = list(first_flow.get("ordered_step_kinds", []))
            elif (
                matched_signals
                and set(str(item) for item in first_flow.get("ordered_step_kinds", [])) >= matched_signals
                and len(first_flow.get("ordered_step_kinds", [])) >= max(2, len(matched_signals))
            ):
                stitched_step_kinds = list(first_flow.get("ordered_step_kinds", []))
            else:
                stitched_step_kinds = self._compact_behavioral_step_kinds(
                    step_kind
                    for node_position, node_id in enumerate(flow_nodes)
                    for step_kind in (
                        [
                            kind
                            for kind in selected_summary_map[node_id].get("ordered_step_kinds", [])
                            if not (
                                node_position < len(flow_nodes) - 1
                                and kind == "output_boundary"
                            )
                        ]
                    )
                )
            append_chain(
                chain_id=f"{path.get('path_id', f'flow_chain_{index}')}",
                query_anchor=str(path.get("risk_node", "")),
                ordered_nodes=ordered_nodes,
                stitched_step_kinds=stitched_step_kinds,
                supporting_path_refs=[str(path.get("path_id", ""))] if path.get("path_id") else [],
                stop_reason=str(path.get("stop_reason", "")) or "path_selected",
            )

        if not chains and matched_signals:
            for index, path in enumerate(selected_paths, start=1):
                ordered_nodes = [
                    node_id
                    for node_id in self._ordered_path_nodes(path)
                    if node_id in self.nodes and self.nodes[node_id].kind in SEMANTIC_EXECUTABLE_KINDS
                ]
                if len(ordered_nodes) < 2:
                    continue
                query_anchor = str(path.get("risk_node", ""))
                if (
                    (mentioned_symbols or mentioned_files)
                    and not any(
                        node_id in mentioned_symbols
                        or (node_id in self.nodes and self.nodes[node_id].file in mentioned_files)
                        for node_id in ordered_nodes
                    )
                    and int(rank_by_node.get(query_anchor, 999)) > 3
                ):
                    continue
                append_chain(
                    chain_id=f"{path.get('path_id', f'flow_chain_{index}')}::context",
                    query_anchor=query_anchor,
                    ordered_nodes=ordered_nodes,
                    stitched_step_kinds=[],
                    supporting_path_refs=[str(path.get("path_id", ""))] if path.get("path_id") else [],
                    stop_reason="path_without_direct_semantic_evidence",
                )
                if len(chains) >= limit:
                    break

        if len(chains) < limit:
            for index, item in enumerate(selected_flow_summaries, start=1):
                node_id = str(item["node_id"])
                append_chain(
                    chain_id=f"{node_id}::single_flow::{index}",
                    query_anchor=node_id,
                    ordered_nodes=[node_id],
                    stitched_step_kinds=list(item.get("ordered_step_kinds", [])),
                    supporting_path_refs=list(item.get("supporting_path_refs", [])),
                    stop_reason="single_node_flow",
                )
                if len(chains) >= limit:
                    break

        chains.sort(
            key=lambda item: (
                -FLOW_COMPLETENESS_ORDER.get(str(item.get("completeness", "")), 0),
                -int(item.get("_mentioned_match_count", 0)),
                -int(item.get("_matched_step_count", 0)),
                int(item.get("_query_anchor_rank", 999)),
                -len(item.get("supporting_path_refs", [])),
                -int(item.get("_node_count", 0)),
                -len(item.get("stitched_step_kinds", [])),
                str(item.get("chain_id", "")),
            )
        )
        deduped: List[Dict[str, object]] = []
        dedupe_seen: Set[str] = set()
        for item in chains:
            dedupe_key = json.dumps(
                {
                    "query_anchor": str(item.get("query_anchor", "")),
                    "stitched_step_kinds": list(item.get("stitched_step_kinds", [])),
                },
                sort_keys=True,
            )
            if dedupe_key in dedupe_seen:
                continue
            dedupe_seen.add(dedupe_key)
            payload = dict(item)
            for key in ("_query_anchor_rank", "_mentioned_match_count", "_matched_step_count", "_node_count"):
                payload.pop(key, None)
            deduped.append(payload)
            if len(deduped) >= limit:
                break
        return deduped

    def _build_flow_gaps(
        self,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        selected_flow_summaries: List[Dict[str, object]],
        selected_flow_chains: List[Dict[str, object]],
        limit: int = 4,
    ) -> List[Dict[str, object]]:
        matched_signals = set(str(item) for item in analysis.get("matched_semantic_signals", []))
        summary_map = {str(item["node_id"]): item for item in selected_flow_summaries}
        items: List[Dict[str, object]] = []
        for target in ranked_targets[:6]:
            node_id = str(target["node_id"])
            node = self.nodes.get(node_id)
            if node is None or node.kind not in SEMANTIC_EXECUTABLE_KINDS:
                continue
            summary = summary_map.get(node_id)
            if summary is None:
                continue
            missing_step_kinds = sorted(matched_signals - set(str(item) for item in summary.get("ordered_step_kinds", [])))
            if not missing_step_kinds:
                continue
            items.append(
                {
                    "gap_kind": "partial_node_flow",
                    "node_id": node_id,
                    "missing_step_kinds": missing_step_kinds,
                    "reason": "Selected executable flow covers only part of the query-matched semantic signals.",
                    "supporting_slice_refs": list(summary.get("supporting_slice_refs", [])),
                    "supporting_path_refs": list(summary.get("supporting_path_refs", [])),
                }
            )
        for chain in selected_flow_chains:
            if str(chain.get("completeness", "")) == "complete":
                continue
            items.append(
                {
                    "gap_kind": "incomplete_flow_chain",
                    "chain_id": str(chain.get("chain_id", "")),
                    "missing_step_kinds": sorted(matched_signals - set(str(item) for item in chain.get("stitched_step_kinds", []))),
                    "reason": "The stitched behavioral flow chain remains partial for the query signals.",
                    "supporting_slice_refs": list(chain.get("supporting_slice_refs", [])),
                    "supporting_path_refs": list(chain.get("supporting_path_refs", [])),
                }
            )
        return self._dedupe_object_list(items)[:limit]

    def _analysis_overall_goal(self, query: str, analysis: Dict[str, object]) -> str:
        matched_signals = list(analysis.get("matched_semantic_signals", []))
        if matched_signals:
            return (
                "Determine whether the selected evidence proves "
                f"`{', '.join(str(item) for item in matched_signals[:4])}` for `{query}`."
            )
        intents = list(analysis.get("inferred_intents", []))
        if intents:
            return (
                "Determine the smallest evidenced answer to "
                f"`{query}` with emphasis on `{', '.join(str(item) for item in intents[:3])}`."
            )
        return f"Determine the smallest evidenced answer to `{query}`."

    def _recommended_analysis_outcome_mode(
        self,
        analysis: Dict[str, object],
        selected_flow_summaries: List[Dict[str, object]],
        selected_flow_chains: List[Dict[str, object]],
        flow_gaps: List[Dict[str, object]],
        ambiguity_watchlist: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
    ) -> str:
        matched_signals = set(str(item) for item in analysis.get("matched_semantic_signals", []))
        if ambiguity_watchlist:
            return "ambiguous"
        if any(str(item.get("completeness", "")) == "complete" for item in selected_flow_chains):
            return "confirmed"
        if any(str(item.get("completeness", "")) == "complete" for item in selected_flow_summaries):
            return "confirmed"
        covered_signals = {
            signal
            for item in selected_flow_summaries
            for signal in item.get("ordered_step_kinds", [])
            if signal in matched_signals
        } | {
            signal
            for item in selected_flow_chains
            for signal in item.get("stitched_step_kinds", [])
            if signal in matched_signals
        }
        if matched_signals:
            if covered_signals:
                return "partial" if flow_gaps else "confirmed"
            return "unproven"
        if selected_flow_chains or selected_flow_summaries or selected_paths:
            return "partial"
        return "unproven"

    def _build_analysis_candidate_outcomes(
        self,
        query: str,
        analysis: Dict[str, object],
        recommended_outcome_mode: str,
    ) -> List[Dict[str, object]]:
        matched_signals = [str(item) for item in analysis.get("matched_semantic_signals", [])]
        signal_text = ", ".join(matched_signals[:4]) if matched_signals else "the requested behavior"
        templates = {
            "confirmed": {
                "claim_template": f"Confirmed: `{query}` is directly supported by the selected evidence for {signal_text}.",
                "evidence_requirements": [
                    "A selected slice or complete flow chain covers all query-matched signals.",
                    "No unresolved ambiguity remains on the answering path.",
                ],
                "when_to_choose": "Choose this once the selected slices and flow/path evidence answer the query without missing signals.",
                "forbidden_overreach": "Do not claim extra transitions or side effects that are not directly evidenced.",
            },
            "partial": {
                "claim_template": f"Partial: `{query}` is only partly supported; one or more transitions or signals remain open.",
                "evidence_requirements": [
                    "At least one relevant slice or flow chain is directly evidenced.",
                    "A flow gap, missing transition, or weakly supported step remains.",
                ],
                "when_to_choose": "Choose this when the main path is visible but the full requested claim is not yet closed.",
                "forbidden_overreach": "Do not upgrade a partial chain into a complete claim.",
            },
            "unproven": {
                "claim_template": f"Unproven: `{query}` cannot be proven from the selected evidence.",
                "evidence_requirements": [
                    "Primary slices and selected paths were inspected.",
                    "No direct evidence proves the missing signal(s).",
                ],
                "when_to_choose": "Choose this when the available slices stay structural or contextual and the key signal never appears directly.",
                "forbidden_overreach": "Do not infer the missing behavior from naming, wrappers, or adjacency alone.",
            },
            "ambiguous": {
                "claim_template": f"Ambiguous: `{query}` still has multiple plausible interpretations or unresolved candidates.",
                "evidence_requirements": [
                    "An ambiguity_watchlist item or competing candidate set remains unresolved.",
                    "The selected slices do not remove that ambiguity decisively.",
                ],
                "when_to_choose": "Choose this when the best available evidence still branches into multiple plausible answers.",
                "forbidden_overreach": "Do not collapse multiple candidates into a single confirmed answer.",
            },
        }
        order = [recommended_outcome_mode] + [
            item for item in ("confirmed", "partial", "unproven", "ambiguous")
            if item != recommended_outcome_mode
        ]
        return [
            {"outcome_mode": outcome_mode, **templates[outcome_mode]}
            for outcome_mode in order
        ]

    def _build_minimal_open_sequence(
        self,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        selected_slices: List[Dict[str, object]],
        selected_flow_summaries: List[Dict[str, object]],
        selected_flow_chains: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
        flow_gaps: List[Dict[str, object]],
        recommended_outcome_mode: str,
        primary_target_id: str = "",
        primary_chain: Optional[Dict[str, object]] = None,
        primary_path: Optional[Dict[str, object]] = None,
        primary_gap: Optional[Dict[str, object]] = None,
        limit: int = 4,
    ) -> List[Dict[str, object]]:
        matched_signals = set(str(item) for item in analysis.get("matched_semantic_signals", []))
        slice_by_ref = {self._slice_ref(spec): spec for spec in selected_slices}
        slice_refs_by_symbol = self._slice_refs_by_symbol(selected_slices)
        rank_by_node = {
            str(item["node_id"]): index
            for index, item in enumerate(ranked_targets, start=1)
        }
        chain_support_refs = {
            str(ref)
            for item in selected_flow_chains
            for ref in item.get("supporting_slice_refs", [])
        }
        summary_support_refs = {
            str(ref)
            for item in selected_flow_summaries
            for ref in item.get("supporting_slice_refs", [])
        }
        gap_support_refs = {
            str(ref)
            for item in flow_gaps
            for ref in item.get("supporting_slice_refs", [])
        }

        ordered_refs: List[str] = []

        def append_refs(refs: Iterable[str]) -> None:
            ordered_refs.extend(str(ref) for ref in refs if str(ref))

        def append_path_refs() -> None:
            for path in selected_paths:
                for item in path.get("recommended_slices", []):
                    node_id = str(item.get("anchor_symbol", ""))
                    append_refs(slice_refs_by_symbol.get(node_id, []))

        def append_chain_refs() -> None:
            for item in selected_flow_chains:
                append_refs(item.get("supporting_slice_refs", []))

        def append_summary_refs() -> None:
            for item in selected_flow_summaries:
                append_refs(item.get("supporting_slice_refs", []))

        if primary_target_id:
            append_refs(slice_refs_by_symbol.get(primary_target_id, []))
        if primary_chain:
            append_refs(primary_chain.get("supporting_slice_refs", []))
        if primary_path:
            for item in primary_path.get("recommended_slices", []):
                node_id = str(item.get("anchor_symbol", ""))
                append_refs(slice_refs_by_symbol.get(node_id, []))
        if primary_gap:
            append_refs(primary_gap.get("supporting_slice_refs", []))

        if recommended_outcome_mode in {"partial", "unproven"}:
            append_path_refs()
            append_chain_refs()
            append_summary_refs()
        else:
            append_chain_refs()
            append_summary_refs()
            append_path_refs()
        ordered_refs.extend(self._slice_ref(spec) for spec in selected_slices)

        out: List[Dict[str, object]] = []
        seen: Set[str] = set()
        for ref in ordered_refs:
            ref = str(ref)
            if ref in seen or ref not in slice_by_ref:
                continue
            seen.add(ref)
            spec = slice_by_ref[ref]
            candidate_symbols = [
                str(symbol)
                for symbol in spec.get("symbols", [])
                if str(symbol) in self.nodes
            ]
            candidate_symbols.sort(
                key=lambda node_id: (
                    int(rank_by_node.get(node_id, 999)),
                    0 if self.nodes[node_id].kind in SEMANTIC_EXECUTABLE_KINDS else 1,
                    node_id,
                )
            )
            symbol = candidate_symbols[0] if candidate_symbols else (str(spec.get("symbols", [""])[0]) if spec.get("symbols") else "")
            if ref in gap_support_refs:
                why = "Inspect this slice only to decide whether the remaining flow gap can be closed."
                stop_if = (
                    f"Stop after this slice if `{', '.join(sorted(matched_signals))}` is still not directly evidenced."
                    if matched_signals
                    else "Stop after this slice if the gap remains unresolved."
                )
            elif ref in chain_support_refs:
                why = "Primary graph-guided evidence for the leading flow or path check."
                stop_if = "Stop if this slice, together with the current flow/path, already settles the claim."
            elif ref in summary_support_refs:
                why = "Primary executable slice for the highest-ranked query target."
                stop_if = "Stop if this slice alone answers the query."
            else:
                why = "Lowest-cost supporting context retained by the query-scoped ranking."
                stop_if = "Stop if the current outcome mode can already be chosen without opening lower-priority context."
            out.append(
                {
                    "order": len(out) + 1,
                    "slice_ref": ref,
                    "symbol": symbol,
                    "why": why,
                    "stop_if": stop_if,
                }
            )
            if len(out) >= limit:
                break
        return out

    def _select_primary_flow_chain(
        self,
        primary_target_id: str,
        selected_flow_chains: List[Dict[str, object]],
    ) -> Dict[str, object]:
        if not primary_target_id or not selected_flow_chains:
            return selected_flow_chains[0] if selected_flow_chains else {}

        ranked = sorted(
            enumerate(selected_flow_chains),
            key=lambda item: (
                0 if str(item[1].get("query_anchor", "")) == primary_target_id else (1 if primary_target_id in [str(node_id) for node_id in item[1].get("nodes", [])] else 2),
                ([str(node_id) for node_id in item[1].get("nodes", [])].index(primary_target_id) if primary_target_id in [str(node_id) for node_id in item[1].get("nodes", [])] else 999),
                -FLOW_COMPLETENESS_ORDER.get(str(item[1].get("completeness", "")), 0),
                0 if ([str(node_id) for node_id in item[1].get("nodes", [])][:1] == [primary_target_id]) else (1 if primary_target_id in [str(node_id) for node_id in item[1].get("nodes", [])][:2] else 2),
                item[0],
            ),
        )
        return dict(ranked[0][1]) if ranked else {}

    def _select_primary_evidence_path(
        self,
        primary_target_id: str,
        selected_paths: List[Dict[str, object]],
    ) -> Dict[str, object]:
        if not primary_target_id or not selected_paths:
            return selected_paths[0] if selected_paths else {}

        ranked = sorted(
            enumerate(selected_paths),
            key=lambda item: (
                0 if str(item[1].get("risk_node", "")) == primary_target_id else (1 if primary_target_id in self._ordered_path_nodes(item[1]) else 2),
                (self._ordered_path_nodes(item[1]).index(primary_target_id) if primary_target_id in self._ordered_path_nodes(item[1]) else 999),
                -len(item[1].get("query_match_signals", [])),
                -float(item[1].get("path_confidence", 0.0)),
                -float(item[1].get("query_match_score", 0.0)),
                item[0],
            ),
        )
        return dict(ranked[0][1]) if ranked else {}

    def _select_primary_flow_gap(
        self,
        primary_target_id: str,
        primary_chain: Dict[str, object],
        primary_path: Dict[str, object],
        flow_gaps: List[Dict[str, object]],
    ) -> Dict[str, object]:
        if not flow_gaps:
            return {}

        primary_chain_id = str(primary_chain.get("chain_id", "")) if primary_chain else ""
        primary_path_id = str(primary_path.get("path_id", "")) if primary_path else ""
        ranked = sorted(
            enumerate(flow_gaps),
            key=lambda item: (
                0 if primary_chain_id and str(item[1].get("chain_id", "")) == primary_chain_id else (
                    1 if primary_target_id and str(item[1].get("node_id", "")) == primary_target_id else (
                        2 if primary_path_id and primary_path_id in [str(ref) for ref in item[1].get("supporting_path_refs", [])] else 3
                    )
                ),
                len(item[1].get("missing_step_kinds", [])),
                item[0],
            ),
        )
        return dict(ranked[0][1]) if ranked else {}

    def _build_analysis_plan(
        self,
        query: str,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        selected_slices: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
        selected_flow_summaries: List[Dict[str, object]],
        selected_flow_chains: List[Dict[str, object]],
        flow_gaps: List[Dict[str, object]],
        ambiguity_watchlist: List[Dict[str, object]],
        deferred_requests: List[Dict[str, object]],
    ) -> Dict[str, object]:
        matched_signals = [str(item) for item in analysis.get("matched_semantic_signals", [])]
        recommended_outcome_mode = self._recommended_analysis_outcome_mode(
            analysis,
            selected_flow_summaries,
            selected_flow_chains,
            flow_gaps,
            ambiguity_watchlist,
            selected_paths,
        )
        candidate_outcomes = self._build_analysis_candidate_outcomes(
            query,
            analysis,
            recommended_outcome_mode,
        )
        primary_target = ranked_targets[0] if ranked_targets else {}
        primary_target_id = str(primary_target.get("node_id", "")) if primary_target else ""
        primary_chain = self._select_primary_flow_chain(primary_target_id, selected_flow_chains)
        primary_path = self._select_primary_evidence_path(primary_target_id, selected_paths)
        primary_gap = self._select_primary_flow_gap(primary_target_id, primary_chain, primary_path, flow_gaps)
        minimal_open_sequence = self._build_minimal_open_sequence(
            analysis,
            ranked_targets,
            selected_slices,
            selected_flow_summaries,
            selected_flow_chains,
            selected_paths,
            flow_gaps,
            recommended_outcome_mode,
            primary_target_id=primary_target_id,
            primary_chain=primary_chain,
            primary_path=primary_path,
            primary_gap=primary_gap,
            limit=4,
        )
        ambiguity_item = ambiguity_watchlist[0] if ambiguity_watchlist else {}
        branch_requests = [
            {
                "branch_id": f"branch_{index:02d}",
                "when": "Only open this branch if the current selected slices do not satisfy the active step.",
                "deferred_request_ref": f"ask_deferred_request_{index:02d}",
                "request_kind": str(item.get("request_kind", "")),
                "why": str(item.get("why", "")),
                "targets": list(item.get("targets", []))[:3],
            }
            for index, item in enumerate(deferred_requests[:3], start=1)
        ]

        steps: List[Dict[str, object]] = []

        def add_step(
            step_kind: str,
            question: str,
            target_symbols: List[str],
            target_slice_refs: List[str],
            target_flow_refs: List[str],
            target_path_refs: List[str],
            why_this_step: str,
            expected_evidence: str,
            success_condition: str,
            if_success_next: str,
            if_failure_next: str,
            if_ambiguous_next: str,
            stop_if_answered: bool,
        ) -> str:
            step_id = f"step_{len(steps) + 1:02d}"
            steps.append(
                {
                    "step_id": step_id,
                    "step_kind": step_kind,
                    "question": question,
                    "target_symbols": target_symbols,
                    "target_slice_refs": target_slice_refs,
                    "target_flow_refs": target_flow_refs,
                    "target_path_refs": target_path_refs,
                    "why_this_step": why_this_step,
                    "expected_evidence": expected_evidence,
                    "success_condition": success_condition,
                    "if_success_next": if_success_next,
                    "if_failure_next": if_failure_next,
                    "if_ambiguous_next": if_ambiguous_next,
                    "stop_if_answered": stop_if_answered,
                }
            )
            return step_id

        final_step_kind = f"synthesize_{recommended_outcome_mode}"
        final_step_id = "step_final"

        primary_target_slice_refs = [
            str(item["slice_ref"])
            for item in minimal_open_sequence
            if str(item.get("symbol", "")) == primary_target_id
        ]
        primary_slice_ref = primary_target_slice_refs[0] if primary_target_slice_refs else (minimal_open_sequence[0]["slice_ref"] if minimal_open_sequence else "")
        primary_path_refs: List[str] = []
        if primary_path and primary_path.get("path_id"):
            primary_path_refs.append(str(primary_path["path_id"]))
        primary_path_refs.extend(
            str(item)
            for item in primary_chain.get("supporting_path_refs", [])
            if str(item) not in primary_path_refs
        )

        single_slice_confirmable = bool(
            recommended_outcome_mode == "confirmed"
            and primary_chain
            and str(primary_chain.get("completeness", "")) == "complete"
            and len(primary_chain.get("supporting_slice_refs", [])) <= 1
        )

        followup_step_id = "step_02"
        gap_step_needed = bool(primary_gap)
        ambiguity_step_needed = bool(ambiguity_item)
        if primary_chain and primary_gap:
            followup_step_id = "step_02"
        elif primary_chain or primary_gap or ambiguity_item:
            followup_step_id = "step_02"
        else:
            followup_step_id = final_step_id

        add_step(
            step_kind="inspect_primary_slice",
            question=f"What is the smallest direct evidence inside `{primary_target.get('node_id', '') or query}` for `{query}`?",
            target_symbols=[str(primary_target["node_id"])] if primary_target else [],
            target_slice_refs=[primary_slice_ref] if primary_slice_ref else [],
            target_flow_refs=[],
            target_path_refs=primary_path_refs,
            why_this_step="Start with the highest-ranked executable or query-focused slice before opening support context.",
            expected_evidence=(
                f"Direct evidence for `{', '.join(matched_signals[:4])}`."
                if matched_signals
                else "The main executable step that answers the query."
            ),
            success_condition=(
                "The primary slice already answers the query with direct evidence."
                if single_slice_confirmable
                else "The primary slice reveals the leading control step or the strongest direct evidence."
            ),
            if_success_next=final_step_id if single_slice_confirmable else followup_step_id,
            if_failure_next=followup_step_id,
            if_ambiguous_next="step_03" if ambiguity_step_needed and (primary_chain or primary_gap) else (followup_step_id if ambiguity_step_needed else followup_step_id),
            stop_if_answered=True,
        )

        if primary_chain:
            chain_kind = "confirm_flow_chain"
            if matched_signals and {"auth_guard"} & set(matched_signals) and (set(matched_signals) & (SEMANTIC_EXTERNAL_IO_SIGNALS | {"database_io"})):
                chain_kind = "confirm_guard_before_side_effect"
            elif not primary_chain.get("stitched_step_kinds"):
                chain_kind = "inspect_path_transition"
            elif str(primary_chain.get("completeness", "")) != "complete":
                chain_kind = "inspect_flow_gap"
            chain_success_next = (
                final_step_id
                if str(primary_chain.get("completeness", "")) == "complete" and recommended_outcome_mode == "confirmed"
                else ("step_03" if primary_gap else final_step_id)
            )
            add_step(
                step_kind=chain_kind,
                question=(
                    f"Does `{primary_chain.get('chain_id', '')}` provide the ordered evidence needed for `{query}`?"
                ),
                target_symbols=[str(item) for item in primary_chain.get("nodes", [])[:4]],
                target_slice_refs=[str(item) for item in primary_chain.get("supporting_slice_refs", [])[:4]],
                target_flow_refs=[str(primary_chain.get("chain_id", ""))],
                target_path_refs=primary_path_refs[:2],
                why_this_step="Use the strongest selected flow/path after the primary slice to confirm ordering or expose the remaining gap.",
                expected_evidence=(
                    f"An ordered chain covering `{', '.join(matched_signals[:4])}`."
                    if matched_signals
                    else "An ordered structural chain that resolves the query."
                ),
                success_condition=(
                    "The selected chain covers every query-matched signal in order."
                    if str(primary_chain.get("completeness", "")) == "complete"
                    else "The chain clarifies the last supported transition and exposes what is still missing."
                ),
                if_success_next=chain_success_next,
                if_failure_next="step_03" if primary_gap else final_step_id,
                if_ambiguous_next="step_03" if ambiguity_step_needed or primary_gap else final_step_id,
                stop_if_answered=True,
            )

        if primary_gap:
            gap_slice_refs = [str(item) for item in primary_gap.get("supporting_slice_refs", [])[:4]]
            gap_path_refs = [str(item) for item in primary_gap.get("supporting_path_refs", [])[:2]]
            add_step(
                step_kind="inspect_flow_gap",
                question="What direct evidence is still missing after the currently selected structural path?",
                target_symbols=[str(primary_target["node_id"])] if primary_target else [],
                target_slice_refs=gap_slice_refs,
                target_flow_refs=[str(primary_gap.get("chain_id", ""))] if primary_gap.get("chain_id") else [],
                target_path_refs=gap_path_refs,
                why_this_step="Inspect the smallest unresolved gap before requesting more code.",
                expected_evidence=(
                    f"Either a direct `{', '.join(str(item) for item in primary_gap.get('missing_step_kinds', [])[:4])}` span or confirmation that it is absent."
                ),
                success_condition="The missing signal is either directly evidenced or remains absent after the referenced slices are checked.",
                if_success_next=final_step_id,
                if_failure_next=(branch_requests[0]["branch_id"] if branch_requests else final_step_id),
                if_ambiguous_next="step_04" if ambiguity_step_needed and primary_chain else final_step_id,
                stop_if_answered=True,
            )

        if ambiguity_item:
            add_step(
                step_kind="resolve_ambiguity",
                question=f"Does the current evidence resolve the ambiguity around `{ambiguity_item.get('source_node', '')}`?",
                target_symbols=[str(ambiguity_item.get("source_node", ""))],
                target_slice_refs=[str(item) for item in ambiguity_item.get("supporting_slice_refs", [])[:3]],
                target_flow_refs=[],
                target_path_refs=[],
                why_this_step="Ambiguity must be resolved explicitly before a confirmed answer is allowed.",
                expected_evidence="A single supported candidate or a clear reason to keep the result ambiguous.",
                success_condition="Either one candidate clearly wins or the ambiguity remains explicit.",
                if_success_next=final_step_id,
                if_failure_next=(branch_requests[0]["branch_id"] if branch_requests else final_step_id),
                if_ambiguous_next=final_step_id,
                stop_if_answered=True,
            )

        final_target_slice_refs = [str(item["slice_ref"]) for item in minimal_open_sequence[:3]]
        final_target_flow_refs: List[str] = []
        if primary_chain and primary_chain.get("chain_id"):
            final_target_flow_refs.append(str(primary_chain["chain_id"]))
        if primary_gap and primary_gap.get("chain_id") and str(primary_gap["chain_id"]) not in final_target_flow_refs:
            final_target_flow_refs.append(str(primary_gap["chain_id"]))
        final_target_path_refs: List[str] = []
        if primary_path and primary_path.get("path_id"):
            final_target_path_refs.append(str(primary_path["path_id"]))
        for ref in primary_chain.get("supporting_path_refs", []):
            ref = str(ref)
            if ref and ref not in final_target_path_refs:
                final_target_path_refs.append(ref)
        for ref in primary_gap.get("supporting_path_refs", []):
            ref = str(ref)
            if ref and ref not in final_target_path_refs:
                final_target_path_refs.append(ref)
        steps.append(
            {
                "step_id": final_step_id,
                "step_kind": final_step_kind,
                "question": f"Which conservative outcome mode is justified for `{query}` now?",
                "target_symbols": [str(primary_target["node_id"])] if primary_target else [],
                "target_slice_refs": final_target_slice_refs,
                "target_flow_refs": final_target_flow_refs,
                "target_path_refs": final_target_path_refs,
                "why_this_step": "Finish with the smallest allowed claim and stop early once it is justified.",
                "expected_evidence": f"Only the evidence required by `{recommended_outcome_mode}`.",
                "success_condition": f"The evidence satisfies the `{recommended_outcome_mode}` candidate_outcome without overreach.",
                "if_success_next": "stop",
                "if_failure_next": "stop",
                "if_ambiguous_next": "stop",
                "stop_if_answered": True,
            }
        )

        decision_points: List[Dict[str, object]] = []
        for step in steps[:-1]:
            if step.get("if_success_next") and step["if_success_next"] != "stop":
                decision_points.append(
                    {
                        "decision_id": f"decision_{len(decision_points) + 1:02d}",
                        "based_on_step": str(step["step_id"]),
                        "condition": str(step["success_condition"]),
                        "next_step": str(step["if_success_next"]),
                    }
                )
            if step.get("if_failure_next") and str(step["if_failure_next"]).startswith("branch_"):
                branch = next((item for item in branch_requests if item["branch_id"] == step["if_failure_next"]), None)
                decision_points.append(
                    {
                        "decision_id": f"decision_{len(decision_points) + 1:02d}",
                        "based_on_step": str(step["step_id"]),
                        "condition": "The selected slices still do not satisfy the step success_condition.",
                        "next_step": str(final_step_id),
                        "deferred_request_ref": str(branch.get("deferred_request_ref", "")) if branch else "",
                    }
                )
            elif step.get("if_failure_next") and step["if_failure_next"] != "stop":
                decision_points.append(
                    {
                        "decision_id": f"decision_{len(decision_points) + 1:02d}",
                        "based_on_step": str(step["step_id"]),
                        "condition": "The current slice or chain does not yet answer the query fully.",
                        "next_step": str(step["if_failure_next"]),
                    }
                )

        stop_conditions = [
            {
                "outcome_mode": "confirmed",
                "condition": "Stop when a selected slice or complete flow chain covers all query-matched signals directly.",
            },
            {
                "outcome_mode": "partial",
                "condition": "Stop when part of the claim is directly evidenced but a flow gap or missing transition remains.",
            },
            {
                "outcome_mode": "unproven",
                "condition": "Stop when the selected slices and paths stay under-evidenced and the missing signal never appears directly.",
            },
            {
                "outcome_mode": "ambiguous",
                "condition": "Stop when competing candidates remain unresolved and the evidence cannot break the tie conservatively.",
            },
        ]

        return {
            "task": query,
            "overall_goal": self._analysis_overall_goal(query, analysis),
            "recommended_outcome_mode": recommended_outcome_mode,
            "steps": steps,
            "decision_points": decision_points,
            "stop_conditions": stop_conditions,
            "minimal_open_sequence": minimal_open_sequence,
            "candidate_outcomes": candidate_outcomes,
            "branch_requests": branch_requests,
        }

    def _node_brief_label(self, node_id: str) -> str:
        node = self.nodes.get(node_id)
        if node is None:
            return node_id
        if node.qualname:
            return node.qualname
        return self._flow_node_label(node_id)

    def _semantic_ref_id(self, ref: Dict[str, object]) -> str:
        lines = list(ref.get("lines", []))
        start = int(lines[0]) if lines else 0
        end = int(lines[1]) if len(lines) > 1 else start
        return f"{ref.get('file', '')}:{start}-{end}:{ref.get('signal', '')}"

    def _semantic_ref_payload(self, ref: Dict[str, object]) -> Dict[str, object]:
        lines = list(ref.get("lines", []))
        start = int(lines[0]) if lines else 0
        end = int(lines[1]) if len(lines) > 1 else start
        return {
            "ref_id": self._semantic_ref_id(ref),
            "file": str(ref.get("file", "")),
            "lines": [start, end],
            "signal": str(ref.get("signal", "")),
            "reason": str(ref.get("reason", "")),
        }

    def _flow_gap_ref(self, gap: Dict[str, object]) -> str:
        missing = ",".join(sorted(str(item) for item in gap.get("missing_step_kinds", []) if item))
        if gap.get("chain_id"):
            base = f"chain::{gap['chain_id']}"
        elif gap.get("node_id"):
            base = f"node::{gap['node_id']}"
        else:
            base = "gap::unknown"
        return f"{base}::{missing}" if missing else base

    def _ambiguity_ref(self, item: Dict[str, object]) -> str:
        return f"{item.get('source_node', '')}:{item.get('raw_call', '')}"

    def _analysis_result_behavior_phrase(
        self,
        signals: Iterable[str],
        analysis: Dict[str, object],
        primary_path: Optional[Dict[str, object]] = None,
    ) -> str:
        ordered_signals = self._sort_semantic_signals(str(item) for item in signals if item)
        signal_set = set(ordered_signals)
        query_tokens = {str(item).lower() for item in analysis.get("query_tokens", [])}
        path_labels = [
            self._node_brief_label(node_id).lower()
            for node_id in self._ordered_path_nodes(primary_path or {})
            if node_id in self.nodes
        ]
        if {"auth_guard", "database_io"} <= signal_set:
            if any("repository" in label for label in path_labels):
                db_phrase = "the repository read"
            elif "read" in query_tokens:
                db_phrase = "the database read"
            else:
                db_phrase = "database access"
            return f"auth enforced before {db_phrase}"
        if {"state_mutation", "filesystem_io"} <= signal_set:
            if {"write", "disk", "file"} & query_tokens:
                return "state mutation and a disk write"
            return "state mutation and filesystem I/O"
        phrase_map = {
            "auth_guard": "auth enforcement",
            "validation_guard": "validation",
            "state_mutation": "state mutation",
            "config_access": "config access",
            "deserialization": "deserialization",
            "serialization": "serialization",
            "database_io": "database I/O",
            "network_io": "network I/O",
            "filesystem_io": "filesystem I/O",
            "process_io": "process I/O",
            "input_boundary": "input handling",
            "output_boundary": "output handling",
            "error_handling": "error handling",
            "time_or_randomness": "time or randomness",
            "external_io": "external I/O",
        }
        phrases = [phrase_map.get(signal, signal.replace("_", " ")) for signal in ordered_signals]
        if not phrases:
            return "the requested behavior"
        if len(phrases) == 1:
            return phrases[0]
        if len(phrases) == 2:
            return f"{phrases[0]} and {phrases[1]}"
        return ", ".join(phrases[:-1]) + f", and {phrases[-1]}"

    def _analysis_result_context_phrase(
        self,
        primary_target_id: str,
        primary_path: Dict[str, object],
        primary_chain: Dict[str, object],
    ) -> str:
        node_ids: List[str] = []
        if primary_path:
            node_ids = [node_id for node_id in self._ordered_path_nodes(primary_path) if node_id != primary_target_id]
        elif primary_chain:
            node_ids = [
                str(node_id)
                for node_id in primary_chain.get("nodes", [])
                if str(node_id) and str(node_id) != primary_target_id
            ]
        labels = [self._flow_node_label(node_id) for node_id in node_ids if node_id in self.nodes]
        fetch_like = [label for label in labels if "fetch" in label.lower()]
        if fetch_like:
            return "internal fetch-related calls"
        if not labels:
            return "the selected structural context"
        unique_labels: List[str] = []
        for label in labels:
            if label not in unique_labels:
                unique_labels.append(label)
        if len(unique_labels) == 1:
            return f"internal `{unique_labels[0]}` calls"
        joined = " -> ".join(unique_labels[:3])
        return joined if len(unique_labels) <= 3 else f"{joined} context"

    def _analysis_result_confidence_posture(
        self,
        outcome_mode: str,
        primary_summary: Dict[str, object],
        primary_chain: Dict[str, object],
    ) -> str:
        if outcome_mode == "confirmed":
            if primary_chain and str(primary_chain.get("completeness", "")) == "complete":
                return "complete_flow_evidence"
            if primary_summary and str(primary_summary.get("completeness", "")) == "complete":
                return "direct_executable_evidence"
            return "bounded_confirmed_evidence"
        if outcome_mode == "partial":
            return "bounded_partial_evidence"
        if outcome_mode == "ambiguous":
            return "ambiguity_blocks_unique_answer"
        return "no_direct_evidence_for_requested_behavior"

    def _analysis_result_forbidden_overreach(
        self,
        outcome_mode: str,
        analysis: Dict[str, object],
        primary_target_id: str,
        flow_gap_refs: List[str],
        ambiguity_refs: List[str],
    ) -> Dict[str, object]:
        symbol_label = self._node_brief_label(primary_target_id) if primary_target_id else "the selected symbol"
        unsupported: List[str] = ["project_wide_claim", "root_cause_claim"]
        statements = [
            f"Do not widen `{symbol_label}` into a project-wide claim.",
            "Do not infer root cause or hidden intent from structural evidence alone.",
        ]
        matched_signals = {str(item) for item in analysis.get("matched_semantic_signals", [])}
        if outcome_mode != "confirmed" or flow_gap_refs:
            unsupported.append("complete_flow_claim")
            statements.append("Do not upgrade a partial or missing chain into a complete flow claim.")
        if "network_io" in matched_signals and outcome_mode != "confirmed":
            unsupported.append("end_to_end_claim_without_direct_io")
            statements.append("Do not claim end-to-end network I/O without a direct network evidence span.")
        if ambiguity_refs:
            unsupported.append("uniqueness_claim_without_disambiguation")
            statements.append("Do not claim a unique implementation or path while ambiguity remains unresolved.")
        return {
            "unsupported_claim_kinds": sorted(set(unsupported)),
            "statements": list(dict.fromkeys(statements)),
        }

    def _select_next_best_request(
        self,
        outcome_mode: str,
        primary_target_id: str,
        primary_gap: Dict[str, object],
        ambiguity_item: Dict[str, object],
        deferred_requests: List[Dict[str, object]],
    ) -> Optional[Dict[str, object]]:
        if outcome_mode == "confirmed" or not deferred_requests:
            return None
        primary_gap_refs = {str(item) for item in primary_gap.get("supporting_path_refs", [])}
        ranked = sorted(
            deferred_requests,
            key=lambda item: (
                -(
                    (12 if ambiguity_item and str(item.get("type", "")) == "ambiguity_followup" and str(item.get("symbol", "")) == str(ambiguity_item.get("source_node", "")) else 0)
                    + (10 if primary_target_id and str(item.get("symbol", "")) == primary_target_id else 0)
                    + (4 if primary_gap_refs and any(str(target.get("anchor_symbol", "")) == primary_target_id for target in item.get("targets", [])) else 0)
                ),
                str(item.get("type", "")),
                str(item.get("symbol", "")),
                str(item.get("request", "")),
            ),
        )
        return dict(ranked[0]) if ranked else None

    def _build_analysis_result_claim(
        self,
        outcome_mode: str,
        symbol_label: str,
        behavior_phrase: str,
        requested_phrase: str,
        context_phrase: str,
        decisive_signals: List[str],
        ambiguity_item: Dict[str, object],
    ) -> Tuple[str, str]:
        if outcome_mode == "confirmed":
            if {"auth_guard", "database_io"} <= set(decisive_signals):
                claim = f"Auth is enforced in {symbol_label} before the repository read." if "repository read" in behavior_phrase else f"Auth is enforced in {symbol_label} before the database read."
                claim_short = f"Confirmed auth-before-read in {symbol_label}."
            elif {"state_mutation", "filesystem_io"} <= set(decisive_signals):
                claim = f"{symbol_label} performs state mutation and writes to disk."
                claim_short = f"{symbol_label} mutates state and writes to disk."
            else:
                claim = f"{symbol_label} directly evidences {behavior_phrase}."
                claim_short = f"Confirmed in {symbol_label}: {behavior_phrase}."
        elif outcome_mode == "partial":
            claim = f"The selected evidence shows {symbol_label} covering {behavior_phrase}, but not the full requested behavior."
            claim_short = f"Partial evidence in {symbol_label}."
        elif outcome_mode == "ambiguous":
            candidates = [
                self._node_brief_label(str(item))
                for item in ambiguity_item.get("candidates", [])
                if str(item) in self.nodes
            ]
            candidate_text = ", ".join(candidates[:3]) if candidates else "multiple candidates"
            raw_call = str(ambiguity_item.get("raw_call", "the selected call"))
            claim = f"The selected evidence keeps `{raw_call}` in {symbol_label} ambiguous between {candidate_text}."
            claim_short = f"Ambiguous in {symbol_label}: {raw_call}."
        else:
            claim = f"The selected context shows {symbol_label} reaching {context_phrase}, but no direct {requested_phrase} evidence."
            claim_short = f"No direct {requested_phrase} evidence for {symbol_label}."
        return claim, claim_short

    def _build_analysis_result_metadata(
        self,
        outcome_mode: str,
        missing_signals: List[str],
        primary_gap: Dict[str, object],
        ambiguity_item: Dict[str, object],
        flow_gap_refs: List[str],
        ambiguity_refs: List[str],
        primary_chain: Dict[str, object],
        primary_summary: Dict[str, object],
        decisive_signals: List[str],
        primary_target_id: str,
        supporting_slice_refs: List[str],
        supporting_flow_refs: List[str],
        supporting_path_refs: List[str],
        semantic_refs: List[Dict[str, object]],
    ) -> Tuple[List[Dict[str, object]], Dict[str, object], List[str], List[str]]:
        missing_evidence: List[Dict[str, object]] = []
        if outcome_mode in {"partial", "unproven"} and missing_signals:
            missing_evidence.append(
                {
                    "kind": "missing_signal",
                    "signals": list(missing_signals),
                    "reason": "No selected direct semantic span covers these query-matched signals.",
                }
            )
        if primary_gap:
            missing_evidence.append(
                {
                    "kind": str(primary_gap.get("gap_kind", "flow_gap")),
                    "gap_ref": flow_gap_refs[0],
                    "signals": list(primary_gap.get("missing_step_kinds", [])),
                    "reason": str(primary_gap.get("reason", "")),
                }
            )
        if ambiguity_item:
            missing_evidence.append(
                {
                    "kind": "ambiguity",
                    "ambiguity_ref": ambiguity_refs[0],
                    "candidates": list(ambiguity_item.get("candidates", [])),
                    "reason": str(ambiguity_item.get("resolution_reason", "")),
                }
            )

        if outcome_mode == "ambiguous":
            decisive_outcome_rule = "ambiguity_watchlist_blocks_unique_answer"
        elif primary_chain and str(primary_chain.get("completeness", "")) == "complete":
            decisive_outcome_rule = "complete_flow_chain_covers_all_query_signals"
        elif primary_summary and str(primary_summary.get("completeness", "")) == "complete":
            decisive_outcome_rule = "single_executable_flow_covers_all_query_signals"
        elif outcome_mode == "partial" and primary_gap:
            decisive_outcome_rule = "direct_evidence_exists_but_flow_gap_remains"
        elif supporting_path_refs or primary_gap:
            decisive_outcome_rule = "selected_context_lacks_direct_query_signal"
        else:
            decisive_outcome_rule = "selected_evidence_does_not_justify_broader_claim"

        minimal_basis = {
            "primary_symbol": primary_target_id,
            "decisive_slice_refs": list(supporting_slice_refs[:3]),
            "decisive_flow_refs": list(supporting_flow_refs[:2]),
            "decisive_path_refs": list(supporting_path_refs[:2]),
            "decisive_semantic_signals": list(decisive_signals[:6]),
            "decisive_outcome_rule": decisive_outcome_rule,
        }

        evidence_refs = list(
            dict.fromkeys(
                list(supporting_slice_refs)
                + list(supporting_flow_refs)
                + list(supporting_path_refs)
                + [item["ref_id"] for item in semantic_refs]
                + flow_gap_refs
                + ambiguity_refs
            )
        )
        result_reasoning_notes = [
            f"Outcome follows `analysis_plan.recommended_outcome_mode = {outcome_mode}`.",
            "Direct executable evidence outranks context-only structure.",
        ]
        if outcome_mode == "confirmed":
            result_reasoning_notes.append("A selected complete executable flow or chain covers the required query signals.")
        elif outcome_mode == "partial":
            result_reasoning_notes.append("At least one required signal is directly evidenced, but the requested behavior remains incomplete.")
        elif outcome_mode == "ambiguous":
            result_reasoning_notes.append("Competing candidates remain unresolved, so uniqueness is not allowed.")
        else:
            result_reasoning_notes.append("Selected paths stay structural or contextual while the requested direct signal remains absent.")

        return missing_evidence, minimal_basis, evidence_refs, result_reasoning_notes

    def _build_analysis_result(
        self,
        query: str,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        selected_slices: List[Dict[str, object]],
        selected_semantic_refs: List[Dict[str, object]],
        selected_flow_summaries: List[Dict[str, object]],
        selected_flow_chains: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
        flow_gaps: List[Dict[str, object]],
        ambiguity_watchlist: List[Dict[str, object]],
        deferred_requests: List[Dict[str, object]],
        analysis_plan: Dict[str, object],
    ) -> Dict[str, object]:
        outcome_mode = str(analysis_plan.get("recommended_outcome_mode", "unproven") or "unproven")
        primary_target = ranked_targets[0] if ranked_targets else {}
        primary_target_id = str(primary_target.get("node_id", "")) if primary_target else ""
        primary_chain = self._select_primary_flow_chain(primary_target_id, selected_flow_chains)
        primary_path = self._select_primary_evidence_path(primary_target_id, selected_paths)
        primary_gap = self._select_primary_flow_gap(primary_target_id, primary_chain, primary_path, flow_gaps)
        primary_summary = next(
            (item for item in selected_flow_summaries if str(item.get("node_id", "")) == primary_target_id),
            {},
        )
        ambiguity_item = next(
            (
                item
                for item in ambiguity_watchlist
                if str(item.get("source_node", "")) == primary_target_id
            ),
            ambiguity_watchlist[0] if ambiguity_watchlist else {},
        )
        matched_signals = {str(item) for item in analysis.get("matched_semantic_signals", [])}
        requested_signals = self._sort_semantic_signals(matched_signals)
        summary_signals = {
            str(item)
            for item in primary_summary.get("ordered_step_kinds", [])
            if str(item) in matched_signals
        }
        chain_signals = {
            str(item)
            for item in primary_chain.get("stitched_step_kinds", [])
            if str(item) in matched_signals
        }
        primary_related_nodes = {primary_target_id}
        primary_related_nodes.update(self._ordered_path_nodes(primary_path))
        primary_related_nodes.update(str(item) for item in primary_chain.get("nodes", []))
        semantic_refs = [
            self._semantic_ref_payload(item)
            for item in selected_semantic_refs
            if str(item.get("node_id", "")) in primary_related_nodes
            and (not matched_signals or str(item.get("signal", "")) in matched_signals)
        ]
        if not semantic_refs and primary_target_id in self.nodes:
            semantic_refs = [
                self._semantic_ref_payload(item)
                for item in self._query_relevant_semantic_refs(
                    list(self.nodes[primary_target_id].semantic_evidence_spans),
                    matched_signals,
                    limit=4,
                )
            ]
        semantic_refs = self._dedupe_object_list(semantic_refs)[:4]
        semantic_ref_signals = {
            str(item.get("signal", ""))
            for item in semantic_refs
            if str(item.get("signal", "")) in matched_signals
        }
        decisive_signals = self._sort_semantic_signals(summary_signals | chain_signals | semantic_ref_signals)
        missing_signals = self._sort_semantic_signals(matched_signals - set(decisive_signals))
        minimal_open_sequence = list(analysis_plan.get("minimal_open_sequence", []))
        primary_slice_refs = [
            str(item["slice_ref"])
            for item in minimal_open_sequence
            if str(item.get("symbol", "")) == primary_target_id
        ]
        if not primary_slice_refs and minimal_open_sequence:
            primary_slice_refs = [str(minimal_open_sequence[0]["slice_ref"])]
        supporting_slice_refs: List[str] = []
        for ref in primary_slice_refs:
            if ref and ref not in supporting_slice_refs:
                supporting_slice_refs.append(ref)
        for ref in primary_chain.get("supporting_slice_refs", []):
            ref = str(ref)
            if ref and ref not in supporting_slice_refs:
                supporting_slice_refs.append(ref)
        for ref in primary_gap.get("supporting_slice_refs", []):
            ref = str(ref)
            if ref and ref not in supporting_slice_refs:
                supporting_slice_refs.append(ref)
        supporting_slice_refs = supporting_slice_refs[:4]

        supporting_flow_refs: List[str] = []
        if primary_chain and primary_chain.get("chain_id"):
            supporting_flow_refs.append(str(primary_chain["chain_id"]))
        if primary_gap and primary_gap.get("chain_id") and str(primary_gap["chain_id"]) not in supporting_flow_refs:
            supporting_flow_refs.append(str(primary_gap["chain_id"]))

        supporting_path_refs: List[str] = []
        if primary_path and primary_path.get("path_id"):
            supporting_path_refs.append(str(primary_path["path_id"]))
        for ref in primary_chain.get("supporting_path_refs", []):
            ref = str(ref)
            if ref and ref not in supporting_path_refs:
                supporting_path_refs.append(ref)
        for ref in primary_gap.get("supporting_path_refs", []):
            ref = str(ref)
            if ref and ref not in supporting_path_refs:
                supporting_path_refs.append(ref)

        flow_gap_refs = [self._flow_gap_ref(primary_gap)] if primary_gap else []
        ambiguity_refs = [self._ambiguity_ref(ambiguity_item)] if ambiguity_item else []
        forbidden_overreach = self._analysis_result_forbidden_overreach(
            outcome_mode,
            analysis,
            primary_target_id,
            flow_gap_refs,
            ambiguity_refs,
        )
        next_best_request = self._select_next_best_request(
            outcome_mode,
            primary_target_id,
            primary_gap,
            ambiguity_item,
            deferred_requests,
        )
        symbol_label = self._node_brief_label(primary_target_id) if primary_target_id else "the selected symbol"
        behavior_phrase = self._analysis_result_behavior_phrase(decisive_signals, analysis, primary_path)
        requested_phrase = self._analysis_result_behavior_phrase(missing_signals or matched_signals, analysis, primary_path)
        context_phrase = self._analysis_result_context_phrase(primary_target_id, primary_path, primary_chain)

        claim, claim_short = self._build_analysis_result_claim(
            outcome_mode,
            symbol_label,
            behavior_phrase,
            requested_phrase,
            context_phrase,
            decisive_signals,
            ambiguity_item,
        )

        missing_evidence, minimal_basis, evidence_refs, result_reasoning_notes = (
            self._build_analysis_result_metadata(
                outcome_mode,
                missing_signals,
                primary_gap,
                ambiguity_item,
                flow_gap_refs,
                ambiguity_refs,
                primary_chain,
                primary_summary,
                decisive_signals,
                primary_target_id,
                supporting_slice_refs,
                supporting_flow_refs,
                supporting_path_refs,
                semantic_refs,
            )
        )

        return {
            "outcome_mode": outcome_mode,
            "claim": claim,
            "claim_short": claim_short,
            "confidence_posture": self._analysis_result_confidence_posture(outcome_mode, primary_summary, primary_chain),
            "requested_semantic_signals": requested_signals,
            "evidence_refs": evidence_refs[:12],
            "supporting_slice_refs": supporting_slice_refs,
            "supporting_flow_refs": supporting_flow_refs,
            "supporting_path_refs": supporting_path_refs,
            "supporting_semantic_refs": semantic_refs,
            "flow_gap_refs": flow_gap_refs,
            "ambiguity_refs": ambiguity_refs,
            "minimal_basis": minimal_basis,
            "missing_evidence": missing_evidence,
            "forbidden_overreach": forbidden_overreach,
            "next_best_request": next_best_request,
            "result_reasoning_notes": result_reasoning_notes,
            "outcome_explanation": {
                "one_sentence": claim_short,
                "evidence_sentence": (
                    f"Key evidence: {', '.join(evidence_refs[:3])}."
                    if evidence_refs
                    else "Key evidence: no decisive reference was selected."
                ),
                "limitation_sentence": forbidden_overreach["statements"][0] if forbidden_overreach["statements"] else "Do not go beyond the selected evidence.",
            },
        }

    def _outcome_mode_rank(self, outcome_mode: str) -> int:
        return OUTCOME_MODE_ORDER.get(outcome_mode, -1)

    def _outcome_upgrade_label(self, current_outcome: str, target_outcome: str) -> str:
        if not target_outcome or target_outcome == current_outcome:
            return "none"
        return f"{current_outcome} -> {target_outcome}"

    def _request_signature(self, request: Dict[str, object]) -> str:
        return json.dumps(request, sort_keys=True)

    def _escalation_target_symbols(self, request: Dict[str, object]) -> List[str]:
        symbols: List[str] = []
        primary_symbol = str(request.get("symbol", ""))
        if primary_symbol:
            symbols.append(primary_symbol)
        for candidate in request.get("candidates", []):
            candidate = str(candidate)
            if candidate and candidate not in symbols:
                symbols.append(candidate)
        for target in request.get("targets", []):
            anchor_symbol = str(target.get("anchor_symbol", ""))
            if anchor_symbol and anchor_symbol not in symbols:
                symbols.append(anchor_symbol)
        return symbols[:4]

    def _escalation_target_slice_candidates(self, request: Dict[str, object]) -> List[Dict[str, object]]:
        candidates: List[Dict[str, object]] = []
        seen: Set[Tuple[str, int, int, str, str]] = set()
        for target in request.get("targets", []):
            file_name = str(target.get("file", ""))
            lines = list(target.get("lines", []))
            if not file_name or not lines:
                continue
            start = int(lines[0])
            end = int(lines[1]) if len(lines) > 1 else start
            anchor_symbol = str(target.get("anchor_symbol", ""))
            signal = str(target.get("signal", ""))
            key = (file_name, start, end, anchor_symbol, signal)
            if key in seen:
                continue
            seen.add(key)
            payload: Dict[str, object] = {
                "file": file_name,
                "lines": [start, end],
            }
            if anchor_symbol:
                payload["anchor_symbol"] = anchor_symbol
            if signal:
                payload["signal"] = signal
            if target.get("why"):
                payload["why"] = str(target.get("why", ""))
            candidates.append(payload)
        return candidates[:3]

    def _escalation_cost_payload(self, target_slice_candidates: List[Dict[str, object]]) -> Dict[str, object]:
        unique_files = {str(item.get("file", "")) for item in target_slice_candidates if item.get("file")}
        additional_line_span = sum(
            max(1, int(item["lines"][1]) - int(item["lines"][0]) + 1)
            for item in target_slice_candidates
            if item.get("lines")
        )
        target_count = len(target_slice_candidates)
        if target_count <= 1 and additional_line_span <= 8 and len(unique_files) <= 1:
            label = "low"
        elif target_count <= 2 and additional_line_span <= 24 and len(unique_files) <= 2:
            label = "medium"
        else:
            label = "high"
        return {
            "label": label,
            "additional_target_count": target_count,
            "additional_file_count": len(unique_files),
            "additional_line_span": additional_line_span,
        }

    def _derive_synthetic_ambiguity_request(
        self,
        ambiguity_item: Dict[str, object],
        selected_slices: List[Dict[str, object]],
    ) -> Optional[Dict[str, object]]:
        if not ambiguity_item:
            return None
        next_target = ambiguity_item.get("recommended_next_evidence_target", {})
        raw_targets = list(next_target.get("targets", [])) if isinstance(next_target, dict) else []
        targets: List[Dict[str, object]] = []
        for target in raw_targets:
            file_name = str(target.get("file", ""))
            lines = list(target.get("lines", []))
            if not file_name or not lines:
                continue
            if self._slice_covers_lines(selected_slices, file_name, lines):
                continue
            targets.append(
                {
                    "file": file_name,
                    "lines": lines,
                    "why": str(target.get("why", "")),
                }
            )
        if not targets:
            return None
        return {
            "type": "ambiguity_followup",
            "symbol": str(ambiguity_item.get("source_node", "")),
            "raw_call": str(ambiguity_item.get("raw_call", "")),
            "candidates": list(ambiguity_item.get("candidates", [])),
            "request": (
                f"Open only the caller and smallest candidate slices for `{ambiguity_item.get('raw_call', '')}` "
                "to resolve the remaining ambiguity."
            ),
            "targets": targets[:3],
            "why": str(ambiguity_item.get("resolution_reason", "")),
        }

    def _derive_synthetic_semantic_gap_request(
        self,
        primary_target_id: str,
        primary_path: Dict[str, object],
        primary_chain: Dict[str, object],
        missing_signals: List[str],
        selected_slices: List[Dict[str, object]],
    ) -> Optional[Dict[str, object]]:
        if not primary_target_id or not missing_signals:
            return None
        ordered_nodes: List[str] = [primary_target_id]
        for node_id in self._ordered_path_nodes(primary_path):
            if node_id and node_id not in ordered_nodes:
                ordered_nodes.append(node_id)
        for node_id in primary_chain.get("nodes", []):
            node_id = str(node_id)
            if node_id and node_id not in ordered_nodes:
                ordered_nodes.append(node_id)
        candidate_refs: List[Tuple[int, int, str, str, str, Dict[str, object]]] = []
        missing_signal_set = set(str(item) for item in missing_signals)
        for index, node_id in enumerate(ordered_nodes):
            node = self.nodes.get(node_id)
            if node is None:
                continue
            for ref in node.semantic_evidence_spans:
                signal = str(ref.get("signal", ""))
                if signal not in missing_signal_set:
                    continue
                file_name = str(ref.get("file", ""))
                lines = list(ref.get("lines", []))
                if not file_name or not lines:
                    continue
                if self._slice_covers_lines(selected_slices, file_name, lines):
                    continue
                span = max(1, int(lines[1]) - int(lines[0]) + 1)
                candidate_refs.append((index, span, file_name, signal, node_id, ref))
        candidate_refs.sort(
            key=lambda item: (
                item[0],
                item[1],
                item[2],
                item[3],
                item[4],
            )
        )
        if not candidate_refs:
            return None
        _, _, _, signal, node_id, ref = candidate_refs[0]
        return {
            "type": "semantic_followup",
            "symbol": node_id,
            "signals": [signal],
            "request": (
                f"Open only `{ref['file']}:{ref['lines'][0]}-{ref['lines'][1]}` "
                f"to validate the missing `{signal}` evidence."
            ),
            "targets": [
                {
                    "file": str(ref["file"]),
                    "lines": list(ref["lines"]),
                    "anchor_symbol": node_id,
                    "signal": signal,
                    "why": str(ref.get("reason", "")),
                }
            ],
            "why": f"Potential direct evidence for the missing query signal `{signal}` on the primary evidence path.",
        }

    def _build_escalation_option(
        self,
        option_id: str,
        source: str,
        request_ref: str,
        request: Dict[str, object],
        current_outcome: str,
        analysis_result: Dict[str, object],
        primary_gap: Dict[str, object],
        ambiguity_item: Dict[str, object],
    ) -> Dict[str, object]:
        requested_signals = {str(item) for item in analysis_result.get("requested_semantic_signals", [])}
        missing_signals = {
            str(signal)
            for item in analysis_result.get("missing_evidence", [])
            if str(item.get("kind", "")) == "missing_signal"
            for signal in item.get("signals", [])
        }
        target_slice_candidates = self._escalation_target_slice_candidates(request)
        target_symbols = self._escalation_target_symbols(request)
        request_type = str(request.get("type", ""))
        signal_gain = {
            str(item)
            for item in request.get("signals", [])
            if str(item) in requested_signals
        }
        for target in target_slice_candidates:
            signal = str(target.get("signal", ""))
            if signal in requested_signals:
                signal_gain.add(signal)

        expected_evidence_gain: List[str] = []
        if signal_gain:
            expected_evidence_gain.append("direct_semantic_evidence")
        if request_type == "ambiguity_followup" or source == "ambiguity_watchlist":
            expected_evidence_gain.append("candidate_disambiguation")
        if primary_gap and set(str(item) for item in primary_gap.get("missing_step_kinds", [])) & signal_gain:
            expected_evidence_gain.append("close_flow_gap")
        elif request_type == "focused_symbol_followup":
            expected_evidence_gain.append("path_transition_validation")

        path_gain_refs = list(analysis_result.get("supporting_path_refs", []))[:2]
        flow_gap_refs = list(analysis_result.get("flow_gap_refs", []))[:2]
        if request_type == "ambiguity_followup" or source == "ambiguity_watchlist":
            path_gain_kind = "resolve_ambiguity"
        elif primary_gap and set(str(item) for item in primary_gap.get("missing_step_kinds", [])) & signal_gain:
            path_gain_kind = "close_primary_flow_gap"
        elif signal_gain:
            path_gain_kind = "direct_signal_confirmation"
        elif request_type == "focused_symbol_followup" and path_gain_refs:
            path_gain_kind = "validate_existing_path"
        else:
            path_gain_kind = "no_path_gain"
        expected_path_gain = {
            "gain_kind": path_gain_kind,
            "path_refs": path_gain_refs,
            "flow_gap_refs": flow_gap_refs if path_gain_kind == "close_primary_flow_gap" else [],
        }

        expected_target_outcome = ""
        covers_all_missing = bool(missing_signals) and missing_signals <= signal_gain
        if request_type == "ambiguity_followup" or source == "ambiguity_watchlist":
            if current_outcome == "ambiguous":
                expected_target_outcome = "confirmed" if not missing_signals and not analysis_result.get("flow_gap_refs", []) else "partial"
        elif signal_gain:
            if current_outcome == "partial":
                expected_target_outcome = "confirmed" if covers_all_missing else "partial"
            elif current_outcome == "unproven":
                expected_target_outcome = "confirmed" if covers_all_missing and not analysis_result.get("ambiguity_refs", []) else "partial"
        elif request_type == "focused_symbol_followup" and current_outcome == "partial" and not missing_signals:
            expected_target_outcome = "confirmed"

        cost = self._escalation_cost_payload(target_slice_candidates)
        blocked_by: List[str] = []
        if current_outcome == "confirmed":
            blocked_by.append("confirmed_result_already_sufficient")
        if not target_slice_candidates:
            blocked_by.append("no_target_slice_candidates")
        if current_outcome == "ambiguous" and request_type != "ambiguity_followup" and source != "ambiguity_watchlist":
            blocked_by.append("ambiguity_requires_disambiguation_only")
        if not expected_target_outcome or expected_target_outcome == current_outcome:
            blocked_by.append("no_expected_outcome_upgrade")
        if cost["label"] == "high" and expected_target_outcome != "confirmed":
            blocked_by.append("cost_exceeds_bounded_gain")
        allowed = not blocked_by

        if not allowed:
            confidence = "low"
        elif expected_target_outcome == "confirmed" and cost["label"] == "low" and signal_gain:
            confidence = "high"
        elif expected_target_outcome in {"confirmed", "partial"} and cost["label"] in {"low", "medium"}:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "option_id": option_id,
            "source": source,
            "request_ref": request_ref,
            "target_symbols": target_symbols,
            "target_slice_candidates": target_slice_candidates,
            "why": str(request.get("why", "")) or str(request.get("request", "")),
            "expected_evidence_gain": expected_evidence_gain,
            "expected_signal_gain": self._sort_semantic_signals(signal_gain),
            "expected_path_gain": expected_path_gain,
            "expected_target_outcome": expected_target_outcome,
            "expected_outcome_upgrade": self._outcome_upgrade_label(current_outcome, expected_target_outcome),
            "confidence": confidence,
            "cost": cost,
            "allowed": allowed,
            "blocked_by": blocked_by,
        }

    def _build_escalation_controller(
        self,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        selected_slices: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
        selected_flow_chains: List[Dict[str, object]],
        flow_gaps: List[Dict[str, object]],
        ambiguity_watchlist: List[Dict[str, object]],
        deferred_requests: List[Dict[str, object]],
        analysis_result: Dict[str, object],
    ) -> Dict[str, object]:
        current_outcome = str(analysis_result.get("outcome_mode", "unproven") or "unproven")
        primary_target_id = str(analysis_result.get("minimal_basis", {}).get("primary_symbol", "") or "")
        primary_chain = self._select_primary_flow_chain(primary_target_id, selected_flow_chains)
        primary_path = self._select_primary_evidence_path(primary_target_id, selected_paths)
        primary_gap = self._select_primary_flow_gap(primary_target_id, primary_chain, primary_path, flow_gaps)
        ambiguity_item = next(
            (
                item
                for item in ambiguity_watchlist
                if str(item.get("source_node", "")) == primary_target_id
            ),
            ambiguity_watchlist[0] if ambiguity_watchlist else {},
        )

        if current_outcome == "confirmed":
            return {
                "current_result_ref": "analysis_result",
                "current_outcome_mode": current_outcome,
                "escalation_needed": False,
                "escalation_allowed": False,
                "escalation_reason": "The current confirmed result already satisfies the query conservatively.",
                "stop_reason": "sufficient_confirmed_result",
                "current_sufficiency": "sufficient_confirmed_result",
                "next_step_mode": "stop",
                "escalation_options": [],
                "recommended_option": None,
                "maximum_reachable_outcome": "confirmed",
                "escalation_budget": {
                    "max_options_considered": 4,
                    "max_target_slices_per_option": 2,
                    "low_cost_line_span": 8,
                    "medium_cost_line_span": 24,
                },
                "next_ask_seed": None,
            }

        request_candidates: List[Tuple[str, str, Dict[str, object]]] = []
        seen_requests: Set[str] = set()
        next_best_request = analysis_result.get("next_best_request")
        if isinstance(next_best_request, dict) and next_best_request:
            signature = self._request_signature(next_best_request)
            seen_requests.add(signature)
            request_candidates.append(("next_best_request", "analysis_result.next_best_request", dict(next_best_request)))
        for index, request in enumerate(deferred_requests, start=1):
            signature = self._request_signature(request)
            if signature in seen_requests:
                continue
            seen_requests.add(signature)
            request_candidates.append(("deferred_request", f"ask_deferred_request_{index:02d}", dict(request)))

        synthetic_ambiguity = self._derive_synthetic_ambiguity_request(ambiguity_item, selected_slices)
        if synthetic_ambiguity is not None:
            signature = self._request_signature(synthetic_ambiguity)
            if signature not in seen_requests:
                seen_requests.add(signature)
                request_candidates.append(("ambiguity_watchlist", "synthetic_ambiguity", synthetic_ambiguity))

        synthetic_semantic_gap = self._derive_synthetic_semantic_gap_request(
            primary_target_id,
            primary_path,
            primary_chain,
            list(
                {
                    str(signal)
                    for item in analysis_result.get("missing_evidence", [])
                    if str(item.get("kind", "")) == "missing_signal"
                    for signal in item.get("signals", [])
                }
            ),
            selected_slices,
        )
        if synthetic_semantic_gap is not None:
            signature = self._request_signature(synthetic_semantic_gap)
            if signature not in seen_requests:
                seen_requests.add(signature)
                request_candidates.append(("semantic_gap", "synthetic_semantic_gap", synthetic_semantic_gap))

        options: List[Dict[str, object]] = []
        for index, (source, request_ref, request) in enumerate(request_candidates[:4], start=1):
            options.append(
                self._build_escalation_option(
                    option_id=f"option_{index:02d}",
                    source=source,
                    request_ref=request_ref,
                    request=request,
                    current_outcome=current_outcome,
                    analysis_result=analysis_result,
                    primary_gap=primary_gap,
                    ambiguity_item=ambiguity_item,
                )
            )

        cost_rank = {"low": 0, "medium": 1, "high": 2}
        confidence_rank = {"low": 0, "medium": 1, "high": 2}
        source_rank = {
            "next_best_request": 0,
            "semantic_gap": 1,
            "ambiguity_watchlist": 2,
            "deferred_request": 3,
            "path_completion": 4,
            "flow_gap": 5,
        }
        options.sort(
            key=lambda item: (
                0 if item.get("allowed") else 1,
                cost_rank.get(str(item.get("cost", {}).get("label", "")), 9),
                -self._outcome_mode_rank(str(item.get("expected_target_outcome", ""))),
                -confidence_rank.get(str(item.get("confidence", "")), -1),
                source_rank.get(str(item.get("source", "")), 9),
                str(item.get("option_id", "")),
            )
        )

        allowed_options = [item for item in options if item.get("allowed")]
        recommended_option = dict(allowed_options[0]) if allowed_options else None
        maximum_reachable_outcome = current_outcome
        for option in allowed_options:
            target_outcome = str(option.get("expected_target_outcome", ""))
            if self._outcome_mode_rank(target_outcome) > self._outcome_mode_rank(maximum_reachable_outcome):
                maximum_reachable_outcome = target_outcome

        escalation_allowed = recommended_option is not None
        escalation_needed = bool(escalation_allowed and current_outcome != "confirmed")
        if escalation_allowed:
            current_sufficiency = "bounded_result_with_escalation_option"
            escalation_reason = "A bounded next evidence step could improve the current result without widening the context excessively."
            stop_reason = None
            next_step_mode = "bounded_escalation"
        else:
            current_sufficiency = "bounded_result_without_safe_escalation"
            escalation_reason = "No bounded evidence request offers a conservative outcome upgrade from the current result."
            stop_reason = "no_bounded_evidence_gain"
            next_step_mode = "stop"

        next_ask_seed = None
        if recommended_option is not None:
            cost_label = str(recommended_option.get("cost", {}).get("label", "medium"))
            next_ask_seed = {
                "derived_query": str(recommended_option.get("why", "")) or str(recommended_option.get("request_ref", "")),
                "derived_focus_symbols": list(recommended_option.get("target_symbols", []))[:3],
                "derived_budget": 20 if cost_label == "low" else (35 if cost_label == "medium" else 60),
                "derived_goal": str(recommended_option.get("expected_outcome_upgrade", "")) or "gather_additional_evidence",
            }

        return {
            "current_result_ref": "analysis_result",
            "current_outcome_mode": current_outcome,
            "escalation_needed": escalation_needed,
            "escalation_allowed": escalation_allowed,
            "escalation_reason": escalation_reason,
            "stop_reason": stop_reason,
            "current_sufficiency": current_sufficiency,
            "next_step_mode": next_step_mode,
            "escalation_options": options,
            "recommended_option": recommended_option,
            "maximum_reachable_outcome": maximum_reachable_outcome,
            "escalation_budget": {
                "max_options_considered": 4,
                "max_target_slices_per_option": 2,
                "low_cost_line_span": 8,
                "medium_cost_line_span": 24,
            },
            "next_ask_seed": next_ask_seed,
        }

    def _build_escalation_prompt(self, ask_context_pack: Dict[str, object]) -> str:
        query = str(ask_context_pack.get("query", ""))
        analysis_result = ask_context_pack.get("analysis_result", {}) if isinstance(ask_context_pack.get("analysis_result"), dict) else {}
        controller = ask_context_pack.get("escalation_controller", {}) if isinstance(ask_context_pack.get("escalation_controller"), dict) else {}
        allowed = bool(controller.get("escalation_allowed"))
        maximum_reachable = str(controller.get("maximum_reachable_outcome", "") or analysis_result.get("outcome_mode", ""))
        return (
            f"Respect `analysis_result` first for `{query}`. Escalate only if `escalation_controller.recommended_option.allowed = true` "
            f"and only by opening its `target_slice_candidates`. Treat `{maximum_reachable}` as the maximum reachable outcome after one bounded "
            "escalation step, not as a granted upgrade. If `escalation_allowed = false`, stop immediately with the exported `stop_reason`. "
            "Do not claim an upgraded outcome until the new evidence is actually opened and the analysis is rerun."
            if allowed
            else (
                f"Respect `analysis_result` first for `{query}` and stop unless a future rerun produces a bounded `recommended_option`. "
                "The current `escalation_controller` does not allow a safe next step, so do not widen the context or invent a stronger outcome."
            )
        )

    def _followup_kind_for_option(self, option: Dict[str, object]) -> str:
        source = str(option.get("source", ""))
        request_gain = set(str(item) for item in option.get("expected_evidence_gain", []))
        path_gain = option.get("expected_path_gain", {}) if isinstance(option.get("expected_path_gain"), dict) else {}
        path_gain_kind = str(path_gain.get("gain_kind", ""))
        if "candidate_disambiguation" in request_gain or source == "ambiguity_watchlist":
            return "ambiguity_resolution"
        if path_gain_kind == "close_primary_flow_gap":
            return "flow_gap_check"
        if option.get("expected_signal_gain"):
            return "semantic_confirmation"
        if path_gain_kind in {"validate_existing_path", "close_primary_flow_gap"} or source in {"path_completion", "flow_gap"}:
            return "path_completion"
        return "focused_symbol_check"

    def _followup_budget(self, option: Dict[str, object]) -> Dict[str, object]:
        target_slice_candidates = list(option.get("target_slice_candidates", []))
        cost = option.get("cost", {}) if isinstance(option.get("cost"), dict) else {}
        cost_label = str(cost.get("label", "medium") or "medium")
        unique_files = {str(item.get("file", "")) for item in target_slice_candidates if item.get("file")}
        line_span = sum(
            max(1, int(item["lines"][1]) - int(item["lines"][0]) + 1)
            for item in target_slice_candidates
            if item.get("lines")
        )
        if cost_label == "low":
            line_budget = min(max(line_span + 2, 8), 12)
            slice_budget = 1
            file_budget = 1
        elif cost_label == "medium":
            line_budget = min(max(line_span + 4, 12), 24)
            slice_budget = min(2, max(1, len(target_slice_candidates)))
            file_budget = min(2, max(1, len(unique_files) or 1))
        else:
            line_budget = min(max(line_span + 6, 18), 40)
            slice_budget = min(3, max(1, len(target_slice_candidates)))
            file_budget = min(3, max(1, len(unique_files) or 1))
        return {
            "line_budget": line_budget,
            "slice_budget": slice_budget,
            "file_budget": file_budget,
            "cost_label": cost_label,
        }

    def _build_followup_guardrails(
        self,
        focus_symbols: List[str],
        option: Dict[str, object],
        analysis_result: Dict[str, object],
    ) -> Tuple[Dict[str, object], List[str]]:
        path_gain = option.get("expected_path_gain", {}) if isinstance(option.get("expected_path_gain"), dict) else {}
        do_not_expand_beyond = {
            "focus_symbols": list(focus_symbols[:3]),
            "slice_targets": list(option.get("target_slice_candidates", []))[:2],
            "path_refs": list(path_gain.get("path_refs", []))[:2],
            "flow_refs": list(analysis_result.get("supporting_flow_refs", []))[:2],
        }
        forbidden_scope_expansions = ["do_not_generalize_project_wide"]
        if str(analysis_result.get("outcome_mode", "")) != "confirmed":
            forbidden_scope_expansions.append("do_not_infer_missing_io")
        if str(option.get("source", "")) != "ambiguity_watchlist":
            forbidden_scope_expansions.append("do_not_open_unrelated_callers")
        if do_not_expand_beyond["path_refs"]:
            forbidden_scope_expansions.append("do_not_expand_to_sibling_modules")
        if any(str(item).startswith("java.") or str(item).startswith("typescript.") or str(item).startswith("pyapp.") for item in focus_symbols):
            forbidden_scope_expansions.append("do_not_leave_primary_focus_symbols")
        return do_not_expand_beyond, sorted(set(forbidden_scope_expansions))

    def _build_followup_ask(
        self,
        query: str,
        analysis: Dict[str, object],
        analysis_result: Dict[str, object],
        escalation_controller: Dict[str, object],
    ) -> Dict[str, object]:
        recommended_option = (
            escalation_controller.get("recommended_option", {})
            if isinstance(escalation_controller.get("recommended_option"), dict)
            else {}
        )
        if not bool(escalation_controller.get("escalation_allowed")) or not recommended_option:
            return {
                "enabled": False,
                "derived_from": "escalation_controller",
                "source_option_ref": None,
                "followup_kind": "none",
                "derived_query": "",
                "derived_goal": "",
                "derived_focus_symbols": [],
                "derived_slice_targets": [],
                "derived_path_refs": [],
                "derived_flow_refs": [],
                "derived_semantic_signals": [],
                "expected_outcome_upgrade": "none",
                "maximum_reachable_outcome": str(escalation_controller.get("maximum_reachable_outcome", analysis_result.get("outcome_mode", ""))),
                "budget": {
                    "line_budget": 0,
                    "slice_budget": 0,
                    "file_budget": 0,
                    "cost_label": "none",
                },
                "stop_if": str(escalation_controller.get("stop_reason", "followup_not_allowed")),
                "stop_reason": str(escalation_controller.get("stop_reason", "followup_not_allowed")),
                "do_not_expand_beyond": {
                    "focus_symbols": [],
                    "slice_targets": [],
                    "path_refs": [],
                    "flow_refs": [],
                },
                "forbidden_scope_expansions": ["do_not_generalize_project_wide"],
            }

        primary_symbol = str(analysis_result.get("minimal_basis", {}).get("primary_symbol", "") or "")
        primary_label = self._node_brief_label(primary_symbol) if primary_symbol else "the current primary symbol"
        focus_symbols = list(recommended_option.get("target_symbols", []))[:3] or ([primary_symbol] if primary_symbol else [])
        focus_label = self._node_brief_label(focus_symbols[0]) if focus_symbols else primary_label
        followup_kind = self._followup_kind_for_option(recommended_option)
        expected_signal_gain = [str(item) for item in recommended_option.get("expected_signal_gain", []) if item]
        signal_phrase = self._analysis_result_behavior_phrase(expected_signal_gain, analysis)
        expected_outcome_upgrade = str(recommended_option.get("expected_outcome_upgrade", "none") or "none")
        maximum_reachable_outcome = str(escalation_controller.get("maximum_reachable_outcome", analysis_result.get("outcome_mode", "")))
        budget = self._followup_budget(recommended_option)
        path_gain = recommended_option.get("expected_path_gain", {}) if isinstance(recommended_option.get("expected_path_gain"), dict) else {}
        derived_path_refs = list(path_gain.get("path_refs", []))[:2]
        derived_flow_refs = list(analysis_result.get("supporting_flow_refs", []))[:2]

        if followup_kind == "ambiguity_resolution":
            derived_query = f"Resolve the remaining ambiguity for {primary_label} using only the smallest candidate slices."
            derived_goal = f"Attempt `{expected_outcome_upgrade}` by disambiguating the bounded candidate set without widening scope."
            stop_if = "Stop if the candidate slices still leave multiple plausible answers; keep the current bounded result."
        elif followup_kind == "flow_gap_check":
            derived_query = f"Check whether the selected {primary_label} path has direct {signal_phrase} evidence in the smallest remaining candidate slice."
            derived_goal = f"Attempt `{expected_outcome_upgrade}` by closing the current flow gap with one bounded evidence check."
            stop_if = f"Stop if the bounded slice still does not show direct {signal_phrase} evidence; keep the current {analysis_result.get('outcome_mode', '')} result."
        elif followup_kind == "semantic_confirmation":
            derived_query = f"Check whether {focus_label} has direct {signal_phrase} evidence in the smallest remaining candidate slice."
            derived_goal = f"Attempt `{expected_outcome_upgrade}` by confirming only the missing direct semantic evidence."
            stop_if = f"Stop if the bounded slice still does not show direct {signal_phrase} evidence; do not broaden the claim."
        elif followup_kind == "path_completion":
            derived_query = f"Check whether the selected {primary_label} path transition is directly evidenced in the smallest remaining candidate slice."
            derived_goal = f"Attempt `{expected_outcome_upgrade}` by validating one bounded path transition."
            stop_if = "Stop if the bounded slice does not close the existing path transition; keep the current bounded result."
        else:
            derived_query = f"Check only {focus_label} in the smallest remaining slice needed by the current result."
            derived_goal = f"Attempt `{expected_outcome_upgrade}` with a bounded symbol-level evidence check."
            stop_if = "Stop if the bounded symbol slice does not improve the current result; do not expand to unrelated context."

        do_not_expand_beyond, forbidden_scope_expansions = self._build_followup_guardrails(
            focus_symbols,
            recommended_option,
            analysis_result,
        )
        return {
            "enabled": True,
            "derived_from": "escalation_controller.recommended_option",
            "source_option_ref": str(recommended_option.get("option_id", "")),
            "followup_kind": followup_kind,
            "derived_query": derived_query,
            "derived_goal": derived_goal,
            "derived_focus_symbols": focus_symbols,
            "derived_slice_targets": list(recommended_option.get("target_slice_candidates", []))[:2],
            "derived_path_refs": derived_path_refs,
            "derived_flow_refs": derived_flow_refs,
            "derived_semantic_signals": expected_signal_gain,
            "expected_outcome_upgrade": expected_outcome_upgrade,
            "maximum_reachable_outcome": maximum_reachable_outcome,
            "budget": budget,
            "stop_if": stop_if,
            "do_not_expand_beyond": do_not_expand_beyond,
            "forbidden_scope_expansions": forbidden_scope_expansions,
            "stop_reason": None,
        }

    def _build_followup_prompt(self, ask_context_pack: Dict[str, object]) -> str:
        query = str(ask_context_pack.get("query", ""))
        analysis_result = ask_context_pack.get("analysis_result", {}) if isinstance(ask_context_pack.get("analysis_result"), dict) else {}
        followup_ask = ask_context_pack.get("followup_ask", {}) if isinstance(ask_context_pack.get("followup_ask"), dict) else {}
        if not bool(followup_ask.get("enabled")):
            return (
                f"Respect `analysis_result` for `{query}` and do not create a bounded follow-up ask. "
                f"The exported stop reason is `{followup_ask.get('stop_reason', 'followup_not_allowed')}`, so do not widen scope or open extra context."
            )
        return (
            f"Respect the existing `analysis_result` for `{query}`. Run only the bounded follow-up described in `followup_ask`: "
            "inspect only `derived_slice_targets`, keep the scope inside `derived_focus_symbols`, and pursue only the exported "
            "`expected_outcome_upgrade`. If the targeted slices do not yield the expected direct evidence, stop and keep the "
            f"current `{analysis_result.get('outcome_mode', '')}` result. Do not expand beyond `do_not_expand_beyond` or violate "
            "`forbidden_scope_expansions`."
        )

    def _slice_ref_from_file_lines(self, file_name: str, lines: Iterable[int]) -> str:
        line_values = list(lines)
        if not file_name or not line_values:
            return ""
        start = int(line_values[0])
        end = int(line_values[1]) if len(line_values) > 1 else start
        return f"{file_name}:{start}-{end}"

    def _infer_worker_task_kind(
        self,
        analysis: Dict[str, object],
        analysis_result: Dict[str, object],
    ) -> str:
        intents = {str(item) for item in analysis.get("inferred_intents", [])}
        matched_signals = {str(item) for item in analysis_result.get("requested_semantic_signals", [])}
        if "refactor" in intents:
            return "refactor_probe"
        if bool(analysis.get("ambiguity_sensitive")) or analysis_result.get("outcome_mode") == "ambiguous":
            return "ambiguity_check"
        if {"auth_guard", "validation_guard"} & matched_signals and (
            matched_signals & {"database_io", "network_io", "filesystem_io", "process_io", "external_io"}
        ):
            return "verify_guard"
        if analysis.get("scope_preference") == "path" or "explain_flow" in intents:
            return "explain_path"
        if matched_signals & {"filesystem_io", "database_io", "network_io", "process_io", "external_io", "state_mutation"}:
            return "inspect_side_effect"
        if "architecture" in intents:
            return "impact_check"
        return "inspect_side_effect"

    def _choose_worker_mode(
        self,
        task_kind: str,
        analysis_result: Dict[str, object],
        ambiguity_watchlist: List[Dict[str, object]],
        followup_ask: Dict[str, object],
    ) -> str:
        outcome_mode = str(analysis_result.get("outcome_mode", "unproven") or "unproven")
        if task_kind == "refactor_probe":
            return "inspect_then_refactor_plan"
        if outcome_mode == "ambiguous" and (ambiguity_watchlist or bool(followup_ask.get("enabled"))):
            return "inspect_then_compare"
        if outcome_mode == "confirmed" and not bool(followup_ask.get("enabled")):
            return "answer_only"
        if task_kind == "ambiguity_check":
            return "ambiguity_resolution_only"
        return "inspect_then_answer"

    def _work_packet_target_payload(
        self,
        node_id: str,
        role: str,
        why: str,
        slice_refs: Optional[Iterable[str]] = None,
        flow_refs: Optional[Iterable[str]] = None,
        path_refs: Optional[Iterable[str]] = None,
    ) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "symbol": node_id,
            "label": self._node_brief_label(node_id) if node_id else node_id,
            "role": role,
            "why": why,
        }
        slice_values = [str(item) for item in (slice_refs or []) if str(item)]
        flow_values = [str(item) for item in (flow_refs or []) if str(item)]
        path_values = [str(item) for item in (path_refs or []) if str(item)]
        if slice_values:
            payload["slice_refs"] = list(dict.fromkeys(slice_values))[:3]
        if flow_values:
            payload["flow_refs"] = list(dict.fromkeys(flow_values))[:2]
        if path_values:
            payload["path_refs"] = list(dict.fromkeys(path_values))[:2]
        return payload

    def _work_packet_supporting_symbols(
        self,
        primary_target_id: str,
        primary_chain: Dict[str, object],
        primary_path: Dict[str, object],
    ) -> List[str]:
        supporting: List[str] = []
        for node_id in primary_chain.get("nodes", []):
            node_id = str(node_id)
            if node_id and node_id != primary_target_id and node_id in self.nodes and node_id not in supporting:
                supporting.append(node_id)
        for node_id in self._ordered_path_nodes(primary_path):
            node_id = str(node_id)
            if node_id and node_id != primary_target_id and node_id in self.nodes and node_id not in supporting:
                supporting.append(node_id)
        supporting.sort(
            key=lambda node_id: (
                0 if self.nodes[node_id].kind in SEMANTIC_EXECUTABLE_KINDS else 1,
                self._node_brief_label(node_id),
                node_id,
            )
        )
        return supporting[:4]

    def _slice_refs_for_work_target(
        self,
        node_id: str,
        selected_slices: List[Dict[str, object]],
        preferred_refs: Optional[Set[str]] = None,
    ) -> List[str]:
        slice_refs_by_symbol = self._slice_refs_by_symbol(selected_slices)
        refs: List[str] = []
        for ref in slice_refs_by_symbol.get(node_id, []):
            ref = str(ref)
            if preferred_refs and ref not in preferred_refs:
                continue
            if ref and ref not in refs:
                refs.append(ref)
        node = self.nodes.get(node_id)
        if node is not None:
            for spec in selected_slices:
                ref = self._slice_ref(spec)
                if preferred_refs and ref not in preferred_refs:
                    continue
                if str(spec.get("file", "")) == node.file and ref not in refs:
                    refs.append(ref)
        return refs[:3]

    def _primary_ambiguity_item(
        self,
        primary_target_id: str,
        ambiguity_watchlist: List[Dict[str, object]],
    ) -> Dict[str, object]:
        if primary_target_id:
            for item in ambiguity_watchlist:
                if str(item.get("source_node", "")) == primary_target_id:
                    return dict(item)
        return dict(ambiguity_watchlist[0]) if ambiguity_watchlist else {}

    def _build_ambiguity_candidate_targets(
        self,
        primary_target_id: str,
        ambiguity_item: Dict[str, object],
        selected_slices: List[Dict[str, object]],
        read_order_refs: Set[str],
    ) -> List[Dict[str, object]]:
        if not ambiguity_item:
            return []
        targets: List[Dict[str, object]] = []
        seen_symbols: Set[str] = set()
        recommended_targets = (
            ambiguity_item.get("recommended_next_evidence_target", {}).get("targets", [])
            if isinstance(ambiguity_item.get("recommended_next_evidence_target"), dict)
            else []
        )
        for candidate_id in [str(item) for item in ambiguity_item.get("candidates", []) if str(item)]:
            if candidate_id == primary_target_id or candidate_id in seen_symbols:
                continue
            slice_refs = self._slice_refs_for_work_target(candidate_id, selected_slices, read_order_refs)
            if not slice_refs:
                node = self.nodes.get(candidate_id)
                if node is not None:
                    for target in recommended_targets:
                        file_name = str(target.get("file", ""))
                        if file_name != node.file:
                            continue
                        ref = self._slice_ref_from_file_lines(file_name, target.get("lines", []))
                        if ref and ref not in slice_refs:
                            slice_refs.append(ref)
            targets.append(
                self._work_packet_target_payload(
                    candidate_id,
                    "candidate",
                    "Candidate implementation retained by the ambiguity watchlist for direct comparison.",
                    slice_refs=slice_refs,
                )
            )
            seen_symbols.add(candidate_id)
        if len(targets) >= 3:
            return targets[:3]
        for target in recommended_targets:
            file_name = str(target.get("file", ""))
            raw_lines = list(target.get("lines", []))
            if not file_name or not raw_lines:
                continue
            start = int(raw_lines[0])
            end = int(raw_lines[1]) if len(raw_lines) > 1 else start
            matching_nodes: List[str] = []
            for node_id, node in self.nodes.items():
                if node_id == primary_target_id or node.file != file_name or node_id in seen_symbols:
                    continue
                node_start, node_end = int(node.lines[0]), int(node.lines[1])
                if node_end < start or node_start > end:
                    continue
                matching_nodes.append(node_id)
            matching_nodes.sort(
                key=lambda node_id: (
                    0 if node_id in {str(item) for item in ambiguity_item.get("candidates", [])} else 1,
                    0 if self.nodes[node_id].kind in SEMANTIC_EXECUTABLE_KINDS else 1,
                    self._node_brief_label(node_id),
                    node_id,
                )
            )
            for node_id in matching_nodes:
                slice_refs = self._slice_refs_for_work_target(node_id, selected_slices, read_order_refs)
                if not slice_refs:
                    ref = self._slice_ref_from_file_lines(file_name, raw_lines)
                    if ref:
                        slice_refs.append(ref)
                targets.append(
                    self._work_packet_target_payload(
                        node_id,
                        "support",
                        "Secondary ambiguity context retained after the concrete candidate targets.",
                        slice_refs=slice_refs,
                    )
                )
                seen_symbols.add(node_id)
                if len(targets) >= 3:
                    return targets[:3]
        return targets[:3]

    def _build_work_packet_allowed_claims(
        self,
        analysis: Dict[str, object],
        analysis_result: Dict[str, object],
        primary_target_id: str,
        primary_path: Dict[str, object],
        primary_chain: Dict[str, object],
    ) -> List[str]:
        outcome_mode = str(analysis_result.get("outcome_mode", "unproven") or "unproven")
        symbol_label = self._node_brief_label(primary_target_id) if primary_target_id else "the selected symbol"
        decisive_signals = [str(item) for item in analysis_result.get("minimal_basis", {}).get("decisive_semantic_signals", []) if item]
        context_phrase = self._analysis_result_context_phrase(primary_target_id, primary_path, primary_chain)
        behavior_phrase = self._analysis_result_behavior_phrase(decisive_signals, analysis, primary_path)
        claims = [str(analysis_result.get("claim", ""))]
        if outcome_mode == "confirmed" and decisive_signals:
            claims.append(f"Direct selected evidence confirms {behavior_phrase} in {symbol_label}.")
        elif outcome_mode == "partial" and decisive_signals:
            claims.append(f"The selected evidence directly confirms {behavior_phrase} in {symbol_label}, but not the full requested behavior.")
        elif outcome_mode == "unproven" and context_phrase and context_phrase != "the selected structural context":
            claims.append(f"The selected context shows {symbol_label} reaching {context_phrase}.")
        elif outcome_mode == "ambiguous":
            ambiguity_refs = list(analysis_result.get("ambiguity_refs", []))
            if ambiguity_refs:
                claims.append(f"The current answer must stay ambiguous because `{ambiguity_refs[0]}` is unresolved.")
        return list(dict.fromkeys(item for item in claims if item))[:2]

    def _build_work_packet_disallowed_claims(
        self,
        analysis: Dict[str, object],
        analysis_result: Dict[str, object],
        primary_target_id: str,
        primary_path: Dict[str, object],
    ) -> List[str]:
        symbol_label = self._node_brief_label(primary_target_id) if primary_target_id else "the selected symbol"
        requested_signals = {str(item) for item in analysis_result.get("requested_semantic_signals", [])}
        forbidden = analysis_result.get("forbidden_overreach", {}) if isinstance(analysis_result.get("forbidden_overreach"), dict) else {}
        unsupported = {str(item) for item in forbidden.get("unsupported_claim_kinds", [])}
        statements = [str(item) for item in forbidden.get("statements", []) if item]
        disallowed: List[str] = []
        if "project_wide_claim" in unsupported:
            if {"auth_guard", "database_io"} <= requested_signals:
                disallowed.append("Do not claim that all project database reads are auth-guarded.")
            elif {"state_mutation", "filesystem_io"} <= requested_signals:
                disallowed.append("Do not claim that every project state write reaches disk.")
            elif "network_io" in requested_signals:
                disallowed.append(f"Do not claim project-wide network reachability from {symbol_label}.")
            else:
                disallowed.append(f"Do not generalize beyond {symbol_label}.")
        if "end_to_end_claim_without_direct_io" in unsupported:
            disallowed.append(f"Do not claim that {symbol_label} reaches direct network I/O.")
        if "complete_flow_claim" in unsupported:
            disallowed.append("Do not claim that this is the complete end-to-end path.")
        if "uniqueness_claim_without_disambiguation" in unsupported:
            disallowed.append("Do not claim a unique implementation or single resolved path while ambiguity remains.")
        if "root_cause_claim" in unsupported:
            disallowed.append("Do not infer root cause or hidden intent from the selected evidence.")
        requested_phrase = self._analysis_result_behavior_phrase(
            requested_signals,
            analysis,
            primary_path,
        )
        if analysis_result.get("outcome_mode") in {"partial", "unproven"} and requested_phrase != "the requested behavior":
            disallowed.append(f"Do not claim direct {requested_phrase} unless a selected direct evidence span proves it.")
        disallowed.extend(statements)
        return list(dict.fromkeys(item for item in disallowed if item))[:6]

    def _build_work_packet_read_order(
        self,
        worker_mode: str,
        analysis_result: Dict[str, object],
        analysis_plan: Dict[str, object],
        selected_slices: List[Dict[str, object]],
        followup_ask: Dict[str, object],
    ) -> List[Dict[str, object]]:
        slice_by_ref = {self._slice_ref(spec): spec for spec in selected_slices}
        minimal_open_sequence = list(analysis_plan.get("minimal_open_sequence", []))
        decisive_slice_refs = [
            str(item)
            for item in analysis_result.get("minimal_basis", {}).get("decisive_slice_refs", [])
            if str(item)
        ]
        if worker_mode == "answer_only":
            ordered_refs = decisive_slice_refs[:3]
        else:
            ordered_refs = [
                str(item.get("slice_ref", ""))
                for item in minimal_open_sequence
                if str(item.get("slice_ref", ""))
            ]
            if decisive_slice_refs:
                ordered_refs = list(dict.fromkeys(decisive_slice_refs + ordered_refs))
        if bool(followup_ask.get("enabled")):
            for target in followup_ask.get("derived_slice_targets", []):
                ref = self._slice_ref_from_file_lines(str(target.get("file", "")), target.get("lines", []))
                if ref:
                    ordered_refs.append(ref)
        out: List[Dict[str, object]] = []
        seen: Set[str] = set()
        by_sequence = {
            str(item.get("slice_ref", "")): item
            for item in minimal_open_sequence
            if str(item.get("slice_ref", ""))
        }
        for ref in ordered_refs:
            ref = str(ref)
            if not ref or ref in seen:
                continue
            seen.add(ref)
            sequence_item = by_sequence.get(ref, {})
            spec = slice_by_ref.get(ref)
            if spec is not None and not sequence_item:
                symbols = [str(symbol) for symbol in spec.get("symbols", []) if str(symbol)]
                symbol = symbols[0] if symbols else ""
                sequence_item = {
                    "slice_ref": ref,
                    "symbol": symbol,
                    "why": "Decisive selected evidence for the current bounded answer.",
                    "stop_if": "Stop when the current bounded outcome is already justified.",
                }
            if not sequence_item:
                continue
            out.append(
                {
                    "order": len(out) + 1,
                    "slice_ref": ref,
                    "symbol": str(sequence_item.get("symbol", "")),
                    "why": str(sequence_item.get("why", "")),
                    "stop_if": str(sequence_item.get("stop_if", "")),
                }
            )
            if len(out) >= (3 if worker_mode == "answer_only" else 4):
                break
        return out

    def _build_work_packet_targets(
        self,
        task_kind: str,
        worker_mode: str,
        analysis_result: Dict[str, object],
        primary_target_id: str,
        ambiguity_item: Dict[str, object],
        selected_slices: List[Dict[str, object]],
        read_order_refs: Set[str],
        supporting_symbols: List[str],
        analysis: Dict[str, object],
        primary_path: Dict[str, object],
        primary_chain: Dict[str, object],
    ) -> Tuple[
        List[Dict[str, object]],
        List[Dict[str, object]],
        List[Dict[str, object]],
        List[Dict[str, object]],
        List[Dict[str, object]],
        List[str],
        List[str],
    ]:
        primary_targets: List[Dict[str, object]] = []
        if primary_target_id:
            primary_targets.append(
                self._work_packet_target_payload(
                    primary_target_id,
                    "primary",
                    "Primary executable target chosen by the bounded analysis result.",
                    slice_refs=analysis_result.get("minimal_basis", {}).get("decisive_slice_refs", []),
                    flow_refs=analysis_result.get("minimal_basis", {}).get("decisive_flow_refs", []),
                    path_refs=analysis_result.get("minimal_basis", {}).get("decisive_path_refs", []),
                )
            )
        if task_kind == "ambiguity_check" or worker_mode == "inspect_then_compare":
            supporting_targets = self._build_ambiguity_candidate_targets(
                primary_target_id,
                ambiguity_item,
                selected_slices,
                read_order_refs,
            )
            if len(supporting_targets) < 3:
                candidate_symbols = {str(item.get("symbol", "")) for item in supporting_targets}
                for node_id in supporting_symbols:
                    if node_id in candidate_symbols or node_id == primary_target_id:
                        continue
                    supporting_targets.append(
                        self._work_packet_target_payload(
                            node_id,
                            "support",
                            "Secondary executable or path-adjacent context retained after ambiguity candidates.",
                            slice_refs=self._slice_refs_for_work_target(node_id, selected_slices, read_order_refs),
                            flow_refs=analysis_result.get("supporting_flow_refs", []),
                            path_refs=analysis_result.get("supporting_path_refs", []),
                        )
                    )
                    if len(supporting_targets) >= 3:
                        break
        else:
            supporting_targets = [
                self._work_packet_target_payload(
                    node_id,
                    "support",
                    "Supporting executable or path-adjacent evidence retained by the query-scoped planner.",
                    slice_refs=[
                        ref
                        for ref in analysis_result.get("supporting_slice_refs", [])
                        if str(ref) in read_order_refs
                    ],
                    flow_refs=analysis_result.get("supporting_flow_refs", []),
                    path_refs=analysis_result.get("supporting_path_refs", []),
                )
                for node_id in supporting_symbols
            ][:3]

        allowed_claims = self._build_work_packet_allowed_claims(
            analysis,
            analysis_result,
            primary_target_id,
            primary_path,
            primary_chain,
        )
        disallowed_claims = self._build_work_packet_disallowed_claims(
            analysis,
            analysis_result,
            primary_target_id,
            primary_path,
        )

        answer_targets = list(primary_targets)
        for item in supporting_targets:
            if item["symbol"] not in {target["symbol"] for target in answer_targets}:
                answer_targets.append(item)
            if len(answer_targets) >= 3:
                break

        patch_targets: List[Dict[str, object]] = []
        if (
            primary_target_id in self.nodes
            and self.nodes[primary_target_id].kind in SEMANTIC_EXECUTABLE_KINDS
            and str(analysis_result.get("outcome_mode", "")) in {"confirmed", "partial"}
        ):
            patch_targets.append(
                self._work_packet_target_payload(
                    primary_target_id,
                    "patch_candidate",
                    "Smallest direct executable locus if behavior around the proven evidence needs to change.",
                    slice_refs=analysis_result.get("minimal_basis", {}).get("decisive_slice_refs", []),
                    flow_refs=analysis_result.get("minimal_basis", {}).get("decisive_flow_refs", []),
                    path_refs=analysis_result.get("minimal_basis", {}).get("decisive_path_refs", []),
                )
            )

        refactor_targets: List[Dict[str, object]] = []
        if task_kind == "refactor_probe":
            for node_id in [primary_target_id] + supporting_symbols:
                if node_id and node_id in self.nodes:
                    refactor_targets.append(
                        self._work_packet_target_payload(
                            node_id,
                            "refactor_candidate",
                            "Refactor inquiry target retained from the bounded primary path.",
                            slice_refs=analysis_result.get("supporting_slice_refs", []),
                            flow_refs=analysis_result.get("supporting_flow_refs", []),
                            path_refs=analysis_result.get("supporting_path_refs", []),
                        )
                    )
                if len(refactor_targets) >= 3:
                    break

        return (
            primary_targets,
            supporting_targets,
            answer_targets,
            patch_targets,
            refactor_targets,
            allowed_claims,
            disallowed_claims,
        )

    def _build_work_packet_completion(
        self,
        outcome_mode: str,
        worker_mode: str,
        followup_ask: Dict[str, object],
        analysis: Dict[str, object],
        analysis_result: Dict[str, object],
        primary_path: Dict[str, object],
    ) -> Tuple[Dict[str, object], List[Dict[str, object]], List[str]]:
        if outcome_mode == "confirmed":
            when_answer_is_complete = "Stop once the allowed confirmed claim is directly supported by decisive_evidence."
            when_to_stop_without_upgrade = "Stop immediately after the decisive evidence is read; no stronger bounded result is needed."
        elif outcome_mode == "ambiguous":
            when_answer_is_complete = "Stop once the bounded ambiguous claim and candidate set are stated without collapsing the ambiguity."
            when_to_stop_without_upgrade = "Stop if the current candidate slices still leave multiple plausible answers."
        else:
            requested_phrase = self._analysis_result_behavior_phrase(
                analysis_result.get("requested_semantic_signals", []),
                analysis,
                primary_path,
            )
            when_answer_is_complete = "Stop once the bounded claim and its limitation are both stated from decisive_evidence."
            when_to_stop_without_upgrade = (
                f"Stop after the listed read_order if direct {requested_phrase} evidence is still absent."
                if requested_phrase != "the requested behavior"
                else "Stop after the listed read_order if the requested direct evidence is still absent."
            )

        followup_enabled = bool(followup_ask.get("enabled"))
        completion_criteria = {
            "when_answer_is_complete": when_answer_is_complete,
            "when_to_stop_without_upgrade": when_to_stop_without_upgrade,
            "when_to_request_followup": (
                "Only request the exported bounded follow-up after the current read_order is exhausted."
                if followup_enabled
                else "Do not request follow-up; the current escalation and follow-up gates are closed."
            ),
            "when_not_to_patch": "Do not patch unless the user explicitly asks for a change and the patch can stay inside `patch_targets`.",
        }
        stop_conditions = [
            {"kind": "answer_complete", "condition": completion_criteria["when_answer_is_complete"]},
            {"kind": "bounded_stop", "condition": completion_criteria["when_to_stop_without_upgrade"]},
            {"kind": "followup_gate", "condition": completion_criteria["when_to_request_followup"]},
        ]

        execution_notes = [
            "Read only the exported `read_order` first; do not widen to sibling modules or callers.",
            "State only `allowed_claims`; treat `disallowed_claims` as hard boundaries.",
        ]
        if worker_mode == "answer_only":
            execution_notes.append("Do not keep exploring after the decisive evidence is read; answer and stop.")
        else:
            execution_notes.append("Inspect the listed bounded context, then answer at the current outcome mode without inventing upgrades.")
        if followup_enabled:
            execution_notes.append("A single bounded follow-up exists, but it is only relevant after the current read_order is exhausted.")
        else:
            execution_notes.append("Do not create a new follow-up request; the current bounded result is the stopping point.")

        return completion_criteria, stop_conditions, execution_notes

    def _build_work_packet(
        self,
        query: str,
        analysis: Dict[str, object],
        analysis_plan: Dict[str, object],
        analysis_result: Dict[str, object],
        selected_slices: List[Dict[str, object]],
        selected_flow_chains: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
        flow_gaps: List[Dict[str, object]],
        ambiguity_watchlist: List[Dict[str, object]],
        escalation_controller: Dict[str, object],
        followup_ask: Dict[str, object],
    ) -> Dict[str, object]:
        primary_target_id = str(analysis_result.get("minimal_basis", {}).get("primary_symbol", "") or "")
        primary_chain = self._select_primary_flow_chain(primary_target_id, selected_flow_chains)
        primary_path = self._select_primary_evidence_path(primary_target_id, selected_paths)
        ambiguity_item = self._primary_ambiguity_item(primary_target_id, ambiguity_watchlist)
        task_kind = self._infer_worker_task_kind(analysis, analysis_result)
        worker_mode = self._choose_worker_mode(task_kind, analysis_result, ambiguity_watchlist, followup_ask)
        read_order = self._build_work_packet_read_order(
            worker_mode,
            analysis_result,
            analysis_plan,
            selected_slices,
            followup_ask,
        )
        supporting_symbols = self._work_packet_supporting_symbols(primary_target_id, primary_chain, primary_path)
        read_order_refs = {str(item.get("slice_ref", "")) for item in read_order if str(item.get("slice_ref", ""))}
        (
            primary_targets,
            supporting_targets,
            answer_targets,
            patch_targets,
            refactor_targets,
            allowed_claims,
            disallowed_claims,
        ) = self._build_work_packet_targets(
            task_kind,
            worker_mode,
            analysis_result,
            primary_target_id,
            ambiguity_item,
            selected_slices,
            read_order_refs,
            supporting_symbols,
            analysis,
            primary_path,
            primary_chain,
        )

        outcome_mode = str(analysis_result.get("outcome_mode", "unproven") or "unproven")
        completion_criteria, stop_conditions, execution_notes = self._build_work_packet_completion(
            outcome_mode,
            worker_mode,
            followup_ask,
            analysis,
            analysis_result,
            primary_path,
        )
        recommended_option_ref = str(followup_ask.get("source_option_ref", "") or analysis_result.get("recommended_escalation_option_ref", "") or "").strip()

        return {
            "task": query,
            "task_kind": task_kind,
            "worker_mode": worker_mode,
            "preferred_action": worker_mode,
            "current_outcome_mode": outcome_mode,
            "read_order": read_order,
            "primary_targets": primary_targets,
            "supporting_targets": supporting_targets,
            "decisive_evidence": {
                "evidence_refs": list(analysis_result.get("evidence_refs", []))[:8],
                "slice_refs": list(analysis_result.get("minimal_basis", {}).get("decisive_slice_refs", []))[:3],
                "flow_refs": list(analysis_result.get("minimal_basis", {}).get("decisive_flow_refs", []))[:2],
                "path_refs": list(analysis_result.get("minimal_basis", {}).get("decisive_path_refs", []))[:2],
                "semantic_refs": list(analysis_result.get("supporting_semantic_refs", []))[:3],
                "flow_gap_refs": list(analysis_result.get("flow_gap_refs", []))[:2],
                "ambiguity_refs": list(analysis_result.get("ambiguity_refs", []))[:2],
            },
            "allowed_claims": allowed_claims,
            "disallowed_claims": disallowed_claims,
            "stop_conditions": stop_conditions,
            "completion_criteria": completion_criteria,
            "patch_targets": patch_targets,
            "refactor_targets": refactor_targets,
            "answer_targets": answer_targets,
            "escalation_gate": {
                "escalation_allowed": bool(escalation_controller.get("escalation_allowed")),
                "followup_enabled": bool(followup_ask.get("enabled")),
                "recommended_option_ref": recommended_option_ref or None,
                "maximum_reachable_outcome": str(
                    escalation_controller.get(
                        "maximum_reachable_outcome",
                        analysis_result.get("maximum_reachable_outcome", outcome_mode),
                    )
                ),
                "stop_reason": str(
                    followup_ask.get("stop_reason")
                    or escalation_controller.get("stop_reason")
                    or analysis_result.get("stop_reason", "")
                ),
            },
            "execution_notes": execution_notes,
        }

    def _build_worker_prompt(self, ask_context_pack: Dict[str, object]) -> str:
        query = str(ask_context_pack.get("query", ""))
        work_packet = ask_context_pack.get("work_packet", {}) if isinstance(ask_context_pack.get("work_packet"), dict) else {}
        followup_ask = ask_context_pack.get("followup_ask", {}) if isinstance(ask_context_pack.get("followup_ask"), dict) else {}
        worker_mode = str(work_packet.get("worker_mode", "inspect_then_answer") or "inspect_then_answer")
        followup_note = (
            "Only consult `followup_ask` after the listed read_order is exhausted."
            if bool(followup_ask.get("enabled"))
            else "Do not open follow-up context; `followup_ask.enabled = false`."
        )
        return (
            f"Use `work_packet` as the operational contract for `{query}`. Read `read_order` strictly in order, keep the task inside "
            f"`primary_targets` and `supporting_targets`, and formulate only `allowed_claims`. Treat `disallowed_claims` as hard limits. "
            f"The current worker mode is `{worker_mode}`: if it is `answer_only`, stop after the decisive evidence and do not explore further; "
            "if it is `inspect_then_answer`, inspect only the listed targets before answering; if it is `inspect_then_compare`, compare only the "
            "listed candidates and stop without forcing uniqueness; if it is `inspect_then_refactor_plan`, limit yourself to focused refactor "
            f"targets without patching. {followup_note} Stop cleanly when `completion_criteria` says the bounded answer is complete."
        )

    def _build_worker_result_template(
        self,
        query: str,
        work_packet: Dict[str, object],
        analysis_result: Dict[str, object],
        followup_ask: Dict[str, object],
    ) -> Dict[str, object]:
        current_outcome = str(analysis_result.get("outcome_mode", "unproven") or "unproven")
        required_read_order_refs = [
            str(item.get("slice_ref", ""))
            for item in work_packet.get("read_order", [])
            if str(item.get("slice_ref", ""))
        ]
        required_primary_symbols = [
            str(item.get("symbol", ""))
            for item in work_packet.get("primary_targets", [])
            if str(item.get("symbol", ""))
        ]
        valid_stop_conditions = [
            str(item.get("kind", ""))
            for item in work_packet.get("stop_conditions", [])
            if str(item.get("kind", ""))
        ]
        return {
            "status": "ready_for_execution",
            "task": query,
            "worker_mode": str(work_packet.get("worker_mode", "")),
            "expected_outcome_ceiling": current_outcome,
            "minimum_honest_outcome": current_outcome,
            "default_completion_state": "ready_for_execution",
            "required_read_order_refs": required_read_order_refs,
            "required_primary_symbols": required_primary_symbols,
            "allowed_claims": list(work_packet.get("allowed_claims", [])),
            "disallowed_claims": list(work_packet.get("disallowed_claims", [])),
            "followup_allowed": bool(followup_ask.get("enabled")),
            "valid_stop_conditions": valid_stop_conditions,
            "supported_completion_states": list(WORKER_COMPLETION_STATES),
            "result_slots": {
                "inspected_slice_refs": [],
                "inspected_symbols": [],
                "used_claims": [],
                "final_outcome_mode": "",
                "final_claim": "",
                "supporting_refs": [],
                "stop_condition_hit": "",
                "completion_state": "ready_for_execution",
                "followup_used": False,
                "unresolved_points": [],
                "notes": [],
            },
        }

    def _build_worker_trace_template(
        self,
        worker_result_template: Dict[str, object],
    ) -> Dict[str, object]:
        return {
            "status": "ready_for_execution",
            "trace_slots": {
                "opened_slice_refs": [],
                "opened_symbols": [],
                "claim_attempts": [],
                "accepted_claims": [],
                "rejected_claims": [],
                "stop_condition_triggered": "",
                "completion_state": str(worker_result_template.get("default_completion_state", "ready_for_execution")),
                "followup_touched": False,
                "notes": [],
                "unresolved_points": [],
                "execution_time_hint": "",
            },
            "trace_expectations": {
                "required_read_order_refs": list(worker_result_template.get("required_read_order_refs", [])),
                "required_primary_symbols": list(worker_result_template.get("required_primary_symbols", [])),
                "maximum_allowed_outcome": str(worker_result_template.get("expected_outcome_ceiling", "")),
                "minimum_honest_outcome": str(worker_result_template.get("minimum_honest_outcome", "")),
                "allowed_claims": list(worker_result_template.get("allowed_claims", [])),
                "disallowed_claims": list(worker_result_template.get("disallowed_claims", [])),
                "followup_allowed": bool(worker_result_template.get("followup_allowed")),
            },
        }

    def _build_worker_validation_rules(
        self,
        work_packet: Dict[str, object],
        analysis_result: Dict[str, object],
        worker_result_template: Dict[str, object],
    ) -> List[Dict[str, object]]:
        forbidden = analysis_result.get("forbidden_overreach", {}) if isinstance(analysis_result.get("forbidden_overreach"), dict) else {}
        unsupported = {str(item) for item in forbidden.get("unsupported_claim_kinds", [])}
        rules: List[Dict[str, object]] = [
            {
                "rule_id": "must_respect_allowed_claims",
                "description": "Use only claim strings listed in `allowed_claims` for `result_slots.used_claims` and `result_slots.final_claim`.",
                "severity": "error",
                "applies_when": "always",
                "pass_condition": "Every emitted claim is copied from `allowed_claims`.",
                "fail_condition": "A claim appears that is not listed in `allowed_claims`.",
            },
            {
                "rule_id": "must_not_use_disallowed_claims",
                "description": "Never emit a claim string listed in `disallowed_claims`.",
                "severity": "error",
                "applies_when": "when `disallowed_claims` is non-empty",
                "pass_condition": "No emitted claim matches `disallowed_claims`.",
                "fail_condition": "A disallowed claim appears in `result_slots.used_claims` or `result_slots.final_claim`.",
            },
            {
                "rule_id": "must_not_exceed_outcome_ceiling",
                "description": "Do not raise `result_slots.final_outcome_mode` above `expected_outcome_ceiling`.",
                "severity": "error",
                "applies_when": "always",
                "pass_condition": "`final_outcome_mode` is less than or equal to `expected_outcome_ceiling`.",
                "fail_condition": "`final_outcome_mode` exceeds `expected_outcome_ceiling`.",
            },
            {
                "rule_id": "must_not_drop_below_minimum_honest_outcome",
                "description": "Do not return an outcome below the current bounded result.",
                "severity": "error",
                "applies_when": "always",
                "pass_condition": "`final_outcome_mode` is greater than or equal to `minimum_honest_outcome`.",
                "fail_condition": "`final_outcome_mode` drops below `minimum_honest_outcome`.",
            },
            {
                "rule_id": "must_set_final_outcome_for_terminal_result",
                "description": "Terminal worker results must set `result_slots.final_outcome_mode`.",
                "severity": "error",
                "applies_when": "when `completion_state` is terminal",
                "pass_condition": "`final_outcome_mode` is non-empty for any terminal worker result.",
                "fail_condition": "A terminal worker result omits `final_outcome_mode`.",
            },
            {
                "rule_id": "must_read_primary_slice_first",
                "description": "The first inspected slice must match the first `required_read_order_refs` entry.",
                "severity": "error",
                "applies_when": "when `required_read_order_refs` is non-empty and execution progressed beyond `ready_for_execution`",
                "pass_condition": "`inspected_slice_refs[0]` equals the first required read-order ref.",
                "fail_condition": "The worker skipped the first primary slice or inspected a different slice first.",
            },
            {
                "rule_id": "must_read_required_sequence_for_terminal_result",
                "description": "Terminal worker results must include the full `required_read_order_refs` sequence in order.",
                "severity": "error",
                "applies_when": "when `completion_state` is terminal and `required_read_order_refs` is non-empty",
                "pass_condition": "`required_read_order_refs` appears as an ordered subsequence inside `inspected_slice_refs`.",
                "fail_condition": "A required read-order ref is missing or appears out of order in a terminal worker result.",
            },
            {
                "rule_id": "must_cover_required_primary_symbols_for_terminal_result",
                "description": "Terminal worker results must record every `required_primary_symbols` entry in `result_slots.inspected_symbols`.",
                "severity": "error",
                "applies_when": "when `completion_state` is terminal and `required_primary_symbols` is non-empty",
                "pass_condition": "All required primary symbols appear in `inspected_symbols`.",
                "fail_condition": "A required primary symbol is missing from a terminal worker result.",
            },
            {
                "rule_id": "must_stop_when_completion_criteria_met",
                "description": "Completed or stopped results must cite one of the exported stop conditions.",
                "severity": "error",
                "applies_when": "when `completion_state` is a completed or stopped state",
                "pass_condition": "`stop_condition_hit` matches `valid_stop_conditions`.",
                "fail_condition": "The worker finished without referencing a valid stop condition.",
            },
        ]
        if not bool(worker_result_template.get("followup_allowed")):
            rules.append(
                {
                    "rule_id": "must_not_open_followup_when_disabled",
                    "description": "Follow-up use is forbidden when `followup_allowed = false`.",
                    "severity": "error",
                    "applies_when": "when `followup_allowed = false`",
                    "pass_condition": "`result_slots.followup_used = false`.",
                    "fail_condition": "The worker used follow-up evidence even though the gate was closed.",
                }
            )
        if str(analysis_result.get("outcome_mode", "")) == "ambiguous" or "uniqueness_claim_without_disambiguation" in unsupported:
            rules.append(
                {
                    "rule_id": "must_not_claim_uniqueness_while_ambiguous",
                    "description": "Ambiguous work packets may not collapse the result into a unique implementation or path.",
                    "severity": "error",
                    "applies_when": "when `expected_outcome_ceiling = ambiguous` or ambiguity refs are present",
                    "pass_condition": "`final_outcome_mode = ambiguous` and emitted claims stay inside the ambiguous allow-list.",
                    "fail_condition": "The worker returns a unique or stronger-than-ambiguous result without new evidence.",
                }
            )
        if "end_to_end_claim_without_direct_io" in unsupported:
            rules.append(
                {
                    "rule_id": "must_not_claim_direct_io_without_direct_evidence",
                    "description": "Direct I/O claims remain forbidden when the current bounded result lacks direct evidence.",
                    "severity": "error",
                    "applies_when": "when direct I/O is requested but `analysis_result` still marks it unsupported",
                    "pass_condition": "Claims stay inside `allowed_claims` and do not upgrade the current bounded result.",
                    "fail_condition": "The worker claims direct I/O even though no selected direct evidence span proves it.",
                }
            )
        return rules

    def _build_worker_result_prompt(self, ask_context_pack: Dict[str, object]) -> str:
        query = str(ask_context_pack.get("query", ""))
        work_packet = ask_context_pack.get("work_packet", {}) if isinstance(ask_context_pack.get("work_packet"), dict) else {}
        analysis_result = ask_context_pack.get("analysis_result", {}) if isinstance(ask_context_pack.get("analysis_result"), dict) else {}
        worker_result_template = (
            ask_context_pack.get("worker_result_template", {})
            if isinstance(ask_context_pack.get("worker_result_template"), dict)
            else {}
        )
        ceiling = str(worker_result_template.get("expected_outcome_ceiling", analysis_result.get("outcome_mode", "")) or "")
        return (
            f"Fill `worker_result_template` for `{query}` only after respecting `work_packet` and `analysis_result`. "
            "Keep `result_slots.used_claims` and `result_slots.final_claim` inside `allowed_claims`, never use "
            "`disallowed_claims`, and do not raise `result_slots.final_outcome_mode` above "
            f"`expected_outcome_ceiling = {ceiling}`. Record the exported read-order refs, required primary symbols, supporting refs, "
            "and a non-empty `result_slots.final_outcome_mode` before returning any terminal result. "
            "Set `followup_used = true` only if the gate is open, choose a `completion_state` from "
            "`supported_completion_states`, and do not mark a terminal result until the full `required_read_order_refs` "
            "sequence has been inspected in order and every `required_primary_symbols` entry has been recorded. If the current result is `unproven` or `ambiguous`, stop there "
            "cleanly instead of inventing a stronger claim."
        )

    def _build_worker_report_prompt(self, ask_context_pack: Dict[str, object]) -> str:
        query = str(ask_context_pack.get("query", ""))
        worker_result_template = (
            ask_context_pack.get("worker_result_template", {})
            if isinstance(ask_context_pack.get("worker_result_template"), dict)
            else {}
        )
        worker_trace_template = (
            ask_context_pack.get("worker_trace_template", {})
            if isinstance(ask_context_pack.get("worker_trace_template"), dict)
            else {}
        )
        ceiling = str(worker_result_template.get("expected_outcome_ceiling", "")) or "unproven"
        return (
            f"For `{query}`, keep `worker_trace_template` and `worker_result_template` separate. Record actual slice opens, symbol "
            "opens, and claim attempts in `worker_trace_template.trace_slots`, then fill `worker_result_template.result_slots` only "
            "inside the exported contract. Treat any invalidated claim attempt as rejected, do not hide violations, and do not treat "
            "a worker result as final until the validator has produced the derived `worker_result_report`. The current maximum bounded "
            f"outcome is `{ceiling}`; never let the final accepted result exceed that ceiling, and never rewrite rejected claims into "
            "an apparently valid summary."
        )

    def _build_result_prompt(self, ask_context_pack: Dict[str, object]) -> str:
        query = str(ask_context_pack.get("query", ""))
        analysis_result = ask_context_pack.get("analysis_result", {}) if isinstance(ask_context_pack.get("analysis_result"), dict) else {}
        outcome_mode = str(analysis_result.get("outcome_mode", "unproven") or "unproven")
        forbidden = analysis_result.get("forbidden_overreach", {}) if isinstance(analysis_result.get("forbidden_overreach"), dict) else {}
        unsupported = ", ".join(str(item) for item in forbidden.get("unsupported_claim_kinds", [])) or "none"
        controller = ask_context_pack.get("escalation_controller", {}) if isinstance(ask_context_pack.get("escalation_controller"), dict) else {}
        escalation_instruction = (
            "Only open `escalation_controller.recommended_option`"
            if bool(controller.get("escalation_allowed"))
            else "Do not open new escalation context"
        )
        return (
            f"Answer `{query}` by using `analysis_result` first. Treat `claim`, `minimal_basis`, and `evidence_refs` as the "
            f"maximum allowed answer surface for the current `{outcome_mode}` result. Do not exceed "
            f"`forbidden_overreach.unsupported_claim_kinds = [{unsupported}]`. {escalation_instruction}, "
            "`analysis_plan`, or broader deferred context if a wider answer is explicitly requested. If the result is "
            "`partial`, `unproven`, or `ambiguous`, stop at that bounded conclusion instead of inferring the missing behavior."
        )

    def _build_ask_prompt(self, ask_context_pack: Dict[str, object]) -> str:
        query = str(ask_context_pack.get("query", ""))
        return (
            f"Answer the question `{query}` by checking `work_packet` first for the strict worker contract, then `analysis_result`, "
            "then `escalation_controller`, then `followup_ask`, then `analysis_plan`, and only then using selected_flow_summaries, selected_flow_chains, "
            "selected_evidence_paths, selected_semantic_refs, and selected_slices in that order. Prefer direct semantic "
            "evidence over contained semantics, executable symbols over containers, and high-confidence paths over weaker "
            "hints. Treat any ambiguity_watchlist item as unresolved until a bounded escalation option is explicitly allowed."
        )

    def _build_analyst_prompt(self, ask_context_pack: Dict[str, object]) -> str:
        query = str(ask_context_pack.get("query", ""))
        analysis_plan = ask_context_pack.get("analysis_plan", {}) if isinstance(ask_context_pack.get("analysis_plan"), dict) else {}
        recommended_outcome_mode = str(analysis_plan.get("recommended_outcome_mode", "partial") or "partial")
        return (
            f"Work the analysis_plan for `{query}` in order. After each step, decide whether `confirmed`, `partial`, "
            f"`unproven`, or `ambiguous` is already justified; the recommended default is `{recommended_outcome_mode}`. "
            "Use selected_flow_summaries, selected_flow_chains, selected_evidence_paths, selected_semantic_refs, and "
            "selected_slices before opening any branch_requests or deferred_requests. Do not claim a flow, guard, side "
            "effect, or external interaction unless the current step has direct evidence for it. Compile `analysis_result` "
            "once the matching candidate_outcome is satisfied, then consult `escalation_controller` before opening any "
            "new evidence and stop early whenever escalation is not explicitly allowed."
        )

    def _rank_ask_candidates(
        self,
        analysis: Dict[str, object],
        inbound: Dict[str, List],
    ) -> Tuple[List[Dict[str, object]], Dict[str, float], Dict[str, Dict[str, object]], List[Dict[str, object]]]:
        mentioned_symbols = set(str(item) for item in analysis.get("mentioned_symbols", []))
        mentioned_files = set(str(item) for item in analysis.get("mentioned_files", []))

        def matches_query_focus_node(node_id: str) -> bool:
            return node_id in mentioned_symbols or (
                node_id in self.nodes and self.nodes[node_id].file in mentioned_files
            )

        def matches_query_focus_path(path: Dict[str, object]) -> bool:
            return any(matches_query_focus_node(node_id) for node_id in self._ordered_path_nodes(path))

        base_candidates = [
            self._build_query_target_candidate(node_id, analysis, inbound)
            for node_id in sorted(self.nodes)
        ]
        base_candidates = [
            item
            for item in base_candidates
            if (
                float(item["base_selection_score"]) > 0.0
                or item["direct_semantic_match"]
                or item["contained_semantic_match"]
                or item["ambiguity_relevance"]
            )
        ]
        base_candidates.sort(
            key=lambda item: (
                -float(item["base_selection_score"]),
                0 if self.nodes[item["node_id"]].kind in SEMANTIC_EXECUTABLE_KINDS else 1,
                str(item["node_id"]),
            )
        )
        query_paths = self._build_query_evidence_paths(base_candidates, inbound, analysis, limit=10)
        path_bonus_by_node: Dict[str, float] = defaultdict(float)
        best_path_by_node: Dict[str, Dict[str, object]] = {}
        for path in query_paths:
            risk_node = str(path.get("risk_node", ""))
            score = float(path.get("query_match_score", 0.0))
            if score > path_bonus_by_node.get(risk_node, 0.0):
                path_bonus_by_node[risk_node] = score
                best_path_by_node[risk_node] = path

        ranked_targets: List[Dict[str, object]] = []
        for item in base_candidates:
            node_id = str(item["node_id"])
            final_score = float(item["base_selection_score"]) + float(path_bonus_by_node.get(node_id, 0.0))
            payload = dict(item)
            payload["evidence_path_match"] = node_id in best_path_by_node
            payload["evidence_path_score"] = round(float(path_bonus_by_node.get(node_id, 0.0)), 2)
            payload["best_evidence_path_id"] = str(best_path_by_node[node_id]["path_id"]) if node_id in best_path_by_node else ""
            payload["selection_score"] = round(final_score, 2)
            payload["why_selected"] = list(payload["match_reasons"][:4]) or ["Selected because it best matches the query-scoped evidence heuristics."]
            ranked_targets.append(payload)

        ranked_targets.sort(
            key=lambda item: (
                -float(item["selection_score"]),
                0 if self.nodes[item["node_id"]].kind in SEMANTIC_EXECUTABLE_KINDS else 1,
                -float(self.nodes[item["node_id"]].risk_score),
                str(item["node_id"]),
            )
        )
        for rank, item in enumerate(ranked_targets, start=1):
            item["rank"] = rank

        return ranked_targets, path_bonus_by_node, best_path_by_node, query_paths

    def _select_ask_slices(
        self,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        query_paths: List[Dict[str, object]],
        best_path_by_node: Dict[str, Dict[str, object]],
        query_ambiguity_watchlist: List[Dict[str, object]],
        inbound: Dict[str, List],
        line_budget: int,
    ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], Dict[str, List], List[Dict[str, object]]]:
        mentioned_symbols = set(str(item) for item in analysis.get("mentioned_symbols", []))
        mentioned_files = set(str(item) for item in analysis.get("mentioned_files", []))

        def matches_query_focus_node(node_id: str) -> bool:
            return node_id in mentioned_symbols or (
                node_id in self.nodes and self.nodes[node_id].file in mentioned_files
            )

        def matches_query_focus_path(path: Dict[str, object]) -> bool:
            return any(matches_query_focus_node(node_id) for node_id in self._ordered_path_nodes(path))

        selected_paths = [
            path
            for path in query_paths
            if float(path.get("query_match_score", 0.0)) > 0.0
        ][:5]
        if mentioned_symbols or mentioned_files:
            focused_paths = [path for path in selected_paths if matches_query_focus_path(path)]
            if focused_paths:
                selected_paths = focused_paths
        if not selected_paths and ranked_targets[:1]:
            fallback = best_path_by_node.get(str(ranked_targets[0]["node_id"]))
            if fallback is not None:
                selected_paths = [fallback]

        path_refs_by_anchor = self._path_refs_by_anchor(selected_paths)
        selected_semantic_refs: List[Dict[str, object]] = []
        for item in ranked_targets[:8]:
            node_id = str(item["node_id"])
            direct_refs = self._query_relevant_semantic_refs(
                list(item.get("direct_semantic_refs", [])),
                set(str(signal) for signal in item.get("direct_semantic_match", [])),
                limit=3,
            )
            if direct_refs:
                for ref in direct_refs:
                    selected_semantic_refs.append({"node_id": node_id, "match_type": "direct", **ref})
                continue
            contained_refs = self._query_relevant_semantic_refs(
                list(item.get("contained_semantic_refs", [])),
                set(str(signal) for signal in item.get("contained_semantic_match", [])),
                limit=2,
            )
            for ref in contained_refs:
                selected_semantic_refs.append({"node_id": node_id, "match_type": "contained", **ref})
        selected_semantic_refs = self._dedupe_object_list(selected_semantic_refs)[:12]

        slice_specs: List[Dict[str, object]] = []
        used_lines = 0
        primary_budget = max(1, int(line_budget * 0.72))
        selected_target_ids: Set[str] = set()
        primary_targets = list(ranked_targets[:10])
        if mentioned_symbols or mentioned_files:
            focused_targets = [
                item
                for item in primary_targets
                if matches_query_focus_node(str(item["node_id"]))
            ]
            if focused_targets:
                primary_targets = focused_targets
        if len(set(str(item) for item in analysis.get("matched_semantic_signals", []))) > 1:
            focused_targets = [
                item
                for item in primary_targets
                if (
                    float(item.get("direct_semantic_coverage", 0.0)) >= 0.99
                    or float(item.get("contained_semantic_coverage", 0.0)) >= 0.99
                    or bool(item.get("evidence_path_match"))
                    or bool(item.get("ambiguity_relevance"))
                    or bool(item.get("has_strong_query_anchor"))
                )
            ]
            if focused_targets:
                primary_targets = focused_targets
        for item in primary_targets[:6]:
            node_id = str(item["node_id"])
            focus_refs = list(item.get("direct_semantic_refs", []))
            if not focus_refs and item.get("contained_semantic_match") and not item.get("direct_semantic_match"):
                focus_refs = list(item.get("contained_semantic_refs", []))[:2]
            spec = self._build_query_slice_spec(
                node_id=node_id,
                why=list(item["why_selected"]) + ["Query-scoped primary evidence slice."],
                selection_score=float(item["selection_score"]),
                selection_confidence_label=str(item.get("best_support_label", "") or "medium"),
                supporting_edges=self._support_edges_for_node(node_id, inbound, limit=2),
                ambiguity_flags=[],
                role="query_target",
                evidence_path_refs=[str(item.get("best_evidence_path_id", ""))] if item.get("best_evidence_path_id") else [],
                semantic_refs=focus_refs,
            )
            line_count = int(spec["end_line"]) - int(spec["start_line"]) + 1
            if used_lines + line_count > primary_budget and selected_target_ids:
                continue
            slice_specs.append(spec)
            used_lines += line_count
            selected_target_ids.add(node_id)

        for path in selected_paths:
            for item in path.get("recommended_slices", [])[1:]:
                node_id = str(item.get("anchor_symbol", ""))
                if node_id not in self.nodes or node_id in selected_target_ids:
                    continue
                path_match_refs = self._query_relevant_semantic_refs(
                    self._semantic_refs_for_node(node_id, limit=3),
                    set(str(signal) for signal in path.get("query_match_signals", [])),
                    limit=3,
                )
                spec = self._build_query_slice_spec(
                    node_id=node_id,
                    why=[
                        f"Support slice for query path `{path['path_id']}` ({path['path_kind']}).",
                        *list(path.get("query_match_reasons", []))[:2],
                    ],
                    selection_score=float(path.get("query_match_score", 0.0)),
                    selection_confidence_label=str(path.get("path_confidence_label", "") or "medium"),
                    supporting_edges=self._support_edges_for_node(node_id, inbound, limit=1),
                    ambiguity_flags=[],
                    role="support",
                    evidence_path_refs=[str(path["path_id"])],
                    semantic_refs=path_match_refs,
                )
                line_count = int(spec["end_line"]) - int(spec["start_line"]) + 1
                if used_lines + line_count > line_budget:
                    continue
                slice_specs.append(spec)
                used_lines += line_count
                selected_target_ids.add(node_id)

        if bool(analysis.get("ambiguity_sensitive")):
            for item in query_ambiguity_watchlist[:2]:
                source_node = str(item["source_node"])
                if source_node not in self.nodes or source_node in selected_target_ids:
                    continue
                spec = self._build_query_slice_spec(
                    node_id=source_node,
                    why=[
                        "Ambiguity-focused slice for the query.",
                        str(item.get("resolution_reason", "")),
                    ],
                    selection_score=float(item.get("query_match_score", 0.0)),
                    selection_confidence_label=str(item.get("confidence_label", "") or "ambiguous"),
                    supporting_edges=[],
                    ambiguity_flags=[item],
                    role="ambiguity_context",
                    evidence_path_refs=[],
                    semantic_refs=[],
                )
                line_count = int(spec["end_line"]) - int(spec["start_line"]) + 1
                if used_lines + line_count > line_budget:
                    continue
                slice_specs.append(spec)
                used_lines += line_count
                selected_target_ids.add(source_node)

        return slice_specs, selected_paths, path_refs_by_anchor, selected_semantic_refs

    def _build_ask_flow_data(
        self,
        analysis: Dict[str, object],
        ranked_targets: List[Dict[str, object]],
        merged_slices: List[Dict[str, object]],
        selected_paths: List[Dict[str, object]],
    ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
        selected_flow_summaries = self._build_selected_flow_summaries(
            ranked_targets,
            merged_slices,
            selected_paths,
            analysis,
            limit=6,
        )
        selected_flow_chains = self._build_selected_flow_chains(
            analysis,
            ranked_targets,
            selected_paths,
            merged_slices,
            selected_flow_summaries,
            limit=4,
        )
        flow_gaps = self._build_flow_gaps(
            analysis,
            ranked_targets,
            selected_flow_summaries,
            selected_flow_chains,
            limit=4,
        )
        return selected_flow_summaries, selected_flow_chains, flow_gaps

    def _build_ask_context_pack(
        self,
        query: str,
        line_budget: int = 110,
    ) -> Dict[str, object]:
        inbound = self._inbound_adj()
        analysis = self._build_query_analysis(query)
        ranked_targets, path_bonus_by_node, best_path_by_node, query_paths = (
            self._rank_ask_candidates(analysis, inbound)
        )

        query_ambiguity_watchlist = self._build_query_ambiguity_watchlist(analysis, ranked_targets, limit=4)
        slice_specs, selected_paths, path_refs_by_anchor, selected_semantic_refs = self._select_ask_slices(
            analysis,
            ranked_targets,
            query_paths,
            best_path_by_node,
            query_ambiguity_watchlist,
            inbound,
            line_budget,
        )

        merged_slices = self._merge_slice_specs(slice_specs)
        merged_slices = [self._annotate_slice_path_refs(spec, path_refs_by_anchor) for spec in merged_slices]
        selected_symbols = {symbol for spec in merged_slices for symbol in spec.get("symbols", [])}
        selected_flow_summaries, selected_flow_chains, flow_gaps = self._build_ask_flow_data(
            analysis,
            ranked_targets,
            merged_slices,
            selected_paths,
        )

        deferred: List[Dict[str, object]] = []
        if bool(analysis.get("ambiguity_sensitive")):
            for item in query_ambiguity_watchlist[:2]:
                deferred.append(self._build_deferred_request_for_ambiguity(item))
        for item in ranked_targets[:4]:
            node_id = str(item["node_id"])
            if node_id not in selected_symbols:
                continue
            best_path = best_path_by_node.get(node_id)
            if best_path is not None:
                request = self._build_deferred_request_for_path(best_path, selected_symbols)
                if request is not None:
                    deferred.append(request)
        semantic_watchlist = self._build_semantic_watchlist(limit=8)
        selected_watchlist = [item for item in semantic_watchlist if item["symbol"] in selected_symbols]
        for item in selected_watchlist[:2]:
            request = self._build_deferred_request_for_semantic_item(item, merged_slices)
            if request is not None:
                deferred.append(request)
        deferred = self._dedupe_object_list(deferred)[:6]
        analysis_plan = self._build_analysis_plan(
            query,
            analysis,
            ranked_targets,
            merged_slices,
            selected_paths,
            selected_flow_summaries,
            selected_flow_chains,
            flow_gaps,
            query_ambiguity_watchlist,
            deferred,
        )
        analysis_result = self._build_analysis_result(
            query,
            analysis,
            ranked_targets,
            merged_slices,
            selected_semantic_refs,
            selected_flow_summaries,
            selected_flow_chains,
            selected_paths,
            flow_gaps,
            query_ambiguity_watchlist,
            deferred,
            analysis_plan,
        )
        escalation_controller = self._build_escalation_controller(
            analysis,
            ranked_targets,
            merged_slices,
            selected_paths,
            selected_flow_chains,
            flow_gaps,
            query_ambiguity_watchlist,
            deferred,
            analysis_result,
        )
        analysis_result["escalation_status"] = (
            "not_needed"
            if analysis_result.get("outcome_mode") == "confirmed"
            else ("allowed" if escalation_controller.get("escalation_allowed") else "stopped_no_bounded_gain")
        )
        analysis_result["stop_reason"] = escalation_controller.get("stop_reason")
        analysis_result["maximum_reachable_outcome"] = escalation_controller.get("maximum_reachable_outcome")
        analysis_result["recommended_escalation_option_ref"] = (
            escalation_controller["recommended_option"]["option_id"]
            if isinstance(escalation_controller.get("recommended_option"), dict)
            else None
        )
        followup_ask = self._build_followup_ask(
            query,
            analysis,
            analysis_result,
            escalation_controller,
        )
        analysis_result["followup_status"] = "enabled" if followup_ask.get("enabled") else "disabled"
        analysis_result["followup_ref"] = (
            str(followup_ask.get("source_option_ref", "")) if followup_ask.get("enabled") else None
        )
        work_packet = self._build_work_packet(
            query,
            analysis,
            analysis_plan,
            analysis_result,
            merged_slices,
            selected_flow_chains,
            selected_paths,
            flow_gaps,
            query_ambiguity_watchlist,
            escalation_controller,
            followup_ask,
        )
        worker_result_template = self._build_worker_result_template(
            query,
            work_packet,
            analysis_result,
            followup_ask,
        )
        worker_trace_template = self._build_worker_trace_template(worker_result_template)
        worker_validation_rules = self._build_worker_validation_rules(
            work_packet,
            analysis_result,
            worker_result_template,
        )

        ask_context_pack = {
            "query": query,
            "query_analysis": analysis,
            "ranked_targets": [
                {
                    "node_id": item["node_id"],
                    "rank": item["rank"],
                    "file": item["file"],
                    "lines": item["lines"],
                    "kind": item["kind"],
                    "why_selected": list(item["why_selected"]),
                    "match_reasons": list(item["match_reasons"]),
                    "direct_semantic_match": list(item["direct_semantic_match"]),
                    "contained_semantic_match": list(item["contained_semantic_match"]),
                    "evidence_path_match": bool(item["evidence_path_match"]),
                    "ambiguity_relevance": bool(item["ambiguity_relevance"]),
                    "selection_score": float(item["selection_score"]),
                }
                for item in ranked_targets[:10]
            ],
            "selected_slices": merged_slices,
            "selected_evidence_paths": selected_paths,
            "selected_semantic_refs": selected_semantic_refs,
            "selected_flow_summaries": selected_flow_summaries,
            "selected_flow_chains": selected_flow_chains,
            "flow_gaps": flow_gaps,
            "ambiguity_watchlist": query_ambiguity_watchlist,
            "deferred_requests": deferred,
            "analysis_plan": analysis_plan,
            "analysis_result": analysis_result,
            "escalation_controller": escalation_controller,
            "followup_ask": followup_ask,
            "work_packet": work_packet,
            "worker_result_template": worker_result_template,
            "worker_trace_template": worker_trace_template,
            "worker_validation_rules": worker_validation_rules,
            "selection_strategy": (
                "Rank executable nodes first by lexical query match, direct semantic matches, path evidence, "
                "confidence quality, and ambiguity relevance. Build compact behavioral flow summaries from direct "
                "semantic evidence, and only fall back to contained semantics or container nodes when direct executable "
                "evidence is weaker or absent."
            ),
            "budget": {
                "line_budget": max(20, line_budget),
                "selected_line_count": sum(int(spec["end_line"]) - int(spec["start_line"]) + 1 for spec in merged_slices),
                "selected_target_count": len(selected_symbols),
                "selected_path_count": len(selected_paths),
                "selected_flow_summary_count": len(selected_flow_summaries),
                "selected_flow_chain_count": len(selected_flow_chains),
                "deferred_request_count": len(deferred),
            },
        }
        ask_context_pack["ask_prompt"] = self._build_ask_prompt(ask_context_pack)
        ask_context_pack["analyst_prompt"] = self._build_analyst_prompt(ask_context_pack)
        ask_context_pack["result_prompt"] = self._build_result_prompt(ask_context_pack)
        ask_context_pack["escalation_prompt"] = self._build_escalation_prompt(ask_context_pack)
        ask_context_pack["followup_prompt"] = self._build_followup_prompt(ask_context_pack)
        ask_context_pack["worker_prompt"] = self._build_worker_prompt(ask_context_pack)
        ask_context_pack["worker_result_prompt"] = self._build_worker_result_prompt(ask_context_pack)
        ask_context_pack["worker_report_prompt"] = self._build_worker_report_prompt(ask_context_pack)
        return ask_context_pack

    def _language_for_file(self, rel_path: str) -> str:
        suffix = Path(rel_path).suffix.lower()
        return {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "jsx",
            ".ts": "typescript",
            ".tsx": "tsx",
            ".json": "json",
            ".toml": "toml",
            ".yml": "yaml",
            ".yaml": "yaml",
            ".xml": "xml",
            ".gradle": "groovy",
            ".md": "markdown",
            ".txt": "text",
            ".cfg": "ini",
            ".go": "go",
            ".java": "java",
            ".rs": "rust",
        }.get(suffix, "text")

    def _inbound_adj(self) -> Dict[str, Set[str]]:
        inbound: Dict[str, Set[str]] = defaultdict(set)
        for src, dsts in self.adj.items():
            for dst in dsts:
                inbound[dst].add(src)
        return inbound

    def _edge_outcome(self, source: str, target: str) -> ResolutionOutcome:
        if (source, target) in self.edge_resolution:
            return self.edge_resolution[(source, target)]
        return self._resolution(
            target=target,
            kind="heuristic",
            reason="Resolved internal edge without explicit provenance.",
        )

    def _dedupe_object_list(self, items: List[Dict[str, object]]) -> List[Dict[str, object]]:
        seen: Set[str] = set()
        out: List[Dict[str, object]] = []
        for item in items:
            key = json.dumps(item, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def _build_confidence_summary(self) -> Dict[str, object]:
        by_label: Dict[str, int] = defaultdict(int)
        by_kind: Dict[str, int] = defaultdict(int)
        ambiguity_count = 0
        unresolved_detail_count = 0

        for outcome in self.edge_resolution.values():
            if outcome.confidence_label:
                by_label[outcome.confidence_label] += 1
            if outcome.resolution_kind:
                by_kind[outcome.resolution_kind] += 1

        for node in self.nodes.values():
            unresolved_detail_count += len(node.unresolved_call_details)
            for detail in node.unresolved_call_details.values():
                if detail.get("resolution_kind") == "ambiguous_candidates":
                    ambiguity_count += 1

        return {
            "edge_count_by_confidence_label": {key: by_label[key] for key in sorted(by_label)},
            "edge_count_by_resolution_kind": {key: by_kind[key] for key in sorted(by_kind)},
            "ambiguity_count": ambiguity_count,
            "unresolved_call_detail_count": unresolved_detail_count,
        }

    def _semantic_bundle_bonus(self, node: SymbolNode) -> float:
        if not node.semantic_signals:
            return 0.0
        bonus = node.semantic_weight * 1.7
        if any(signal in SEMANTIC_BOUNDARY_SIGNALS for signal in node.semantic_signals):
            bonus += 4.0
        if any(signal in SEMANTIC_CRITICAL_SIGNALS for signal in node.semantic_signals):
            bonus += 2.0
        if node.unresolved_call_details and any(signal in SEMANTIC_CRITICAL_SIGNALS for signal in node.semantic_signals):
            bonus += 1.5
        if node.kind == "module":
            bonus -= 1.0
        return round(max(0.0, bonus), 2)

    def _semantic_refs_for_file(self, rel_path: str, limit: int = 4) -> List[Dict[str, object]]:
        refs: List[Dict[str, object]] = []
        for node in self.nodes.values():
            if node.file != rel_path:
                continue
            if self._semantic_node_is_shadowed(node):
                continue
            refs.extend(list(node.semantic_evidence_spans))
        return self._dedupe_semantic_refs(refs, limit=limit)

    def _semantic_node_is_shadowed(self, node: SymbolNode) -> bool:
        if not node.semantic_signals:
            return False
        kind_rank = {
            "method": 0,
            "function": 0,
            "async_function": 0,
            "class": 1,
            "interface": 1,
            "enum": 1,
            "module": 2,
        }
        node_signals = set(node.semantic_signals)
        node_span = max(1, int(node.lines[1]) - int(node.lines[0]) + 1)
        for other in self.nodes.values():
            if other.node_id == node.node_id or other.file != node.file or not other.semantic_signals:
                continue
            other_signals = set(other.semantic_signals)
            other_span = max(1, int(other.lines[1]) - int(other.lines[0]) + 1)
            if other_signals >= node_signals and (
                kind_rank.get(other.kind, 9) < kind_rank.get(node.kind, 9)
                or (
                    kind_rank.get(other.kind, 9) == kind_rank.get(node.kind, 9)
                    and other_span < node_span
                )
            ):
                return True
        return False

    def _build_semantic_candidates(self, limit: int = 10) -> List[Dict[str, object]]:
        candidates: List[Dict[str, object]] = []
        for node_id, node in self.nodes.items():
            if not node.semantic_signals:
                continue
            if self._semantic_node_is_shadowed(node):
                continue
            reasons: List[str] = []
            if any(signal in SEMANTIC_BOUNDARY_SIGNALS for signal in node.semantic_signals):
                reasons.append("Boundary-facing symbol with explicit semantic evidence.")
            if any(signal in SEMANTIC_SIDE_EFFECT_SIGNALS for signal in node.semantic_signals):
                reasons.append("Contains state mutation or side-effectful behavior.")
            if any(signal in SEMANTIC_GUARD_SIGNALS for signal in node.semantic_signals):
                reasons.append("Contains validation, authorization, or error-handling logic.")
            if node.risk_score >= 45.0:
                reasons.append("Also appears structurally important enough to matter for triage.")
            if node.unresolved_call_details:
                reasons.append("Semantic interpretation may still depend on unresolved structural ambiguity.")
            priority = (
                (node.semantic_weight * 3.0)
                + min(node.risk_score / 12.0, 8.0)
                + (3.0 if any(signal in SEMANTIC_BOUNDARY_SIGNALS for signal in node.semantic_signals) else 0.0)
                + (2.0 if any(signal in SEMANTIC_EXTERNAL_IO_SIGNALS for signal in node.semantic_signals) else 0.0)
                - (1.0 if node.kind == "module" else 0.0)
            )
            candidates.append(
                {
                    "node_id": node_id,
                    "file": node.file,
                    "lines": node.lines,
                    "kind": node.kind,
                    "language": node.language,
                    "risk_score": node.risk_score,
                    "semantic_weight": node.semantic_weight,
                    "semantic_signals": list(node.semantic_signals),
                    "semantic_summary": dict(node.semantic_summary),
                    "semantic_evidence_spans": self._semantic_refs_for_node(node_id, limit=4),
                    "contained_semantic_signals": list(node.contained_semantic_signals),
                    "contained_semantic_summary": dict(node.contained_semantic_summary),
                    "contained_semantic_refs": self._contained_semantic_refs_for_node(node_id, limit=4),
                    "why_selected": reasons or ["Semantic evidence is present on this symbol."],
                    "ambiguity_count": len(node.unresolved_call_details),
                    "selection_score": round(priority, 2),
                }
            )
        candidates.sort(
            key=lambda item: (
                -float(item["selection_score"]),
                -float(item["semantic_weight"]),
                -float(item["risk_score"]),
                str(item["node_id"]),
            )
        )
        return candidates[:limit]

    def _build_semantic_watchlist(self, limit: int = 8) -> List[Dict[str, object]]:
        watchlist: List[Dict[str, object]] = []
        for node_id, node in self.nodes.items():
            if not node.semantic_signals:
                continue
            if self._semantic_node_is_shadowed(node):
                continue
            reasons: List[str] = []
            signals = set(node.semantic_signals)
            if node.unresolved_call_details and signals & SEMANTIC_CRITICAL_SIGNALS:
                reasons.append("Semantically important node still has unresolved structural ambiguity.")
            if "state_mutation" in signals and signals & SEMANTIC_EXTERNAL_IO_SIGNALS:
                reasons.append("Combines state mutation with external side effects.")
            if "auth_guard" in signals and (signals & SEMANTIC_EXTERNAL_IO_SIGNALS or "input_boundary" in signals):
                reasons.append("Authorization logic sits on a boundary or side-effect path.")
            if "error_handling" in signals and signals & SEMANTIC_EXTERNAL_IO_SIGNALS:
                reasons.append("Side-effectful code path relies on explicit error handling.")
            if "process_io" in signals:
                reasons.append("Process execution is operationally sensitive.")
            if not reasons:
                continue
            refs = self._semantic_refs_for_node(node_id, limit=3)
            target_ref = refs[0] if refs else {"file": node.file, "lines": node.lines, "signal": ""}
            watchlist.append(
                {
                    "symbol": node_id,
                    "file": node.file,
                    "lines": node.lines,
                    "semantic_signals": list(node.semantic_signals),
                    "semantic_summary": dict(node.semantic_summary),
                    "semantic_evidence_spans": refs,
                    "contained_semantic_signals": list(node.contained_semantic_signals),
                    "contained_semantic_summary": dict(node.contained_semantic_summary),
                    "ambiguity_count": len(node.unresolved_call_details),
                    "why": reasons,
                    "recommended_next_evidence_target": {
                        "file": target_ref["file"],
                        "lines": target_ref["lines"],
                        "signal": target_ref.get("signal", ""),
                        "why": target_ref.get("reason", ""),
                    },
                }
            )
        watchlist.sort(
            key=lambda item: (
                -float(self.nodes[item["symbol"]].semantic_weight),
                -float(self.nodes[item["symbol"]].risk_score),
                str(item["symbol"]),
            )
        )
        return watchlist[:limit]

    def _build_semantic_overview(self, limit: int = 8) -> Dict[str, object]:
        direct_by_signal: Dict[str, int] = defaultdict(int)
        contained_by_signal: Dict[str, int] = defaultdict(int)
        by_file: Dict[str, Dict[str, object]] = {}
        for node in self.nodes.values():
            shadowed = self._semantic_node_is_shadowed(node)
            if not shadowed:
                for signal in node.semantic_signals:
                    direct_by_signal[signal] += 1
            if (not node.semantic_signals or shadowed) and not node.semantic_evidence_spans:
                continue
            current = by_file.setdefault(
                node.file,
                {
                    "file": node.file,
                    "contained_refs": [],
                    "direct_semantic_weight": 0.0,
                    "contained_signals": set(),
                    "direct_signals": set(),
                    "symbol_count": 0,
                },
            )
            if node.semantic_signals and not shadowed:
                current["direct_semantic_weight"] += node.semantic_weight
                current["direct_signals"].update(node.semantic_signals)
                current["symbol_count"] += 1
            if not shadowed:
                current["contained_refs"].extend(list(node.semantic_evidence_spans))
        for item in by_file.values():
            contained_refs = self._dedupe_semantic_refs(list(item["contained_refs"]), limit=24)
            item["contained_refs"] = contained_refs
            item["contained_signals"] = set(str(ref.get("signal", "")) for ref in contained_refs if ref.get("signal"))
            item["contained_semantic_weight"] = round(
                sum(SEMANTIC_SIGNAL_WEIGHTS.get(signal, 0.0) for signal in item["contained_signals"]),
                2,
            )
            for signal in item["contained_signals"]:
                contained_by_signal[signal] += 1
        boundary_files = sorted(
            (
                {
                    "file": item["file"],
                    "contained_semantic_weight": round(float(item["contained_semantic_weight"]), 2),
                    "direct_semantic_weight": round(float(item["direct_semantic_weight"]), 2),
                    "contained_semantic_signals": self._sort_semantic_signals(item["contained_signals"]),
                    "direct_semantic_signals": self._sort_semantic_signals(item["direct_signals"]),
                    "contained_semantic_refs": self._dedupe_semantic_refs(list(item["contained_refs"]), limit=4),
                    "symbol_count": int(item["symbol_count"]),
                }
                for item in by_file.values()
                if item["contained_semantic_weight"] > 0.0 or item["direct_semantic_weight"] > 0.0
            ),
            key=lambda item: (-float(item["contained_semantic_weight"]), -float(item["direct_semantic_weight"]), -int(item["symbol_count"]), str(item["file"])),
        )
        return {
            "aggregation_scope": "contained_descendant_semantics_for_file_view",
            "direct_node_count_by_signal": {key: direct_by_signal[key] for key in sorted(direct_by_signal)},
            "contained_file_count_by_signal": {key: contained_by_signal[key] for key in sorted(contained_by_signal)},
            "files_by_contained_semantic_weight": boundary_files[:limit],
        }

    def _build_semantic_entrypoints(self, limit: int = 8) -> List[Dict[str, object]]:
        candidates: List[Dict[str, object]] = []
        for node_id, node in self.nodes.items():
            if not node.semantic_signals:
                continue
            if self._semantic_node_is_shadowed(node):
                continue
            if not (set(node.semantic_signals) & (SEMANTIC_BOUNDARY_SIGNALS | SEMANTIC_EXTERNAL_IO_SIGNALS | {"auth_guard", "validation_guard"})):
                continue
            candidates.append(
                {
                    "symbol": node_id,
                    "file": node.file,
                    "lines": node.lines,
                    "language": node.language,
                    "semantic_signals": list(node.semantic_signals),
                    "semantic_weight": node.semantic_weight,
                    "risk_score": node.risk_score,
                    "semantic_evidence_spans": self._semantic_refs_for_node(node_id, limit=3),
                    "contained_semantic_signals": list(node.contained_semantic_signals),
                    "contained_semantic_summary": dict(node.contained_semantic_summary),
                }
            )
        candidates.sort(
            key=lambda item: (
                -float(item["semantic_weight"]),
                -float(item["risk_score"]),
                str(item["symbol"]),
            )
        )
        return candidates[:limit]

    def _slice_covers_lines(
        self,
        slices: List[Dict[str, object]],
        file_name: str,
        lines: List[int],
    ) -> bool:
        if not lines:
            return False
        start_line = int(lines[0])
        end_line = int(lines[1]) if len(lines) > 1 else start_line
        return any(
            str(spec.get("file", "")) == file_name
            and int(spec.get("start_line", 0)) <= start_line
            and int(spec.get("end_line", 0)) >= end_line
            for spec in slices
        )

    def _build_deferred_request_for_semantic_item(
        self,
        item: Dict[str, object],
        context_slices: List[Dict[str, object]],
    ) -> Optional[Dict[str, object]]:
        refs = list(item.get("semantic_evidence_spans", []))
        if not refs:
            return None
        target_ref = next(
            (
                ref
                for ref in refs
                if not self._slice_covers_lines(
                    context_slices,
                    str(ref["file"]),
                    list(ref.get("lines", [])),
                )
            ),
            None,
        )
        if target_ref is None:
            return None
        signal = str(target_ref.get("signal", ""))
        return {
            "type": "semantic_followup",
            "symbol": item["symbol"],
            "signals": list(item.get("semantic_signals", []))[:4],
            "confidence_gate": "only_if_this_semantic_signal_changes_the_decision",
            "request": (
                f"Open only `{target_ref['file']}:{target_ref['lines'][0]}-{target_ref['lines'][1]}` "
                f"to validate the `{signal}` evidence."
            ),
            "targets": [
                {
                    "file": target_ref["file"],
                    "lines": target_ref["lines"],
                    "signal": signal,
                    "why": target_ref.get("reason", ""),
                }
            ],
            "why": "; ".join(str(reason) for reason in item.get("why", []) if reason),
        }

    def _support_edge_payload(self, source: str, target: str, direction: str, focus_node: str) -> Dict[str, object]:
        outcome = self._edge_outcome(source, target)
        other = target if source == focus_node else source
        other_node = self.nodes[other]
        return {
            "source": source,
            "target": target,
            "direction": direction,
            "other_node": other,
            "other_file": other_node.file,
            "other_lines": other_node.lines,
            "kinds": sorted(self.edge_kinds.get((source, target), set())),
            "confidence_score": outcome.confidence_score,
            "confidence_label": outcome.confidence_label,
            "resolution_kind": outcome.resolution_kind,
            "resolution_reason": outcome.resolution_reason,
        }

    def _support_edges_for_node(
        self,
        node_id: str,
        inbound: Dict[str, Set[str]],
        limit: int = 6,
    ) -> List[Dict[str, object]]:
        entries: List[Dict[str, object]] = []
        for source in sorted(inbound.get(node_id, set())):
            entries.append(self._support_edge_payload(source, node_id, "incoming", node_id))
        for target in sorted(self.adj.get(node_id, set())):
            entries.append(self._support_edge_payload(node_id, target, "outgoing", node_id))
        entries.sort(
            key=lambda item: (
                -float(item["confidence_score"]),
                0 if item["direction"] == "incoming" else 1,
                str(item["resolution_kind"]),
                str(item["other_node"]),
            )
        )
        return entries[:limit]

    def _confidence_breakdown(self, edges: List[Dict[str, object]]) -> Dict[str, object]:
        counts: Dict[str, int] = defaultdict(int)
        for edge in edges:
            label = str(edge.get("confidence_label", ""))
            if label:
                counts[label] += 1
        best = edges[0] if edges else None
        return {
            "best_label": best.get("confidence_label", "") if best else "",
            "best_score": round(float(best.get("confidence_score", 0.0)), 2) if best else 0.0,
            "edge_count_by_label": {key: counts[key] for key in sorted(counts)},
        }

    def _recommended_next_evidence_target(
        self,
        node: SymbolNode,
        raw_call: str,
        detail: Dict[str, object],
    ) -> Dict[str, object]:
        targets = [{"file": node.file, "lines": node.lines, "why": f"Caller evidence for `{raw_call}`."}]
        for candidate_id in sorted(str(item) for item in detail.get("candidates", [])):
            if candidate_id not in self.nodes:
                continue
            candidate_node = self.nodes[candidate_id]
            targets.append(
                {
                    "file": candidate_node.file,
                    "lines": candidate_node.lines,
                    "why": f"Candidate implementation `{candidate_node.qualname}`.",
                }
            )
        return {
            "targets": self._dedupe_object_list(targets),
            "why": "Open the caller and candidate implementation slices only if the ambiguous edge matters.",
        }

    def _build_ambiguity_watchlist(self, limit: int = 12) -> List[Dict[str, object]]:
        watchlist: List[Dict[str, object]] = []
        for node_id in sorted(self.nodes, key=lambda item: (-self.nodes[item].risk_score, item)):
            node = self.nodes[node_id]
            for raw_call in sorted(node.unresolved_call_details):
                detail = node.unresolved_call_details[raw_call]
                watchlist.append(
                    {
                        "source_node": node_id,
                        "file": node.file,
                        "lines": node.lines,
                        "raw_call": raw_call,
                        "candidates": list(detail.get("candidates", [])),
                        "resolution_kind": detail.get("resolution_kind", ""),
                        "resolution_reason": detail.get("resolution_reason", ""),
                        "confidence_label": detail.get("confidence_label", ""),
                        "recommended_next_evidence_target": self._recommended_next_evidence_target(node, raw_call, detail),
                    }
                )
        return watchlist[:limit]

    def _sort_confidence_labels(self, labels: Iterable[str]) -> List[str]:
        unique = {label for label in labels if label}
        return sorted(
            unique,
            key=lambda label: (-CONFIDENCE_LABEL_ORDER.get(label, -1), label),
        )

    def _make_evidence_group(
        self,
        anchor_symbol: str,
        role: str,
        why: List[str],
        supporting_edges: Optional[List[Dict[str, object]]] = None,
        selection_confidence_labels: Optional[List[str]] = None,
        ambiguity_flags: Optional[List[Dict[str, object]]] = None,
        selection_score: Optional[float] = None,
        evidence_path_refs: Optional[List[str]] = None,
        semantic_refs: Optional[List[Dict[str, object]]] = None,
    ) -> Dict[str, object]:
        group: Dict[str, object] = {
            "anchor_symbol": anchor_symbol,
            "role": role,
            "why": list(why),
            "supporting_edges": list(supporting_edges or []),
            "selection_confidence_labels": self._sort_confidence_labels(selection_confidence_labels or []),
            "ambiguity_flags": list(ambiguity_flags or []),
        }
        if selection_score is not None:
            group["selection_score"] = round(selection_score, 2)
        if evidence_path_refs:
            group["evidence_path_refs"] = sorted(set(str(item) for item in evidence_path_refs if item))
        if semantic_refs:
            group["semantic_refs"] = self._dedupe_semantic_refs(list(semantic_refs), limit=4)
        return group

    def _normalize_evidence_groups(self, groups: List[Dict[str, object]]) -> List[Dict[str, object]]:
        role_order = {
            "query_target": 0,
            "primary_risk": 1,
            "support": 2,
            "ambiguity_context": 3,
            "file_context": 4,
        }
        merged: Dict[Tuple[str, str], Dict[str, object]] = {}
        for group in groups:
            anchor_symbol = str(group.get("anchor_symbol", ""))
            role = str(group.get("role", "support"))
            key = (anchor_symbol, role)
            current = merged.get(key)
            if current is None:
                current = {
                    "anchor_symbol": anchor_symbol,
                    "role": role,
                    "why": [],
                    "supporting_edges": [],
                    "selection_confidence_labels": [],
                    "ambiguity_flags": [],
                    "selection_score": float(group.get("selection_score", 0.0)),
                    "evidence_path_refs": [],
                    "semantic_refs": [],
                }
                merged[key] = current
            current["why"].extend(str(item) for item in group.get("why", []) if item)
            current["supporting_edges"].extend(list(group.get("supporting_edges", [])))
            current["selection_confidence_labels"].extend(str(item) for item in group.get("selection_confidence_labels", []) if item)
            current["ambiguity_flags"].extend(list(group.get("ambiguity_flags", [])))
            current["selection_score"] = max(float(current.get("selection_score", 0.0)), float(group.get("selection_score", 0.0)))
            current["evidence_path_refs"].extend(str(item) for item in group.get("evidence_path_refs", []) if item)
            current["semantic_refs"].extend(list(group.get("semantic_refs", [])))

        normalized_groups: List[Dict[str, object]] = []
        for anchor_symbol, role in sorted(
            merged,
            key=lambda item: (
                role_order.get(item[1], 9),
                item[0],
            ),
        ):
            current = merged[(anchor_symbol, role)]
            payload: Dict[str, object] = {
                "anchor_symbol": anchor_symbol,
                "role": role,
                "why": sorted(set(str(item) for item in current["why"] if item)),
                "supporting_edges": self._dedupe_object_list(list(current["supporting_edges"])),
                "selection_confidence_labels": self._sort_confidence_labels(current["selection_confidence_labels"]),
                "ambiguity_flags": self._dedupe_object_list(list(current["ambiguity_flags"])),
            }
            if float(current.get("selection_score", 0.0)) > 0.0:
                payload["selection_score"] = round(float(current["selection_score"]), 2)
            if current.get("evidence_path_refs"):
                payload["evidence_path_refs"] = sorted(set(str(item) for item in current["evidence_path_refs"] if item))
            if current.get("semantic_refs"):
                payload["semantic_refs"] = self._dedupe_semantic_refs(list(current["semantic_refs"]), limit=4)
            normalized_groups.append(payload)
        return normalized_groups

    def _path_refs_by_anchor(self, evidence_paths: List[Dict[str, object]]) -> Dict[str, List[str]]:
        refs: Dict[str, Set[str]] = defaultdict(set)
        for path in evidence_paths:
            path_id = str(path.get("path_id", ""))
            if not path_id:
                continue
            for item in path.get("recommended_slices", []):
                anchor_symbol = str(item.get("anchor_symbol", ""))
                if anchor_symbol:
                    refs[anchor_symbol].add(path_id)
        return {
            anchor_symbol: sorted(path_ids)
            for anchor_symbol, path_ids in refs.items()
        }

    def _annotate_slice_path_refs(
        self,
        spec: Dict[str, object],
        path_refs_by_anchor: Dict[str, List[str]],
    ) -> Dict[str, object]:
        group_refs: Set[str] = set(str(item) for item in spec.get("evidence_path_refs", []) if item)
        for group in spec.get("evidence_groups", []):
            anchor_symbol = str(group.get("anchor_symbol", ""))
            if not anchor_symbol:
                continue
            refs = sorted(set(str(item) for item in group.get("evidence_path_refs", []) if item) | set(path_refs_by_anchor.get(anchor_symbol, [])))
            if refs:
                group["evidence_path_refs"] = refs
                group_refs.update(refs)
        if group_refs:
            spec["evidence_path_refs"] = sorted(group_refs)
        return spec

    def _build_slice_spec(
        self,
        node_id: str,
        why: List[str],
        selection_score: float,
        selection_confidence_label: str,
        supporting_edges: Optional[List[Dict[str, object]]] = None,
        ambiguity_flags: Optional[List[Dict[str, object]]] = None,
        role: str = "support",
        anchor_symbol: str = "",
        evidence_path_refs: Optional[List[str]] = None,
        semantic_refs: Optional[List[Dict[str, object]]] = None,
    ) -> Dict[str, object]:
        node = self.nodes[node_id]
        start_line = max(1, node.lines[0] - 3)
        end_line = node.lines[1] + 3
        labels = self._sort_confidence_labels([selection_confidence_label])
        anchor = anchor_symbol or node_id
        semantic_items = self._dedupe_semantic_refs(list(semantic_refs or self._semantic_refs_for_node(anchor)), limit=4)
        return {
            "file": node.file,
            "start_line": start_line,
            "end_line": end_line,
            "symbols": [node_id],
            "why": list(why),
            "selection_score": round(selection_score, 2),
            "selection_confidence_label": selection_confidence_label,
            "selection_confidence_labels": labels,
            "supporting_edges": list(supporting_edges or []),
            "ambiguity_flags": list(ambiguity_flags or []),
            "evidence_path_refs": sorted(set(str(item) for item in evidence_path_refs or [] if item)),
            "semantic_refs": semantic_items,
            "evidence_groups": [
                self._make_evidence_group(
                    anchor_symbol=anchor,
                    role=role,
                    why=why,
                    supporting_edges=supporting_edges,
                    selection_confidence_labels=labels,
                    ambiguity_flags=ambiguity_flags,
                    selection_score=selection_score,
                    evidence_path_refs=evidence_path_refs,
                    semantic_refs=semantic_items,
                )
            ],
        }

    def _build_support_chain(
        self,
        node_id: str,
        inbound: Dict[str, Set[str]],
        limit: int = 3,
    ) -> Dict[str, object]:
        edges = self._support_edges_for_node(node_id, inbound, limit=limit * 2)
        incoming = [edge for edge in edges if edge["direction"] == "incoming"][:limit]
        outgoing = [edge for edge in edges if edge["direction"] == "outgoing"][:limit]
        return {
            "risk_node": node_id,
            "incoming_support": incoming,
            "outgoing_support": outgoing,
        }

    def _path_hop_payload(self, source: str, target: str) -> Dict[str, object]:
        outcome = self._edge_outcome(source, target)
        return {
            "source": source,
            "target": target,
            "resolution_kind": outcome.resolution_kind,
            "confidence_label": outcome.confidence_label,
            "confidence_score": round(float(outcome.confidence_score), 2),
            "resolution_reason": outcome.resolution_reason,
        }

    def _is_trivial_path_kind(self, resolution_kind: str) -> bool:
        return resolution_kind in {"same_class_method", "same_module_symbol", "direct_symbol"}

    def _path_kind_for_hops(self, risk_node: str, hops: List[Dict[str, object]]) -> str:
        resolution_kinds = {str(hop.get("resolution_kind", "")) for hop in hops}
        if resolution_kinds & {"instance_dispatch", "super_dispatch", "java_di_primary", "java_di_qualifier", "java_di_unique_impl"}:
            return "dispatch_chain"
        if "inheritance_exact" in resolution_kinds:
            return "inheritance_chain"
        if resolution_kinds & {"import_exact", "alias_resolved", "barrel_reexport"}:
            return "import_to_symbol_chain"
        if hops and str(hops[0].get("target", "")) == risk_node:
            return "inbound_support_chain"
        return "outbound_support_chain"

    def _path_recommended_slices(
        self,
        risk_node: str,
        hops: List[Dict[str, object]],
    ) -> List[Dict[str, object]]:
        anchors = [risk_node]
        for hop in hops:
            for node_id in (str(hop["source"]), str(hop["target"])):
                if node_id not in self.nodes or node_id in anchors:
                    continue
                anchors.append(node_id)
        slices: List[Dict[str, object]] = []
        for index, node_id in enumerate(anchors):
            node = self.nodes[node_id]
            slices.append(
                {
                    "anchor_symbol": node_id,
                    "role": "primary_risk" if index == 0 else "support",
                    "file": node.file,
                    "lines": node.lines,
                }
            )
        return slices

    def _select_path_extension(
        self,
        risk_node: str,
        first_edge: Dict[str, object],
        inbound: Dict[str, Set[str]],
        ambiguity_count: int,
    ) -> Tuple[Optional[Dict[str, object]], str]:
        if ambiguity_count > 0:
            return None, "ambiguity_blocked_extension"
        if float(first_edge.get("confidence_score", 0.0)) < 0.78:
            return None, "no_high_confidence_extension"

        pivot = str(first_edge["other_node"])
        preferred_direction = "incoming" if str(first_edge["direction"]) == "incoming" else "outgoing"
        candidates = [
            edge
            for edge in self._support_edges_for_node(pivot, inbound, limit=8)
            if str(edge["direction"]) == preferred_direction
        ]
        interesting_candidates = [
            edge for edge in candidates if not self._is_trivial_path_kind(str(edge.get("resolution_kind", "")))
        ]
        if interesting_candidates:
            candidates = interesting_candidates
        viable: List[Dict[str, object]] = []
        for edge in candidates:
            source = str(edge["source"])
            target = str(edge["target"])
            if source == risk_node or target == risk_node:
                continue
            if source == target:
                continue
            if float(edge.get("confidence_score", 0.0)) < 0.78:
                continue
            viable.append(edge)

        if not viable:
            if candidates:
                return None, "no_high_confidence_extension"
            return None, "no_supported_extension"

        viable.sort(
            key=lambda edge: (
                -float(edge.get("confidence_score", 0.0)),
                str(edge.get("resolution_kind", "")),
                str(edge.get("source", "")),
                str(edge.get("target", "")),
            )
        )
        return viable[0], "max_hops_reached"

    def _build_path_record(
        self,
        risk_node: str,
        hops: List[Dict[str, object]],
        stop_reason: str,
        path_id: str,
    ) -> Dict[str, object]:
        path_confidence = min(float(hop.get("confidence_score", 0.0)) for hop in hops) if hops else 0.0
        path_labels = self._sort_confidence_labels(str(hop.get("confidence_label", "")) for hop in hops)
        semantic_signals = self._sort_semantic_signals(
            signal
            for node_id in {risk_node} | {str(hop.get("source", "")) for hop in hops} | {str(hop.get("target", "")) for hop in hops}
            if node_id in self.nodes
            for signal in self.nodes[node_id].semantic_signals
        )
        payload = {
            "risk_node": risk_node,
            "path_id": path_id,
            "hops": hops,
            "path_confidence": round(path_confidence, 2),
            "path_confidence_label": path_labels[-1] if path_labels else "",
            "path_kind": self._path_kind_for_hops(risk_node, hops),
            "recommended_slices": self._path_recommended_slices(risk_node, hops),
            "stop_reason": stop_reason,
        }
        if semantic_signals:
            payload["semantic_signals"] = semantic_signals[:6]
        return payload

    def _build_evidence_paths_for_candidate(
        self,
        candidate: Dict[str, object],
        inbound: Dict[str, Set[str]],
        limit: int = 3,
    ) -> List[Dict[str, object]]:
        risk_node = str(candidate["node_id"])
        ambiguity_count = len(candidate["ambiguity_flags"])
        edges = self._support_edges_for_node(risk_node, inbound, limit=6)
        interesting_edges = [
            edge for edge in edges if not self._is_trivial_path_kind(str(edge.get("resolution_kind", "")))
        ]
        if interesting_edges:
            edges = interesting_edges
        path_entries: List[Dict[str, object]] = []
        seen_signatures: Set[str] = set()

        for edge in edges:
            hops = [self._path_hop_payload(str(edge["source"]), str(edge["target"]))]
            second_edge, stop_reason = self._select_path_extension(risk_node, edge, inbound, ambiguity_count)
            if second_edge is not None:
                hops.append(self._path_hop_payload(str(second_edge["source"]), str(second_edge["target"])))
            path_signature = " | ".join(f"{hop['source']}->{hop['target']}" for hop in hops)
            if path_signature in seen_signatures:
                continue
            seen_signatures.add(path_signature)
            trivial_penalty = sum(1.5 for hop in hops if self._is_trivial_path_kind(str(hop.get("resolution_kind", ""))))
            path_entries.append(
                {
                    "hops": hops,
                    "stop_reason": stop_reason,
                    "path_score": (
                        float(candidate["bundle_priority"])
                        + (min(float(hop["confidence_score"]) for hop in hops) * 10.0)
                        + len(hops)
                        - trivial_penalty
                    ),
                }
            )

        path_entries.sort(
            key=lambda item: (
                -float(item["path_score"]),
                -min(float(hop["confidence_score"]) for hop in item["hops"]),
                -len(item["hops"]),
                " | ".join(f"{hop['source']}->{hop['target']}" for hop in item["hops"]),
            )
        )

        selected_paths: List[Dict[str, object]] = []
        for index, item in enumerate(path_entries[:limit], start=1):
            selected_paths.append(
                self._build_path_record(
                    risk_node=risk_node,
                    hops=item["hops"],
                    stop_reason=str(item["stop_reason"]),
                    path_id=f"{risk_node}::path::{index}",
                )
            )
        return selected_paths

    def _build_evidence_paths(
        self,
        candidates: List[Dict[str, object]],
        inbound: Dict[str, Set[str]],
        limit_per_node: int = 3,
        global_limit: int = 18,
    ) -> List[Dict[str, object]]:
        paths: List[Dict[str, object]] = []
        for candidate in candidates[:8]:
            paths.extend(self._build_evidence_paths_for_candidate(candidate, inbound, limit=limit_per_node))
        paths.sort(key=self._path_sort_key)
        return paths[:global_limit]

    def _path_sort_key(self, path: Dict[str, object]) -> Tuple[int, float, int, str, str]:
        return (
            -sum(1 for hop in path.get("hops", []) if not self._is_trivial_path_kind(str(hop.get("resolution_kind", "")))),
            -float(path.get("path_confidence", 0.0)),
            -len(path.get("hops", [])),
            str(path.get("path_kind", "")),
            str(path.get("path_id", "")),
        )

    def _best_paths_by_risk_node(self, paths: List[Dict[str, object]]) -> Dict[str, Dict[str, object]]:
        grouped: Dict[str, List[Dict[str, object]]] = defaultdict(list)
        for path in paths:
            grouped[str(path.get("risk_node", ""))].append(path)
        return {
            risk_node: sorted(items, key=self._path_sort_key)[0]
            for risk_node, items in grouped.items()
            if risk_node and items
        }

    def _build_deferred_request_for_symbol(
        self,
        node_id: str,
        why: str,
        confidence_gate: str = "only_if_initial_evidence_is_insufficient",
        targets: Optional[List[Dict[str, object]]] = None,
        request: str = "",
    ) -> Dict[str, object]:
        node = self.nodes[node_id]
        requested_targets = list(targets or [{"file": node.file, "lines": node.lines}])
        return {
            "type": "focused_symbol_followup",
            "symbol": node_id,
            "confidence_gate": confidence_gate,
            "request": request or f"Open only `{node.file}:{node.lines[0]}-{node.lines[1]}` if the first-pass evidence is insufficient.",
            "targets": requested_targets,
            "why": why,
        }

    def _build_deferred_request_for_ambiguity(self, item: Dict[str, object]) -> Dict[str, object]:
        return {
            "type": "ambiguity_followup",
            "symbol": item["source_node"],
            "raw_call": item["raw_call"],
            "confidence_gate": "only_if_this_ambiguity_blocks_the_analysis",
            "request": (
                f"Open the caller and candidate implementations for `{item['raw_call']}` because the resolution is ambiguous."
            ),
            "targets": list(item["recommended_next_evidence_target"]["targets"]),
            "why": item["resolution_reason"],
        }

    def _build_deferred_request_for_path(
        self,
        path: Dict[str, object],
        selected_symbols: Set[str],
    ) -> Optional[Dict[str, object]]:
        risk_node = str(path["risk_node"])
        path_confidence = float(path.get("path_confidence", 0.0))
        if path_confidence >= 0.85:
            return None

        missing_targets: List[Dict[str, object]] = []
        for item in path.get("recommended_slices", []):
            anchor_symbol = str(item.get("anchor_symbol", ""))
            if anchor_symbol in selected_symbols:
                continue
            missing_targets.append(
                {
                    "file": item["file"],
                    "lines": item["lines"],
                    "anchor_symbol": anchor_symbol,
                }
            )

        if not missing_targets:
            return None

        missing_targets.sort(
            key=lambda item: (
                (int(item["lines"][1]) - int(item["lines"][0]) + 1) if item.get("lines") else 9999,
                str(item.get("file", "")),
                str(item.get("anchor_symbol", "")),
            )
        )
        first_target = missing_targets[0]
        hop_kinds = ", ".join(str(hop.get("resolution_kind", "")) for hop in path.get("hops", []))
        return self._build_deferred_request_for_symbol(
            risk_node,
            why=(
                f"Validate the best available `{path['path_kind']}` for `{risk_node}` because the best path is only "
                f"`{path.get('path_confidence_label', '')}` confidence."
            ),
            confidence_gate="only_if_this_medium_confidence_path_matters",
            targets=missing_targets[:1],
            request=(
                f"Open only `{first_target['file']}:{first_target['lines'][0]}-{first_target['lines'][1]}` "
                f"to validate the next evidence hop(s): {hop_kinds}."
            ),
        )

    def _build_evidence_candidate(
        self,
        rank: int,
        entry: Dict[str, object],
        inbound: Dict[str, Set[str]],
    ) -> Dict[str, object]:
        node_id = str(entry["symbol"])
        node = self.nodes[node_id]
        support_edges = self._support_edges_for_node(node_id, inbound)
        support_confidence = self._confidence_breakdown(support_edges)
        ambiguity_flags = [
            {
                "raw_call": raw_call,
                **node.unresolved_call_details[raw_call],
            }
            for raw_call in sorted(node.unresolved_call_details)
        ]
        adjacency_score = min(6.0, float(len(self.adj.get(node_id, set())) + len(inbound.get(node_id, set()))))
        best_support = float(support_confidence["best_score"])
        ambiguity_penalty = float(len(ambiguity_flags) * 4)
        semantic_bonus = self._semantic_bundle_bonus(node)
        bundle_priority = float(entry["risk_score"]) + (best_support * 10.0) + adjacency_score + semantic_bonus - ambiguity_penalty

        why_selected = list(node.reasons) or ["Selected because it appears in the prioritized structural-risk set."]
        if support_edges:
            why_selected.append(
                f"Best supporting edge uses `{support_edges[0]['resolution_kind']}` with `{support_edges[0]['confidence_label']}` confidence."
            )
        if node.semantic_signals:
            why_selected.append(
                f"Semantic signals: {', '.join(node.semantic_signals[:4])}."
            )
        if ambiguity_flags:
            why_selected.append(f"{len(ambiguity_flags)} ambiguous call(s) remain unresolved and are tracked separately.")

        primary_slice = self._build_slice_spec(
            node_id=node_id,
            why=why_selected + ["Primary risk evidence slice."],
            selection_score=bundle_priority + 12.0,
            selection_confidence_label=str(support_confidence["best_label"] or "medium"),
            supporting_edges=support_edges[:3],
            ambiguity_flags=ambiguity_flags[:2],
            role="primary_risk",
        )

        suggested_slices = [primary_slice]
        suggested_files = [node.file]
        for edge in support_edges:
            if float(edge["confidence_score"]) < 0.78:
                continue
            other_node = str(edge["other_node"])
            if other_node == node_id or self.nodes[other_node].file == node.file:
                continue
            suggested_files.append(self.nodes[other_node].file)
            suggested_slices.append(
                self._build_slice_spec(
                    node_id=other_node,
                    why=[
                        f"Support slice for `{node_id}` via `{edge['resolution_kind']}` ({edge['confidence_label']}).",
                        str(edge["resolution_reason"]),
                    ],
                    selection_score=(bundle_priority * 0.4) + (float(edge["confidence_score"]) * 20.0),
                    selection_confidence_label=str(edge["confidence_label"]),
                    supporting_edges=[edge],
                    ambiguity_flags=[],
                    role="support",
                )
            )
            if len(suggested_slices) >= 3:
                break

        deferred_if_needed: List[Dict[str, object]] = []
        if ambiguity_flags:
            for item in self._build_ambiguity_watchlist(limit=50):
                if item["source_node"] == node_id:
                    deferred_if_needed.append(self._build_deferred_request_for_ambiguity(item))

        return {
            "rank": rank,
            "node_id": node_id,
            "file": node.file,
            "lines": node.lines,
            "risk_score": entry["risk_score"],
            "bundle_priority": round(bundle_priority, 2),
            "why_selected": why_selected,
            "supporting_edges": support_edges,
            "supporting_edge_confidence": support_confidence,
            "semantic_signals": list(node.semantic_signals),
            "semantic_summary": dict(node.semantic_summary),
            "semantic_evidence_spans": self._semantic_refs_for_node(node_id, limit=4),
            "behavioral_flow_summary": dict(node.behavioral_flow_summary),
            "behavioral_flow_steps": list(node.behavioral_flow_steps[:8]),
            "contained_semantic_signals": list(node.contained_semantic_signals),
            "contained_semantic_summary": dict(node.contained_semantic_summary),
            "contained_semantic_refs": self._contained_semantic_refs_for_node(node_id, limit=4),
            "suggested_files": sorted(set(suggested_files)),
            "suggested_slices": suggested_slices,
            "ambiguity_flags": ambiguity_flags,
            "deferred_if_needed": self._dedupe_object_list(deferred_if_needed),
            "support_chain": self._build_support_chain(node_id, inbound),
        }

    def _build_evidence_candidates(
        self,
        top_risks: List[Dict[str, object]],
        inbound: Dict[str, Set[str]],
    ) -> List[Dict[str, object]]:
        candidates = [
            self._build_evidence_candidate(rank, entry, inbound)
            for rank, entry in enumerate(top_risks, start=1)
        ]
        candidates.sort(
            key=lambda item: (
                -float(item["bundle_priority"]),
                -float(item["risk_score"]),
                str(item["node_id"]),
            )
        )
        return candidates

    def _build_project_architecture_evidence(
        self,
        recommended_reads: List[Dict[str, str]],
        limit: int = 8,
    ) -> List[Dict[str, object]]:
        interesting_files = {item["file"] for item in recommended_reads}
        candidates: List[Dict[str, object]] = []
        for (source, target), outcome in self.edge_resolution.items():
            source_node = self.nodes[source]
            target_node = self.nodes[target]
            if outcome.resolution_kind in {"same_class_method", "same_module_symbol", "direct_symbol"}:
                continue
            if source_node.file not in interesting_files and target_node.file not in interesting_files:
                continue
            candidates.append(
                {
                    "source": source,
                    "target": target,
                    "source_file": source_node.file,
                    "target_file": target_node.file,
                    "confidence_score": outcome.confidence_score,
                    "confidence_label": outcome.confidence_label,
                    "resolution_kind": outcome.resolution_kind,
                    "resolution_reason": outcome.resolution_reason,
                }
            )
        candidates.sort(
            key=lambda item: (
                -float(item["confidence_score"]),
                str(item["resolution_kind"]),
                str(item["source"]),
                str(item["target"]),
            )
        )
        return candidates[:limit]

    def _build_project_architecture_paths(
        self,
        recommended_reads: List[Dict[str, str]],
        inbound: Dict[str, Set[str]],
        limit: int = 6,
    ) -> List[Dict[str, object]]:
        interesting_files = {item["file"] for item in recommended_reads}
        edge_candidates = self._build_project_architecture_evidence(recommended_reads, limit=max(limit * 2, 8))
        paths: List[Dict[str, object]] = []

        for index, edge in enumerate(edge_candidates, start=1):
            source = str(edge["source"])
            target = str(edge["target"])
            hops = [self._path_hop_payload(source, target)]
            extension: Optional[Dict[str, object]] = None

            outgoing = [
                candidate
                for candidate in self._support_edges_for_node(target, inbound, limit=6)
                if str(candidate["direction"]) == "outgoing"
                and str(candidate["target"]) != source
                and float(candidate.get("confidence_score", 0.0)) >= 0.78
            ]
            incoming = [
                candidate
                for candidate in self._support_edges_for_node(source, inbound, limit=6)
                if str(candidate["direction"]) == "incoming"
                and str(candidate["source"]) != target
                and float(candidate.get("confidence_score", 0.0)) >= 0.78
            ]
            candidates = outgoing + incoming
            if candidates:
                candidates.sort(
                    key=lambda item: (
                        -float(item.get("confidence_score", 0.0)),
                        str(item.get("resolution_kind", "")),
                        str(item.get("source", "")),
                        str(item.get("target", "")),
                    )
                )
                extension = candidates[0]
            if extension is not None:
                hops.append(self._path_hop_payload(str(extension["source"]), str(extension["target"])))

            recommended_slices = []
            seen_files: Set[str] = set()
            for node_id in {str(hop["source"]) for hop in hops} | {str(hop["target"]) for hop in hops}:
                if node_id not in self.nodes:
                    continue
                node = self.nodes[node_id]
                if node.file in seen_files and node.file not in interesting_files:
                    continue
                seen_files.add(node.file)
                recommended_slices.append(
                    {
                        "anchor_symbol": node_id,
                        "role": "file_context" if node.file in interesting_files else "support",
                        "file": node.file,
                        "lines": node.lines,
                    }
                )

            paths.append(
                {
                    "path_id": f"architecture::path::{index}",
                    "focus_edge": {"source": source, "target": target},
                    "hops": hops,
                    "path_confidence": round(min(float(hop["confidence_score"]) for hop in hops), 2) if hops else 0.0,
                    "path_kind": self._path_kind_for_hops(target, hops),
                    "recommended_slices": recommended_slices[:3],
                    "stop_reason": "max_hops_reached" if len(hops) > 1 else "no_supported_extension",
                }
            )

        paths.sort(
            key=lambda item: (
                -float(item["path_confidence"]),
                -len(item["hops"]),
                str(item["path_kind"]),
                str(item["path_id"]),
            )
        )
        return paths[:limit]

    def _rank_neighbors(self, neighbors: Iterable[str], limit: int = 3) -> List[Dict[str, object]]:
        ranked = sorted(
            neighbors,
            key=lambda node_id: (-self.nodes[node_id].risk_score, -self.nodes[node_id].ca, node_id),
        )
        out: List[Dict[str, object]] = []
        for node_id in ranked[:limit]:
            node = self.nodes[node_id]
            out.append(
                {
                    "symbol": node_id,
                    "risk_score": node.risk_score,
                    "file": node.file,
                    "lines": node.lines,
                }
            )
        return out

    def _merge_slice_specs(self, slice_specs: List[Dict[str, object]]) -> List[Dict[str, object]]:
        grouped: Dict[str, List[Dict[str, object]]] = defaultdict(list)
        for spec in slice_specs:
            grouped[spec["file"]].append(spec)

        merged: List[Dict[str, object]] = []
        for file_name in sorted(grouped):
            specs = sorted(grouped[file_name], key=lambda spec: (spec["start_line"], spec["end_line"]))
            current: Optional[Dict[str, object]] = None
            for spec in specs:
                if current is None:
                    current = {
                        "file": file_name,
                        "start_line": spec["start_line"],
                        "end_line": spec["end_line"],
                        "symbols": list(spec["symbols"]),
                        "why": list(spec["why"]),
                        "selection_score": float(spec.get("selection_score", 0.0)),
                        "selection_confidence_labels": list(spec.get("selection_confidence_labels", [])) or ([str(spec.get("selection_confidence_label", ""))] if spec.get("selection_confidence_label") else []),
                        "supporting_edges": list(spec.get("supporting_edges", [])),
                        "ambiguity_flags": list(spec.get("ambiguity_flags", [])),
                        "semantic_refs": list(spec.get("semantic_refs", [])),
                        "evidence_groups": list(spec.get("evidence_groups", [])),
                        "evidence_path_refs": list(spec.get("evidence_path_refs", [])),
                    }
                    continue

                if spec["start_line"] <= current["end_line"] + 2:
                    current["end_line"] = max(current["end_line"], spec["end_line"])
                    current["symbols"].extend(spec["symbols"])
                    current["why"].extend(spec["why"])
                    current["selection_score"] = max(float(current.get("selection_score", 0.0)), float(spec.get("selection_score", 0.0)))
                    current["selection_confidence_labels"].extend(list(spec.get("selection_confidence_labels", [])))
                    if spec.get("selection_confidence_label"):
                        current["selection_confidence_labels"].append(str(spec["selection_confidence_label"]))
                    current["supporting_edges"].extend(list(spec.get("supporting_edges", [])))
                    current["ambiguity_flags"].extend(list(spec.get("ambiguity_flags", [])))
                    current["semantic_refs"].extend(list(spec.get("semantic_refs", [])))
                    current["evidence_groups"].extend(list(spec.get("evidence_groups", [])))
                    current["evidence_path_refs"].extend(list(spec.get("evidence_path_refs", [])))
                else:
                    merged.append(self._normalize_slice(current))
                    current = {
                        "file": file_name,
                        "start_line": spec["start_line"],
                        "end_line": spec["end_line"],
                        "symbols": list(spec["symbols"]),
                        "why": list(spec["why"]),
                        "selection_score": float(spec.get("selection_score", 0.0)),
                        "selection_confidence_labels": list(spec.get("selection_confidence_labels", [])) or ([str(spec.get("selection_confidence_label", ""))] if spec.get("selection_confidence_label") else []),
                        "supporting_edges": list(spec.get("supporting_edges", [])),
                        "ambiguity_flags": list(spec.get("ambiguity_flags", [])),
                        "semantic_refs": list(spec.get("semantic_refs", [])),
                        "evidence_groups": list(spec.get("evidence_groups", [])),
                        "evidence_path_refs": list(spec.get("evidence_path_refs", [])),
                    }

            if current is not None:
                merged.append(self._normalize_slice(current))

        return merged

    def _normalize_slice(self, spec: Dict[str, object]) -> Dict[str, object]:
        evidence_groups = self._normalize_evidence_groups(list(spec.get("evidence_groups", [])))
        non_file_groups = [group for group in evidence_groups if str(group.get("role", "")) != "file_context"]
        normalized = {
            "file": spec["file"],
            "start_line": spec["start_line"],
            "end_line": spec["end_line"],
            "line_count": spec["end_line"] - spec["start_line"] + 1,
            "symbols": sorted(set(spec["symbols"])),
            "why": sorted(set(spec["why"])),
        }
        if len(non_file_groups) > 1:
            merge_reason = "Merged nearby evidence anchors in the same file to preserve budget without losing per-anchor provenance."
            normalized["why"] = sorted(set(list(normalized["why"]) + [merge_reason]))
            evidence_groups.append(
                self._make_evidence_group(
                    anchor_symbol=f"file::{spec['file']}",
                    role="file_context",
                    why=[merge_reason],
                    supporting_edges=[],
                    selection_confidence_labels=list(spec.get("selection_confidence_labels", [])),
                    ambiguity_flags=[],
                    selection_score=float(spec.get("selection_score", 0.0)),
                    evidence_path_refs=list(spec.get("evidence_path_refs", [])),
                    semantic_refs=list(spec.get("semantic_refs", [])),
                )
            )
            evidence_groups = self._normalize_evidence_groups(evidence_groups)
        if "selection_score" in spec:
            normalized["selection_score"] = round(float(spec.get("selection_score", 0.0)), 2)
        if spec.get("selection_confidence_labels"):
            normalized["selection_confidence_labels"] = self._sort_confidence_labels(spec["selection_confidence_labels"])
        if spec.get("supporting_edges"):
            normalized["supporting_edges"] = self._dedupe_object_list(list(spec["supporting_edges"]))
        if spec.get("ambiguity_flags"):
            normalized["ambiguity_flags"] = self._dedupe_object_list(list(spec["ambiguity_flags"]))
        if spec.get("semantic_refs"):
            normalized["semantic_refs"] = self._dedupe_semantic_refs(list(spec["semantic_refs"]), limit=6)
        if evidence_groups:
            normalized["evidence_groups"] = evidence_groups
        if spec.get("evidence_path_refs"):
            normalized["evidence_path_refs"] = sorted(set(str(item) for item in spec["evidence_path_refs"] if item))
        return normalized

    def _build_audit_prompt(self) -> str:
        return (
            "Analyze only the provided context_slices first. Use focus_symbols, evidence_groups, support_chains, "
            "evidence_paths, confidence_summary, semantic_candidates, and semantic_watchlist to explain the structural "
            "and behavioral cause of the risk. Treat ambiguity_watchlist items as unresolved until additional evidence "
            "is requested, and request the smallest useful item from deferred_requests instead of asking for whole files."
        )

    def _recursive_symbols(self) -> List[str]:
        return sorted(node_id for node_id, node in self.nodes.items() if node.recursive_self_call)

    def write_bundle(self, report: Dict[str, object], bundle_dir: str) -> str:
        bundle_path = Path(bundle_dir).resolve()
        bundle_path.mkdir(parents=True, exist_ok=True)
        ask_pack = report.get("ask_context_pack") if isinstance(report.get("ask_context_pack"), dict) else None

        report_path = bundle_path / "sia_report.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        (bundle_path / "audit_prompt.txt").write_text(
            str(report["llm_context_pack"]["audit_prompt"]) + "\n",
            encoding="utf-8",
        )

        (bundle_path / "project_inventory.json").write_text(
            json.dumps(report["project_inventory"], indent=2),
            encoding="utf-8",
        )

        (bundle_path / "project_context_pack.json").write_text(
            json.dumps(report["project_context_pack"], indent=2),
            encoding="utf-8",
        )

        (bundle_path / "context_pack.json").write_text(
            json.dumps(report["llm_context_pack"], indent=2),
            encoding="utf-8",
        )

        slices_dir = bundle_path / "context_slices"
        slices_dir.mkdir(exist_ok=True)
        for index, spec in enumerate(report["llm_context_pack"]["context_slices"], start=1):
            snippet = self._render_slice_markdown(spec)
            slice_name = f"{index:02d}_{self._safe_slug(str(spec['file']))}_{spec['start_line']}_{spec['end_line']}.md"
            (slices_dir / slice_name).write_text(snippet, encoding="utf-8")

        project_slices_dir = bundle_path / "project_slices"
        project_slices_dir.mkdir(exist_ok=True)
        for index, spec in enumerate(report["project_context_pack"]["file_slices"], start=1):
            snippet = self._render_project_slice_markdown(spec)
            slice_name = f"{index:02d}_{self._safe_slug(str(spec['file']))}.md"
            (project_slices_dir / slice_name).write_text(snippet, encoding="utf-8")

        deferred_path = bundle_path / "deferred_requests.json"
        deferred_path.write_text(
            json.dumps(report["llm_context_pack"]["deferred_requests"], indent=2),
            encoding="utf-8",
        )

        if ask_pack:
            (bundle_path / "ask_context_pack.json").write_text(
                json.dumps(ask_pack, indent=2),
                encoding="utf-8",
            )
            (bundle_path / "work_packet.json").write_text(
                json.dumps(ask_pack.get("work_packet", {}), indent=2),
                encoding="utf-8",
            )
            (bundle_path / "worker_prompt.txt").write_text(
                str(ask_pack.get("worker_prompt", "")) + "\n",
                encoding="utf-8",
            )
            (bundle_path / "worker_trace_template.json").write_text(
                json.dumps(ask_pack.get("worker_trace_template", {}), indent=2),
                encoding="utf-8",
            )
            (bundle_path / "worker_result_template.json").write_text(
                json.dumps(ask_pack.get("worker_result_template", {}), indent=2),
                encoding="utf-8",
            )
            (bundle_path / "worker_validation_rules.json").write_text(
                json.dumps(ask_pack.get("worker_validation_rules", []), indent=2),
                encoding="utf-8",
            )
            (bundle_path / "worker_result_prompt.txt").write_text(
                str(ask_pack.get("worker_result_prompt", "")) + "\n",
                encoding="utf-8",
            )
            (bundle_path / "worker_report_prompt.txt").write_text(
                str(ask_pack.get("worker_report_prompt", "")) + "\n",
                encoding="utf-8",
            )
            (bundle_path / "analysis_result.json").write_text(
                json.dumps(ask_pack.get("analysis_result", {}), indent=2),
                encoding="utf-8",
            )
            (bundle_path / "result_prompt.txt").write_text(
                str(ask_pack.get("result_prompt", "")) + "\n",
                encoding="utf-8",
            )
            (bundle_path / "escalation_controller.json").write_text(
                json.dumps(ask_pack.get("escalation_controller", {}), indent=2),
                encoding="utf-8",
            )
            (bundle_path / "escalation_prompt.txt").write_text(
                str(ask_pack.get("escalation_prompt", "")) + "\n",
                encoding="utf-8",
            )
            (bundle_path / "followup_ask.json").write_text(
                json.dumps(ask_pack.get("followup_ask", {}), indent=2),
                encoding="utf-8",
            )
            (bundle_path / "followup_prompt.txt").write_text(
                str(ask_pack.get("followup_prompt", "")) + "\n",
                encoding="utf-8",
            )
            (bundle_path / "ask_prompt.txt").write_text(
                str(ask_pack.get("ask_prompt", "")) + "\n",
                encoding="utf-8",
            )
            (bundle_path / "analyst_prompt.txt").write_text(
                str(ask_pack.get("analyst_prompt", "")) + "\n",
                encoding="utf-8",
            )
            (bundle_path / "ask_deferred_requests.json").write_text(
                json.dumps(ask_pack.get("deferred_requests", []), indent=2),
                encoding="utf-8",
            )
            ask_slices_dir = bundle_path / "ask_slices"
            ask_slices_dir.mkdir(exist_ok=True)
            for index, spec in enumerate(ask_pack.get("selected_slices", []), start=1):
                snippet = self._render_slice_markdown(spec)
                slice_name = f"{index:02d}_{self._safe_slug(str(spec['file']))}_{spec['start_line']}_{spec['end_line']}.md"
                (ask_slices_dir / slice_name).write_text(snippet, encoding="utf-8")

        (bundle_path / "README_LLM.md").write_text(
            self._render_bundle_readme(report, bundle_path),
            encoding="utf-8",
        )
        return str(bundle_path)

    def _render_slice_markdown(self, spec: Dict[str, object]) -> str:
        file_path = os.path.join(self.root_dir, str(spec["file"]))
        lines: List[str] = []
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError:
            return f"# Missing Slice\n\nCould not read `{spec['file']}`.\n"

        start = int(spec["start_line"])
        end = int(spec["end_line"])
        excerpt_lines = []
        for lineno in range(start, min(end, len(lines)) + 1):
            excerpt_lines.append(f"{lineno:>4}: {lines[lineno - 1].rstrip()}")

        joined_symbols = ", ".join(str(item) for item in spec["symbols"])
        reasons = "\n".join(f"- {item}" for item in spec["why"])
        evidence_groups = []
        for group in spec.get("evidence_groups", []):
            group_header = f"- `{group['anchor_symbol']}` ({group['role']})"
            group_reasons = "".join(f"\n  - {item}" for item in group.get("why", []))
            group_semantics = "".join(
                f"\n  - semantic `{item['signal']}` at `{item['lines'][0]}-{item['lines'][1]}`: {item['reason']}"
                for item in group.get("semantic_refs", [])
            )
            evidence_groups.append(group_header + group_reasons + group_semantics)
        evidence_groups_text = "\n".join(evidence_groups) if evidence_groups else "- none"
        path_refs = ", ".join(str(item) for item in spec.get("evidence_path_refs", [])) or "none"
        semantic_refs = "\n".join(
            f"- `{item['signal']}` at `{item['lines'][0]}-{item['lines'][1]}`: {item['reason']}"
            for item in spec.get("semantic_refs", [])
        ) or "- none"
        return (
            f"# Context Slice\n\n"
            f"File: `{spec['file']}`\n"
            f"Lines: `{start}-{end}`\n"
            f"Symbols: `{joined_symbols}`\n\n"
            f"Why:\n{reasons}\n\n"
            f"Semantic Refs:\n{semantic_refs}\n\n"
            f"Evidence Groups:\n{evidence_groups_text}\n\n"
            f"Evidence Path Refs: `{path_refs}`\n\n"
            f"```{self._language_for_file(str(spec['file']))}\n" + "\n".join(excerpt_lines) + "\n```\n"
        )

    def _render_project_slice_markdown(self, spec: Dict[str, object]) -> str:
        evidence_groups = []
        for group in spec.get("evidence_groups", []):
            evidence_groups.append(f"- `{group['anchor_symbol']}` ({group['role']}): " + "; ".join(group.get("why", [])))
        evidence_groups_text = "\n".join(evidence_groups) if evidence_groups else "- none"
        semantic_refs = "\n".join(
            f"- `{item['signal']}` at `{item['lines'][0]}-{item['lines'][1]}`: {item['reason']}"
            for item in spec.get("semantic_refs", [])
        ) or "- none"
        return (
            "# Project Slice\n\n"
            f"File: `{spec['file']}`\n"
            f"Why: {spec['why']}\n\n"
            f"Semantic Refs:\n{semantic_refs}\n\n"
            f"Evidence Groups:\n{evidence_groups_text}\n\n"
            f"```{self._language_for_file(str(spec['file']))}\n{spec['excerpt']}\n```\n"
        )

    def _render_bundle_readme(self, report: Dict[str, object], bundle_path: Path) -> str:
        pack = report["llm_context_pack"]
        ask_pack = report.get("ask_context_pack") if isinstance(report.get("ask_context_pack"), dict) else None
        inventory = report["project_inventory"]
        technologies = ", ".join(inventory["likely_technologies"]) or "unknown"
        languages = ", ".join(
            f"{item['language']} ({item['file_count']})"
            for item in inventory["language_summary"][:6]
        ) or "unknown"
        read_first_lines = [
            "1. `project_context_pack.json`",
            "2. Check `confidence_summary`, direct `semantic_entrypoints`, contained `semantic_overview`, `architecture_evidence`, `architecture_evidence_paths`, and `ambiguity_watchlist`",
            "3. Files under `project_slices/`",
            "4. `sia_report.json`",
            "5. `context_pack.json` with `evidence_candidates`, `semantic_candidates`, `semantic_watchlist`, `evidence_paths`, `support_chains`, and `evidence_groups`",
            "6. Files under `context_slices/`",
            "7. `deferred_requests.json` only if the first slices are insufficient",
        ]
        ask_section = ""
        if ask_pack:
            analysis_result = ask_pack.get("analysis_result", {}) if isinstance(ask_pack.get("analysis_result"), dict) else {}
            escalation_controller = ask_pack.get("escalation_controller", {}) if isinstance(ask_pack.get("escalation_controller"), dict) else {}
            followup_ask = ask_pack.get("followup_ask", {}) if isinstance(ask_pack.get("followup_ask"), dict) else {}
            work_packet = ask_pack.get("work_packet", {}) if isinstance(ask_pack.get("work_packet"), dict) else {}
            read_first_lines = [
                "1. `ask_context_pack.json` for the query-scoped ranking, analysis_plan, work_packet, analysis_result, and smallest evidence-first slices",
                "2. `work_packet.json`",
                "3. `worker_prompt.txt`",
                "4. `worker_trace_template.json`",
                "5. `worker_result_template.json`",
                "6. `worker_validation_rules.json`",
                "7. `worker_result_prompt.txt`",
                "8. `worker_report_prompt.txt`",
                "9. `analysis_result.json`",
                "10. `escalation_controller.json`",
                "11. `followup_ask.json`",
                "12. `result_prompt.txt`",
                "13. `escalation_prompt.txt`",
                "14. `followup_prompt.txt`",
                "15. `analyst_prompt.txt`",
                "16. `ask_prompt.txt`",
                "17. Files under `ask_slices/`",
                "18. `ask_deferred_requests.json` only if the query remains under-evidenced",
                "19. `project_context_pack.json`",
                "20. Check `confidence_summary`, direct `semantic_entrypoints`, contained `semantic_overview`, `architecture_evidence`, `architecture_evidence_paths`, and `ambiguity_watchlist`",
                "21. Files under `project_slices/`",
                "22. `sia_report.json`",
                "23. `context_pack.json` with `evidence_candidates`, `semantic_candidates`, `semantic_watchlist`, `evidence_paths`, `support_chains`, and `evidence_groups`",
                "24. Files under `context_slices/`",
                "25. `deferred_requests.json` only if the broader bundle is still insufficient",
            ]
            ask_section = (
                "## Query-Scoped Ask Pack\n\n"
                f"- Query: `{ask_pack.get('query', '')}`\n"
                f"- Outcome: `{analysis_result.get('outcome_mode', '')}`\n"
                f"- Worker mode: `{work_packet.get('worker_mode', '')}`\n"
                f"- Escalation allowed: `{bool(escalation_controller.get('escalation_allowed'))}`\n"
                f"- Follow-up enabled: `{bool(followup_ask.get('enabled'))}`\n"
                f"- Selected slices: `{len(ask_pack.get('selected_slices', []))}`\n"
                f"- Selected evidence paths: `{len(ask_pack.get('selected_evidence_paths', []))}`\n"
                f"- Deferred requests: `{len(ask_pack.get('deferred_requests', []))}`\n\n"
                "Use the query-scoped pack first. It is intentionally smaller and prefers executable evidence with "
                "direct semantic matches before contained semantics or broader project context. `work_packet.json`, "
                "`worker_prompt.txt`, `worker_trace_template.json`, `worker_result_template.json`, "
                "`worker_validation_rules.json`, `worker_result_prompt.txt`, `worker_report_prompt.txt`, "
                "`analysis_result.json`, `result_prompt.txt`, `escalation_controller.json`, `escalation_prompt.txt`, "
                "`followup_ask.json`, and `followup_prompt.txt` are the narrowest answer, trace, and validation "
                "contract; only open deferred follow-ups if that bounded result is insufficient and escalation is "
                "explicitly allowed.\n\n"
            )
        return (
            "# SIA Context Bundle\n\n"
            "This bundle is designed as the smallest useful handoff to an LLM coding agent.\n\n"
            "## What To Read First\n\n"
            + "\n".join(read_first_lines)
            + "\n\n"
            + ask_section
            + "## Project Snapshot\n\n"
            + f"- Root: `{report['meta']['root_dir']}`\n"
            + f"- Graph nodes: `{inventory['graph_node_count']}`\n"
            + f"- Python symbols: `{inventory['python_symbol_count']}`\n"
            + f"- Total files seen: `{inventory['total_file_count']}`\n"
            + f"- Likely technologies: `{technologies}`\n"
            + f"- Language mix: `{languages}`\n"
            + f"- Git hotspot support active: `{report['meta']['git_hotspots_enabled']}`\n\n"
            + "## Project Prompt\n\n"
            + f"{report['project_context_pack']['project_prompt']}\n\n"
            + "## Audit Prompt\n\n"
            + f"{pack['audit_prompt']}\n\n"
            + "## Bundle Path\n\n"
            + f"`{bundle_path}`\n"
        )

    def _safe_slug(self, text: str) -> str:
        out = []
        for char in text.lower():
            if char.isalnum():
                out.append(char)
            else:
                out.append("_")
        return "".join(out).strip("_") or "slice"


def _validation_outcome_rank(outcome_mode: str) -> int:
    return OUTCOME_MODE_ORDER.get(str(outcome_mode or ""), -1)


def _load_json_file(path: str) -> Dict[str, object]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _worker_result_claims(worker_result: Dict[str, object]) -> List[str]:
    result_slots = worker_result.get("result_slots", {}) if isinstance(worker_result.get("result_slots"), dict) else {}
    claims: List[str] = []
    for claim in result_slots.get("used_claims", []):
        claim = str(claim).strip()
        if claim and claim not in claims:
            claims.append(claim)
    final_claim = str(result_slots.get("final_claim", "")).strip()
    if final_claim and final_claim not in claims:
        claims.append(final_claim)
    return claims


def _ordered_subsequence_check(sequence: List[str], observed: List[str]) -> Tuple[bool, str]:
    if not sequence:
        return True, ""
    if not observed:
        return False, sequence[0]
    obs_index = 0
    for item in sequence:
        while obs_index < len(observed) and observed[obs_index] != item:
            obs_index += 1
        if obs_index >= len(observed):
            return False, item
        obs_index += 1
    return True, ""


def _build_read_order_coverage(
    required_refs: List[str],
    observed_refs: List[str],
) -> Dict[str, object]:
    required_refs = [str(item) for item in required_refs if str(item)]
    observed_refs = [str(item) for item in observed_refs if str(item)]
    if not required_refs:
        return {
            "required_count": 0,
            "observed_count": len(observed_refs),
            "matched_required_refs": [],
            "ordered_coverage_ratio": 1.0,
            "missing_required_refs": [],
            "first_divergence": None,
            "sequence_status": "no_requirements",
        }

    matched: List[str] = []
    missing_required_refs: List[str] = []
    first_divergence: Optional[Dict[str, object]] = None
    obs_index = 0
    for required_index, required_ref in enumerate(required_refs, start=1):
        found = False
        while obs_index < len(observed_refs):
            observed_ref = observed_refs[obs_index]
            if observed_ref == required_ref:
                matched.append(required_ref)
                obs_index += 1
                found = True
                break
            if first_divergence is None:
                first_divergence = {
                    "required_index": required_index,
                    "required_ref": required_ref,
                    "observed_index": obs_index + 1,
                    "observed_ref": observed_ref,
                }
            obs_index += 1
        if not found:
            missing_required_refs = required_refs[len(matched):]
            if first_divergence is None:
                first_divergence = {
                    "required_index": required_index,
                    "required_ref": required_ref,
                    "observed_index": (obs_index + 1) if obs_index < len(observed_refs) else None,
                    "observed_ref": observed_refs[obs_index] if obs_index < len(observed_refs) else "",
                }
            break

    if len(matched) == len(required_refs):
        sequence_status = "complete_in_order"
    elif not observed_refs:
        sequence_status = "not_started"
    elif first_divergence and not matched:
        sequence_status = "diverged_before_start"
    elif first_divergence:
        sequence_status = "partial_with_divergence"
    else:
        sequence_status = "partial_in_order"

    return {
        "required_count": len(required_refs),
        "observed_count": len(observed_refs),
        "matched_required_refs": matched,
        "ordered_coverage_ratio": round(len(matched) / max(1, len(required_refs)), 2),
        "missing_required_refs": missing_required_refs,
        "first_divergence": first_divergence if sequence_status != "complete_in_order" else None,
        "sequence_status": sequence_status,
    }


def _build_primary_target_coverage(
    required_symbols: List[str],
    observed_symbols: List[str],
) -> Dict[str, object]:
    required_symbols = [str(item) for item in required_symbols if str(item)]
    observed_symbols = [str(item) for item in observed_symbols if str(item)]
    if not required_symbols:
        return {
            "required_count": 0,
            "observed_count": len(observed_symbols),
            "matched_primary_symbols": [],
            "missing_required_symbols": [],
            "coverage_ratio": 1.0,
            "status": "no_requirements",
        }
    observed_set = set(observed_symbols)
    matched = [symbol for symbol in required_symbols if symbol in observed_set]
    missing = [symbol for symbol in required_symbols if symbol not in observed_set]
    if not matched:
        status = "not_started"
    elif not missing:
        status = "complete"
    else:
        status = "partial"
    return {
        "required_count": len(required_symbols),
        "observed_count": len(observed_symbols),
        "matched_primary_symbols": matched,
        "missing_required_symbols": missing,
        "coverage_ratio": round(len(matched) / max(1, len(required_symbols)), 2),
        "status": status,
    }


def _load_worker_contract(
    against_ask_bundle: str,
    against_report: str,
) -> Dict[str, object]:
    if bool(against_ask_bundle) == bool(against_report):
        raise ValueError("Provide exactly one of --against-ask-bundle or --against-report.")
    if against_ask_bundle:
        ask_context_path = os.path.join(os.path.abspath(against_ask_bundle), "ask_context_pack.json")
        ask_pack = _load_json_file(ask_context_path)
        return {
            "contract_source": os.path.abspath(against_ask_bundle),
            "ask_context_pack": ask_pack,
            "worker_trace_template": ask_pack.get("worker_trace_template", {}),
            "worker_result_template": ask_pack.get("worker_result_template", {}),
            "worker_validation_rules": ask_pack.get("worker_validation_rules", []),
        }
    report = _load_json_file(os.path.abspath(against_report))
    ask_pack = report.get("ask_context_pack", {})
    if not isinstance(ask_pack, dict) or not ask_pack:
        raise ValueError("The report does not contain an ask_context_pack.")
    return {
        "contract_source": os.path.abspath(against_report),
        "ask_context_pack": ask_pack,
        "worker_trace_template": ask_pack.get("worker_trace_template", {}),
        "worker_result_template": ask_pack.get("worker_result_template", {}),
        "worker_validation_rules": ask_pack.get("worker_validation_rules", []),
    }


def validate_worker_result_payload(
    worker_result: Dict[str, object],
    contract: Dict[str, object],
) -> Dict[str, object]:
    template = contract.get("worker_result_template", {}) if isinstance(contract.get("worker_result_template"), dict) else {}
    rules = contract.get("worker_validation_rules", []) if isinstance(contract.get("worker_validation_rules"), list) else []
    ask_pack = contract.get("ask_context_pack", {}) if isinstance(contract.get("ask_context_pack"), dict) else {}
    rule_index = {
        str(rule.get("rule_id", "")): rule
        for rule in rules
        if isinstance(rule, dict) and str(rule.get("rule_id", ""))
    }

    result_slots = worker_result.get("result_slots", {}) if isinstance(worker_result.get("result_slots"), dict) else {}
    claims = _worker_result_claims(worker_result)
    allowed_claims = {str(item) for item in template.get("allowed_claims", [])}
    disallowed_claims = {str(item) for item in template.get("disallowed_claims", [])}
    expected_ceiling = str(template.get("expected_outcome_ceiling", "")) or str(
        ask_pack.get("analysis_result", {}).get("outcome_mode", "")
    )
    minimum_honest = str(template.get("minimum_honest_outcome", "")) or expected_ceiling
    inspected_slice_refs = [str(item) for item in result_slots.get("inspected_slice_refs", []) if str(item)]
    inspected_symbols = [str(item) for item in result_slots.get("inspected_symbols", []) if str(item)]
    final_outcome_mode = str(result_slots.get("final_outcome_mode", "")).strip()
    completion_state = str(
        result_slots.get("completion_state", "") or template.get("default_completion_state", "ready_for_execution")
    ).strip()
    followup_used = bool(result_slots.get("followup_used"))
    stop_condition_hit = str(result_slots.get("stop_condition_hit", "")).strip()
    required_read_order_refs = [str(item) for item in template.get("required_read_order_refs", []) if str(item)]
    required_primary_symbols = [str(item) for item in template.get("required_primary_symbols", []) if str(item)]
    valid_stop_conditions = {str(item) for item in template.get("valid_stop_conditions", []) if str(item)}
    supported_completion_states = {str(item) for item in template.get("supported_completion_states", []) if str(item)}
    terminal_states = WORKER_TERMINAL_STATES

    violations: List[Dict[str, object]] = []
    warnings: List[Dict[str, object]] = []
    recommended_fixes: List[str] = []
    accepted_claims = [claim for claim in claims if claim in allowed_claims and claim not in disallowed_claims]
    rejected_claims = [claim for claim in claims if claim not in allowed_claims or claim in disallowed_claims]

    def add_issue(
        bucket: List[Dict[str, object]],
        rule_id: str,
        message: str,
        default_severity: str = "error",
    ) -> None:
        rule = rule_index.get(rule_id, {})
        severity = str(rule.get("severity", default_severity) or default_severity)
        bucket.append(
            {
                "rule_id": rule_id,
                "severity": severity,
                "message": message,
            }
        )

    if rejected_claims:
        add_issue(
            violations,
            "must_respect_allowed_claims",
            f"Claims outside the bounded allow-list were used: {', '.join(rejected_claims[:4])}.",
        )
        recommended_fixes.append("Use only claim strings from `allowed_claims`.")

    disallowed_hits = [claim for claim in claims if claim in disallowed_claims]
    if disallowed_hits:
        add_issue(
            violations,
            "must_not_use_disallowed_claims",
            f"Disallowed claim strings were emitted: {', '.join(disallowed_hits[:4])}.",
        )
        recommended_fixes.append("Remove any claim that appears in `disallowed_claims`.")

    if final_outcome_mode:
        if _validation_outcome_rank(final_outcome_mode) > _validation_outcome_rank(expected_ceiling):
            add_issue(
                violations,
                "must_not_exceed_outcome_ceiling",
                f"`final_outcome_mode = {final_outcome_mode}` exceeds `expected_outcome_ceiling = {expected_ceiling}`.",
            )
            recommended_fixes.append(f"Cap `final_outcome_mode` at `{expected_ceiling}`.")
        if _validation_outcome_rank(final_outcome_mode) < _validation_outcome_rank(minimum_honest):
            add_issue(
                violations,
                "must_not_drop_below_minimum_honest_outcome",
                f"`final_outcome_mode = {final_outcome_mode}` drops below `minimum_honest_outcome = {minimum_honest}`.",
            )
            recommended_fixes.append(f"Keep `final_outcome_mode` at or above `{minimum_honest}`.")
    elif completion_state in terminal_states:
        add_issue(
            violations,
            "must_set_final_outcome_for_terminal_result",
            "Terminal worker results must set `result_slots.final_outcome_mode`.",
        )
        recommended_fixes.append("Set `result_slots.final_outcome_mode` before returning a terminal worker result.")
    elif completion_state not in {"ready_for_execution", "in_progress"}:
        add_issue(
            warnings,
            "must_not_exceed_outcome_ceiling",
            "A non-ready worker result omitted `final_outcome_mode`.",
            default_severity="warning",
        )

    if required_read_order_refs:
        if inspected_slice_refs:
            if inspected_slice_refs[0] != required_read_order_refs[0]:
                add_issue(
                    violations,
                    "must_read_primary_slice_first",
                    f"The first inspected slice `{inspected_slice_refs[0]}` does not match the required primary slice `{required_read_order_refs[0]}`.",
                )
                recommended_fixes.append("Inspect the first required read-order slice before any other slice.")
        elif completion_state not in {"ready_for_execution", "in_progress"}:
            add_issue(
                violations,
                "must_read_primary_slice_first",
                "The worker result reached a terminal state without recording any inspected slice refs.",
            )
            recommended_fixes.append("Record inspected slice refs and start with the first required read-order slice.")
        if completion_state in terminal_states:
            is_complete_sequence, missing_ref = _ordered_subsequence_check(required_read_order_refs, inspected_slice_refs)
            if not is_complete_sequence:
                add_issue(
                    violations,
                    "must_read_required_sequence_for_terminal_result",
                    f"Terminal worker results must include the full required read-order sequence; missing or out-of-order ref `{missing_ref}`.",
                )
                recommended_fixes.append(
                    "For terminal worker results, include every `required_read_order_refs` entry in `inspected_slice_refs` in the exported order."
                )

    if required_primary_symbols:
        missing_primary = [symbol for symbol in required_primary_symbols if symbol not in inspected_symbols]
        if missing_primary and completion_state in terminal_states:
            add_issue(
                violations,
                "must_cover_required_primary_symbols_for_terminal_result",
                f"Terminal worker results must record every required primary symbol; missing `{', '.join(missing_primary[:3])}`.",
            )
            recommended_fixes.append(
                "Record every `required_primary_symbols` entry in `result_slots.inspected_symbols` before returning a terminal worker result."
            )
        elif missing_primary and inspected_symbols:
            add_issue(
                warnings,
                "must_cover_required_primary_symbols_for_terminal_result",
                f"Primary symbols were not all recorded in `inspected_symbols`: {', '.join(missing_primary[:3])}.",
                default_severity="warning",
            )

    if completion_state and completion_state not in supported_completion_states:
        add_issue(
            violations,
            "must_stop_when_completion_criteria_met",
            f"`completion_state = {completion_state}` is not listed in `supported_completion_states`.",
        )
        recommended_fixes.append("Use a completion state from `supported_completion_states`.")
    elif completion_state in terminal_states and stop_condition_hit not in valid_stop_conditions:
        add_issue(
            violations,
            "must_stop_when_completion_criteria_met",
            f"Terminal completion state `{completion_state}` requires a `stop_condition_hit` from `valid_stop_conditions`.",
        )
        recommended_fixes.append("Record a valid `stop_condition_hit` when the worker result is completed or stopped.")

    if not bool(template.get("followup_allowed")) and followup_used:
        add_issue(
            violations,
            "must_not_open_followup_when_disabled",
            "The worker marked `followup_used = true` even though the follow-up gate is closed.",
        )
        recommended_fixes.append("Keep `followup_used = false` while the follow-up gate is closed.")

    if "must_not_claim_uniqueness_while_ambiguous" in rule_index and final_outcome_mode and final_outcome_mode != "ambiguous":
        add_issue(
            violations,
            "must_not_claim_uniqueness_while_ambiguous",
            f"Ambiguous contract requires `final_outcome_mode = ambiguous`, but the worker returned `{final_outcome_mode}`.",
        )
        recommended_fixes.append("Keep ambiguous work packets at `final_outcome_mode = ambiguous` unless new evidence is added and the analysis is rerun.")

    if "must_not_claim_direct_io_without_direct_evidence" in rule_index:
        forbidden_io_claims = [
            claim
            for claim in claims
            if "direct network i/o" in claim.lower() and claim not in allowed_claims
        ]
        if forbidden_io_claims:
            add_issue(
                violations,
                "must_not_claim_direct_io_without_direct_evidence",
                f"Direct I/O claims appeared without direct evidence: {', '.join(forbidden_io_claims[:3])}.",
            )
            recommended_fixes.append("Do not claim direct I/O unless the claim is explicitly allowed by the current bounded result.")

    capped_outcome_mode = expected_ceiling
    if final_outcome_mode:
        if _validation_outcome_rank(final_outcome_mode) <= _validation_outcome_rank(expected_ceiling):
            capped_outcome_mode = final_outcome_mode

    return {
        "valid": not violations,
        "attempted_claims": claims,
        "violations": violations,
        "warnings": warnings,
        "capped_outcome_mode": capped_outcome_mode,
        "accepted_claims": accepted_claims,
        "rejected_claims": rejected_claims,
        "recommended_fix": (
            " ".join(dict.fromkeys(recommended_fixes))
            if recommended_fixes
            else "None; the worker result stays within the bounded contract."
        ),
        "contract_source": str(contract.get("contract_source", "")),
        "expected_outcome_ceiling": expected_ceiling,
        "minimum_honest_outcome": minimum_honest,
    }


def build_worker_result_report(
    worker_result: Dict[str, object],
    contract: Dict[str, object],
    validation_report: Dict[str, object],
) -> Dict[str, object]:
    template = contract.get("worker_result_template", {}) if isinstance(contract.get("worker_result_template"), dict) else {}
    ask_pack = contract.get("ask_context_pack", {}) if isinstance(contract.get("ask_context_pack"), dict) else {}
    trace_template = contract.get("worker_trace_template", {}) if isinstance(contract.get("worker_trace_template"), dict) else {}
    result_slots = worker_result.get("result_slots", {}) if isinstance(worker_result.get("result_slots"), dict) else {}
    trace_slots = worker_result.get("trace_slots", {}) if isinstance(worker_result.get("trace_slots"), dict) else {}

    terminal_states = WORKER_TERMINAL_STATES
    expected_ceiling = str(validation_report.get("expected_outcome_ceiling", "")) or str(template.get("expected_outcome_ceiling", ""))
    followup_allowed = bool(template.get("followup_allowed"))
    allowed_claims = [str(item) for item in template.get("allowed_claims", []) if str(item)]
    disallowed_claims = [str(item) for item in template.get("disallowed_claims", []) if str(item)]
    required_read_order_refs = [str(item) for item in template.get("required_read_order_refs", []) if str(item)]
    required_primary_symbols = [str(item) for item in template.get("required_primary_symbols", []) if str(item)]
    valid_stop_conditions = {str(item) for item in template.get("valid_stop_conditions", []) if str(item)}

    observed_slice_refs = [
        str(item)
        for item in (trace_slots.get("opened_slice_refs", []) or result_slots.get("inspected_slice_refs", []))
        if str(item)
    ]
    observed_symbols = [
        str(item)
        for item in (trace_slots.get("opened_symbols", []) or result_slots.get("inspected_symbols", []))
        if str(item)
    ]
    attempted_claims = [
        str(item)
        for item in (trace_slots.get("claim_attempts", []) or validation_report.get("attempted_claims", []))
        if str(item)
    ]
    accepted_claims = [str(item) for item in validation_report.get("accepted_claims", []) if str(item)]
    rejected_claims = [str(item) for item in validation_report.get("rejected_claims", []) if str(item)]
    final_outcome_mode = str(result_slots.get("final_outcome_mode", "")).strip()
    final_claim = str(result_slots.get("final_claim", "")).strip()
    completion_state = str(
        trace_slots.get("completion_state", "")
        or result_slots.get("completion_state", "")
        or template.get("default_completion_state", "ready_for_execution")
    ).strip()
    stop_condition_hit = str(
        trace_slots.get("stop_condition_triggered", "")
        or result_slots.get("stop_condition_hit", "")
    ).strip()
    followup_touched = bool(
        trace_slots.get("followup_touched")
        if "followup_touched" in trace_slots
        else result_slots.get("followup_used")
    )
    supporting_refs = [str(item) for item in result_slots.get("supporting_refs", []) if str(item)]

    read_order_coverage = _build_read_order_coverage(required_read_order_refs, observed_slice_refs)
    primary_target_coverage = _build_primary_target_coverage(required_primary_symbols, observed_symbols)

    if not attempted_claims:
        claim_surface_status = "no_claims_attempted"
    elif rejected_claims:
        claim_surface_status = "contains_rejected_claims"
    elif accepted_claims:
        claim_surface_status = "bounded_claim_surface"
    else:
        claim_surface_status = "no_accepted_claims"

    if completion_state in terminal_states:
        stop_status = (
            "terminal_stop_recorded"
            if stop_condition_hit in valid_stop_conditions
            else "terminal_stop_missing_or_invalid"
        )
    elif completion_state in {"ready_for_execution", "in_progress"}:
        stop_status = "non_terminal"
    else:
        stop_status = "unsupported_completion_state"

    if followup_allowed and followup_touched:
        followup_status = "used_allowed_followup"
    elif followup_allowed:
        followup_status = "open_not_used"
    elif followup_touched:
        followup_status = "violated_closed_gate"
    else:
        followup_status = "closed_and_respected"

    is_non_terminal = completion_state in {"ready_for_execution", "in_progress"}

    if validation_report.get("valid"):
        if is_non_terminal:
            contract_status = "within_bounds_but_non_terminal"
            boundedness_status = "pending_execution" if completion_state == "ready_for_execution" else "execution_in_progress"
        else:
            contract_status = "warnings_only" if validation_report.get("warnings") else "within_bounds"
            boundedness_status = "within_bounds"
    else:
        contract_status = "violations_present"
        boundedness_status = "violated_contract"

    if not validation_report.get("valid"):
        accepted_outcome_mode = "rejected_pending_fix"
        official_result = {
            "accepted_outcome_mode": "rejected_pending_fix",
            "accepted_claim": "",
            "supporting_refs": [],
            "stop_condition": stop_condition_hit,
            "boundedness_status": "rejected_pending_fix",
            "provisional_capped_outcome_mode": str(validation_report.get("capped_outcome_mode", "")),
        }
    elif is_non_terminal:
        accepted_outcome_mode = "pending_execution" if completion_state == "ready_for_execution" else "in_progress"
        official_result = {
            "accepted_outcome_mode": accepted_outcome_mode,
            "accepted_claim": "",
            "supporting_refs": [],
            "stop_condition": "",
            "boundedness_status": "pending_execution" if completion_state == "ready_for_execution" else "execution_in_progress",
            "provisional_capped_outcome_mode": str(validation_report.get("capped_outcome_mode", "")),
        }
    else:
        accepted_outcome_mode = final_outcome_mode or str(validation_report.get("capped_outcome_mode", "")) or expected_ceiling
        accepted_claim = (
            final_claim
            if final_claim and final_claim in accepted_claims
            else (accepted_claims[0] if accepted_claims else "")
        )
        official_result = {
            "accepted_outcome_mode": accepted_outcome_mode,
            "accepted_claim": accepted_claim,
            "supporting_refs": supporting_refs,
            "stop_condition": stop_condition_hit,
            "boundedness_status": "accepted_within_bounds",
        }

    if not validation_report.get("valid"):
        next_action = "fix_worker_result"
    elif completion_state == "ready_for_execution":
        next_action = "execute_worker"
    elif completion_state == "in_progress":
        next_action = "continue_execution"
    elif followup_allowed and accepted_outcome_mode in {"partial", "unproven", "ambiguous"}:
        next_action = "rerun_with_followup"
    elif accepted_outcome_mode in {"partial", "unproven", "ambiguous"}:
        next_action = "stop_on_current_bounds"
    else:
        next_action = "accept_result"

    if not validation_report.get("valid"):
        validation_message = "Worker result violates the bounded contract and must be fixed before acceptance."
    elif is_non_terminal:
        validation_message = "Worker result is still non-terminal; it stays within the contract so far but is not yet an accepted bounded result."
    else:
        validation_message = "Worker result stays within the bounded contract."

    return {
        "valid": bool(validation_report.get("valid")),
        "accepted_result_mode": accepted_outcome_mode,
        "capped_outcome_mode": str(validation_report.get("capped_outcome_mode", "")),
        "attempted_claims": attempted_claims,
        "accepted_claims": accepted_claims,
        "rejected_claims": rejected_claims,
        "claim_surface_status": claim_surface_status,
        "read_order_coverage": read_order_coverage,
        "primary_target_coverage": primary_target_coverage,
        "contract_adherence": {
            "status": contract_status,
            "rules_checked": len(contract.get("worker_validation_rules", [])) if isinstance(contract.get("worker_validation_rules"), list) else 0,
            "violations_count": len(validation_report.get("violations", [])),
            "warnings_count": len(validation_report.get("warnings", [])),
            "used_only_allowed_claims": not rejected_claims,
            "required_sequence_status": str(read_order_coverage.get("sequence_status", "")),
        },
        "stop_analysis": {
            "completion_state": completion_state,
            "stop_condition_hit": stop_condition_hit,
            "status": stop_status,
            "valid_stop_conditions": sorted(valid_stop_conditions),
        },
        "followup_gate_status": {
            "allowed": followup_allowed,
            "used": followup_touched,
            "status": followup_status,
        },
        "boundedness_status": boundedness_status,
        "validation_summary": {
            "status": (
                "invalid"
                if not validation_report.get("valid")
                else ("pending_execution" if is_non_terminal else "valid")
            ),
            "violation_count": len(validation_report.get("violations", [])),
            "warning_count": len(validation_report.get("warnings", [])),
            "message": validation_message,
        },
        "violations": list(validation_report.get("violations", [])),
        "warnings": list(validation_report.get("warnings", [])),
        "recommended_fix": str(validation_report.get("recommended_fix", "")),
        "official_result": official_result,
        "next_action": next_action,
        "trace_expectations": trace_template.get("trace_expectations", {}) if isinstance(trace_template.get("trace_expectations"), dict) else {},
        "trace_observed": {
            "opened_slice_refs": observed_slice_refs,
            "opened_symbols": observed_symbols,
            "claim_attempts": attempted_claims,
            "accepted_claims": accepted_claims,
            "rejected_claims": rejected_claims,
            "followup_touched": followup_touched,
        },
        "worker_mode": str(worker_result.get("worker_mode", "") or template.get("worker_mode", "")),
        "task": str(worker_result.get("task", "") or ask_pack.get("query", "")),
        "expected_outcome_ceiling": expected_ceiling,
        "minimum_honest_outcome": str(validation_report.get("minimum_honest_outcome", "")),
        "allowed_claims": allowed_claims,
        "disallowed_claims": disallowed_claims,
        "contract_source": str(validation_report.get("contract_source", contract.get("contract_source", ""))),
    }


def _build_markdown_report(report: Dict[str, object]) -> str:
    import datetime as _dt

    meta = report.get("meta", {})
    version = meta.get("version", "?")
    node_count = meta.get("node_count", 0)
    edge_count = meta.get("edge_count", 0)
    cycle_count = meta.get("cycle_count", 0)
    lang_dist: Dict[str, int] = meta.get("language_distribution", {})
    generated = meta.get("generated_at") or _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines: List[str] = []
    lines.append("# SIA Report\n")
    lines.append(
        f"> Generated {generated} | SIA v{version} | "
        f"{node_count} nodes | {edge_count} edges | {cycle_count} cycles\n"
    )
    lines.append("")

    top_risks: List[Dict[str, object]] = report.get("top_risks", [])
    if top_risks:
        lines.append("## Top Risks\n")
        lines.append("| # | Symbol | Lang | Kind | Score | Ca | Ce | Instability | SPOF |")
        lines.append("|---|--------|------|------|-------|----|----|-------------|------|")
        for rank, entry in enumerate(top_risks, start=1):
            sym = str(entry.get("symbol", ""))
            lang = str(entry.get("language", ""))
            kind = str(entry.get("kind", ""))
            score = float(entry.get("risk_score", 0.0))
            metrics = entry.get("metrics", {})
            ca = metrics.get("ca", 0)
            ce = metrics.get("ce_total", 0)
            inst = metrics.get("instability", 0.0)
            spof = "yes" if entry.get("single_point_of_failure") else ""
            signals = entry.get("semantic_signals", [])
            sig_str = (
                f"<br>*{', '.join(str(s) for s in signals[:3])}{'...' if len(signals) > 3 else ''}*"
                if signals else ""
            )
            lines.append(
                f"| {rank} | `{sym}`{sig_str} | {lang} | {kind} | "
                f"{score:.1f} | {ca} | {ce} | {inst:.2f} | {spof} |"
            )
        lines.append("")

    cycles: List[List[str]] = report.get("cycles", [])
    if cycles:
        lines.append("## Dependency Cycles\n")
        lines.append(f"**{len(cycles)} cycle{'s' if len(cycles) != 1 else ''} detected.**\n")
        for i, cycle in enumerate(cycles[:20], start=1):
            chain = " -> ".join(f"`{s}`" for s in cycle) + f" -> `{cycle[0]}`"
            lines.append(f"{i}. {chain}")
        if len(cycles) > 20:
            lines.append(f"\n*...and {len(cycles) - 20} more.*")
        lines.append("")

    if lang_dist:
        lines.append("## Language Distribution\n")
        lines.append("| Language | Nodes |")
        lines.append("|----------|-------|")
        for lang, count in sorted(lang_dist.items(), key=lambda item: -item[1]):
            lines.append(f"| {lang} | {count} |")
        lines.append("")

    module_report: List[Dict[str, object]] = report.get("module_report", [])
    if module_report:
        lines.append("## Module Coupling\n")
        lines.append("| Module | Lang | Ca | Ce | Instability | Parse Errors |")
        lines.append("|--------|------|----|----|-------------|--------------|")
        for mod in module_report[:40]:
            mname = str(mod.get("module", ""))
            mlang = str(mod.get("language", ""))
            mca = mod.get("ca", 0)
            mce = mod.get("ce", 0)
            minst = float(mod.get("instability", 0.0))
            merr = mod.get("parse_errors", 0)
            lines.append(f"| `{mname}` | {mlang} | {mca} | {mce} | {minst:.2f} | {merr} |")
        if len(module_report) > 40:
            lines.append(f"\n*...and {len(module_report) - 40} more modules.*")
        lines.append("")

    return "\n".join(lines)


def _run_sia_why(symbol: str, report_path: str) -> None:
    import sys as _sys

    try:
        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)
    except Exception as exc:
        print(f"Error loading {report_path}: {exc}", file=_sys.stderr)
        raise SystemExit(1)

    risk_entry: Optional[Dict[str, object]] = None
    for entry in report.get("top_risks", []):
        if str(entry.get("symbol", "")) == symbol:
            risk_entry = entry
            break

    node_entry: Optional[Dict[str, object]] = None
    for nd in report.get("nodes", []):
        if str(nd.get("node_id", "")) == symbol:
            node_entry = nd
            break

    if risk_entry is None and node_entry is None:
        print(f"Symbol '{symbol}' not found in {report_path}.", file=_sys.stderr)
        print("Tip: run without --summary-only so 'nodes' is included, or check the symbol name.", file=_sys.stderr)
        raise SystemExit(1)

    sep = "=" * 60
    print(f"\n{sep}")
    print(f"Symbol: {symbol}")
    if risk_entry:
        lang = risk_entry.get("language", "?")
        kind = risk_entry.get("kind", "?")
        score = float(risk_entry.get("risk_score", 0.0))
        spof = risk_entry.get("single_point_of_failure", False)
        metrics = risk_entry.get("metrics", {})
        ca = metrics.get("ca", "?")
        ce = metrics.get("ce_total", "?")
        inst = metrics.get("instability", "?")
        git_h = metrics.get("git_hotspot_score", 0)
        signals: List[str] = [str(s) for s in risk_entry.get("semantic_signals", [])]
        print(f"Language: {lang}  Kind: {kind}  Risk score: {score:.1f}  SPOF: {'yes' if spof else 'no'}")
        print()
        print("Coupling")
        print(f"  Afferent  Ca = {ca}   (symbols that depend on this one)")
        print(f"  Efferent  Ce = {ce}   (symbols this one depends on)")
        print(f"  Instability    = {inst if isinstance(inst, str) else f'{inst:.2f}'}")
        if git_h:
            print(f"  Git hotspot    = {git_h:.2f}")
        if signals:
            print()
            print(f"Semantic signals: {', '.join(signals)}")
    elif node_entry:
        print(f"(Not in top risks - node found with risk_score={node_entry.get('risk_score', '?')})")

    callers: List[str] = []
    callees: List[str] = []
    for edge in report.get("edges", []):
        if isinstance(edge, dict):
            src = str(edge.get("source", ""))
            dst = str(edge.get("target", ""))
        elif isinstance(edge, (list, tuple)) and len(edge) >= 2:
            src = str(edge[0])
            dst = str(edge[1])
        else:
            continue
        if dst == symbol:
            callers.append(src)
        if src == symbol:
            callees.append(dst)

    if callers or callees:
        print()
        if callers:
            print(f"Incoming edges ({len(callers)}):")
            for c in sorted(callers)[:10]:
                print(f"  <- {c}")
            if len(callers) > 10:
                print(f"  ... and {len(callers) - 10} more")
        if callees:
            print(f"Outgoing edges ({len(callees)}):")
            for c in sorted(callees)[:10]:
                print(f"  -> {c}")
            if len(callees) > 10:
                print(f"  ... and {len(callees) - 10} more")

    cycles_with: List[List[str]] = [
        c for c in report.get("cycles", []) if symbol in c
    ]
    if cycles_with:
        print()
        print(f"Dependency cycles containing this symbol ({len(cycles_with)}):")
        for cycle in cycles_with[:5]:
            print(f"  {' -> '.join(cycle)} -> {cycle[0]}")
    else:
        print()
        print("Dependency cycles: none")

    print(sep)


def _run_sia_diff(old_path: str, new_path: str) -> None:
    import sys as _sys

    def _load(path: str) -> Dict[str, object]:
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:
            print(f"Error loading {path}: {exc}", file=_sys.stderr)
            raise SystemExit(1)

    old_data = _load(old_path)
    new_data = _load(new_path)

    old_risks = {str(r["symbol"]): float(r["risk_score"]) for r in old_data.get("top_risks", [])}
    new_risks = {str(r["symbol"]): float(r["risk_score"]) for r in new_data.get("top_risks", [])}

    appeared = sorted((s, sc) for s, sc in new_risks.items() if s not in old_risks)
    resolved = sorted((s, sc) for s, sc in old_risks.items() if s not in new_risks)
    improved = sorted(
        (s, old_risks[s], new_risks[s])
        for s in old_risks if s in new_risks and old_risks[s] - new_risks[s] >= 1.0
    )
    degraded = sorted(
        (s, old_risks[s], new_risks[s])
        for s in old_risks if s in new_risks and new_risks[s] - old_risks[s] >= 1.0
    )
    unchanged_count = sum(
        1 for s in old_risks if s in new_risks and abs(new_risks[s] - old_risks[s]) < 1.0
    )

    old_ver = old_data.get("meta", {}).get("version", "?")
    new_ver = new_data.get("meta", {}).get("version", "?")
    old_nodes = old_data.get("meta", {}).get("node_count", "?")
    new_nodes = new_data.get("meta", {}).get("node_count", "?")

    sep = "=" * 56
    print(f"\nSIA Diff  {old_path}  ->  {new_path}")
    print(sep)
    print(f"Version : {old_ver} -> {new_ver}")
    if old_nodes != "?" and new_nodes != "?":
        delta_n = int(new_nodes) - int(old_nodes)
        print(f"Nodes   : {old_nodes} -> {new_nodes}  ({'+' if delta_n >= 0 else ''}{delta_n})")
    print()

    if appeared:
        print(f"NEW RISKS ({len(appeared)} appeared):")
        for sym, sc in appeared:
            print(f"  +  {sym:<60}  score={sc}")
        print()
    if resolved:
        print(f"RESOLVED ({len(resolved)} no longer in top risks):")
        for sym, sc in resolved:
            print(f"  -  {sym:<60}  score={sc}")
        print()
    if improved:
        print("IMPROVED (score down >=1.0):")
        for sym, old_sc, new_sc in improved:
            print(f"  ~  {sym:<60}  {old_sc} -> {new_sc}  ({new_sc - old_sc:+.1f})")
        print()
    if degraded:
        print("DEGRADED (score up >=1.0):")
        for sym, old_sc, new_sc in degraded:
            print(f"  !  {sym:<60}  {old_sc} -> {new_sc}  ({new_sc - old_sc:+.1f})")
        print()
    print(f"UNCHANGED: {unchanged_count} risks within +/-1.0")
    print(sep)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic structural integrity analysis for multi-language projects.")
    parser.add_argument("root", nargs="?", default=".", help="Project root directory (default: current directory).")
    parser.add_argument("--out", default="sia_report.json", help="Output JSON file path.")
    parser.add_argument(
        "--validate-worker-result",
        default="",
        help="Optional JSON file with a filled worker result to validate against an ask bundle or report.",
    )
    parser.add_argument(
        "--against-ask-bundle",
        default="",
        help="Ask bundle directory containing ask_context_pack.json for worker-result validation.",
    )
    parser.add_argument(
        "--against-report",
        default="",
        help="Report JSON containing ask_context_pack for worker-result validation.",
    )
    question_group = parser.add_mutually_exclusive_group()
    question_group.add_argument(
        "--ask",
        default="",
        help="Optional query/task string for a query-scoped ask context pack.",
    )
    question_group.add_argument(
        "--question-file",
        default="",
        help="Optional UTF-8 text file containing a query/task for a query-scoped ask context pack.",
    )
    parser.add_argument(
        "--bundle-dir",
        default="",
        help="Optional directory for a full LLM context bundle (report, prompt, slices, inventory).",
    )
    parser.add_argument("--top", type=int, default=20, help="How many top risks to include in the summary.")
    parser.add_argument(
        "--context-lines",
        type=int,
        default=220,
        help="Approximate line budget for the LLM context pack.",
    )
    parser.add_argument(
        "--ask-lines",
        type=int,
        default=110,
        help="Approximate line budget for the query-scoped ask context pack.",
    )
    parser.add_argument(
        "--no-git-hotspots",
        action="store_true",
        help="Disable optional Git-history hotspot analysis.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Only write summary sections (top_risks/module_report/cycles), omit full nodes+edges.",
    )
    parser.add_argument(
        "--diff",
        nargs=2,
        metavar=("OLD", "NEW"),
        default=None,
        help="Compare two SIA report JSON files and print the diff. No analysis is run.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "Glob pattern to exclude files or directories (repeatable). "
            "Examples: --exclude 'vendor' --exclude '*.generated.kt' "
            "--exclude 'build'. Matched against directory names and "
            "relative file paths."
        ),
    )
    parser.add_argument(
        "--filter-language",
        default="",
        metavar="LANGS",
        help=(
            "Comma-separated list of languages to analyze (e.g. 'Python,Java'). "
            "All other languages are skipped. Case-sensitive."
        ),
    )
    parser.add_argument(
        "--markdown",
        default="",
        metavar="PATH",
        help="Write a human-readable Markdown report to PATH alongside the JSON output.",
    )
    parser.add_argument(
        "--why",
        nargs=2,
        metavar=("SYMBOL", "REPORT"),
        default=None,
        help="Explain why SYMBOL scores high in REPORT JSON file. No analysis is run.",
    )
    args = parser.parse_args()

    if args.diff:
        _run_sia_diff(args.diff[0], args.diff[1])
        return

    if args.why:
        _run_sia_why(args.why[0], args.why[1])
        return

    if args.validate_worker_result:
        if args.ask or args.question_file:
            parser.error("--validate-worker-result cannot be combined with --ask or --question-file.")
        if args.bundle_dir:
            parser.error("--validate-worker-result cannot be combined with --bundle-dir.")
        if args.summary_only:
            parser.error("--validate-worker-result cannot be combined with --summary-only.")
        if args.no_git_hotspots:
            parser.error("--validate-worker-result cannot be combined with --no-git-hotspots.")

        try:
            contract = _load_worker_contract(
                str(args.against_ask_bundle or "").strip(),
                str(args.against_report or "").strip(),
            )
            worker_result = _load_json_file(os.path.abspath(args.validate_worker_result))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.error(f"Worker-result validation setup failed: {exc}")

        validation_report = validate_worker_result_payload(worker_result, contract)
        worker_result_report = build_worker_result_report(worker_result, contract, validation_report)
        out_arg = str(args.out or "").strip()
        default_out = parser.get_default("out")
        out_path = os.path.abspath(
            "worker_result_report.json" if not out_arg or out_arg == default_out else out_arg
        )
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(worker_result_report, handle, indent=2)

        status = "valid" if worker_result_report.get("valid") else "invalid"
        print(
            "Worker result report completed: "
            f"{status}, violations={len(worker_result_report.get('violations', []))}, "
            f"warnings={len(worker_result_report.get('warnings', []))}, "
            f"accepted_result_mode={worker_result_report.get('accepted_result_mode', '')}, "
            f"next_action={worker_result_report.get('next_action', '')}"
        )
        print(f"Worker result report written to: {out_path}")
        return

    ask_query = str(args.ask or "").strip()
    if args.question_file:
        try:
            with open(args.question_file, "r", encoding="utf-8") as handle:
                ask_query = handle.read().strip()
        except OSError as exc:
            parser.error(f"Could not read --question-file: {exc}")
        if not ask_query:
            parser.error("--question-file did not contain a non-empty query.")

    _filter_langs = [l.strip() for l in args.filter_language.split(",") if l.strip()] if args.filter_language else None
    analyzer = StructuralIntegrityAnalyzerV3(
        args.root,
        exclude_globs=args.exclude or [],
        filter_languages=_filter_langs,
    )
    report = analyzer.run(
        top_n=max(1, args.top),
        include_graph=not args.summary_only,
        context_line_budget=max(20, args.context_lines),
        include_git_hotspots=not args.no_git_hotspots,
        ask_query=ask_query,
        ask_line_budget=max(20, args.ask_lines),
    )

    out_path = os.path.abspath(args.out)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    bundle_out = ""
    if args.bundle_dir:
        bundle_out = analyzer.write_bundle(report, args.bundle_dir)

    meta = report["meta"]
    print(
        f"SIA v3 completed: nodes={meta['node_count']}, edges={meta['edge_count']}, "
        f"cycles={meta['cycle_count']}, git_hotspots={meta['git_hotspots_enabled']}, "
        f"parse_errors={meta['parse_error_count']}"
    )
    print(f"Top risks written to: {out_path}")
    if args.markdown:
        md_path = os.path.abspath(args.markdown)
        md_text = _build_markdown_report(report)
        with open(md_path, "w", encoding="utf-8") as handle:
            handle.write(md_text)
        print(f"Markdown report written to: {md_path}")
    if bundle_out:
        print(f"LLM bundle written to: {bundle_out}")


if __name__ == "__main__":
    main()
