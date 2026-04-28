#!/usr/bin/env python3
"""Build god_mode_v3.py from src/ modules. Run after any change to a src/ file."""
import pathlib

MODULES = [
    "src/00_header.py",
    "src/01_core_classes.py",
    "src/02_analyzer_init.py",
    "src/03_run_scan.py",
    "src/04_frappe_scanner.py",
    "src/05_parser_dispatch.py",
    "src/10_parser_other.py",
    "src/06_parser_js.py",
    "src/07_parser_go.py",
    "src/08_parser_java.py",
    "src/09_parser_rust.py",
    "src/11_graph_indices.py",
    "src/12_taint.py",
    "src/13_graph_metrics.py",
    "src/14_analysis.py",
    "src/15_worker_validation.py",
    "src/16_report_builders.py",
    "src/17_markdown_report.py",
    "src/18_sia_commands.py",
    "src/19_cli.py",
]

out = pathlib.Path("god_mode_v3.py")
parts = []
for mod in MODULES:
    p = pathlib.Path(mod)
    if not p.exists():
        raise FileNotFoundError(f"Module not found: {mod}")
    parts.append(p.read_text(encoding="utf-8"))

out.write_text("\n".join(parts), encoding="utf-8")
print(f"Built god_mode_v3.py ({out.stat().st_size:,} bytes, {len(parts)} modules)")
