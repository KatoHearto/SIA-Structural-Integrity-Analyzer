# ── SIA src/17_markdown_report.py ── (god_mode_v3.py lines 14189–14332) ────────────────────

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
        lines.append(
            "> **dynamic_dispatch** - symbol is invoked via a string literal reference; "
            "renaming it silently breaks callers."
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

    doctype_nodes = [
        n for n in report.get("nodes", [])
        if isinstance(n, dict) and n.get("kind") == "doctype"
    ]
    if doctype_nodes:
        lines.append("\n## Frappe DocType Coupling\n")
        lines.append("| DocType | Link fields | Child tables | Controller | ORM References |")
        lines.append("|---------|-------------|--------------|------------|----------------|")
        for n in sorted(doctype_nodes, key=lambda x: str(x.get("qualname", ""))):
            node_id = str(n.get("node_id", ""))
            pd = n.get("plugin_data", {}) if isinstance(n.get("plugin_data", {}), dict) else {}
            name = str(pd.get("frappe_doctype_name", n.get("qualname", "")))
            links = ", ".join(str(item) for item in pd.get("frappe_link_refs", [])) or "-"
            children = ", ".join(str(item) for item in pd.get("frappe_child_refs", [])) or "-"
            ctrl = str(pd.get("frappe_controller_path", "-") or "-")

            orm_sources = []
            for ed in report.get("edge_details", []):
                if str(ed.get("target")) == node_id and "string_ref" in ed.get("kinds", []):
                    src = str(ed.get("source", ""))
                    short_src = src.split(":")[1] if ":" in src else src
                    orm_sources.append(f"`{short_src}`")
            orm_refs = ", ".join(sorted(set(orm_sources))) or "-"

            lines.append(f"| {name} | {links} | {children} | `{ctrl}` | {orm_refs} |")
        lines.append("")

    arch_warnings: List[Dict[str, object]] = report.get("architectural_warnings", [])
    if arch_warnings:
        total = sum(len(entry.get("warnings", [])) for entry in arch_warnings)
        lines.append("\n## Architectural Warnings\n")
        lines.append(
            f"**{total} warning{'s' if total != 1 else ''} across "
            f"{len(arch_warnings)} symbol{'s' if len(arch_warnings) != 1 else ''}.**\n"
        )
        lines.append("| Severity | Symbol | Rule | Message |")
        lines.append("|----------|--------|------|---------|")
        _sev_order = {"critical": 0, "high": 1, "medium": 2}
        rows = []
        for entry in arch_warnings:
            sym = str(entry.get("node_id", ""))
            for w in entry.get("warnings", []):
                sev = str(w.get("severity", "medium"))
                rows.append((
                    _sev_order.get(sev, 99),
                    sym,
                    sev,
                    str(w.get("rule", "")),
                    str(w.get("message", "")),
                ))
        rows.sort()
        for _, sym, sev, rule, msg in rows:
            lines.append(f"| **{sev}** | `{sym}` | `{rule}` | {msg} |")
        lines.append("")

    return "\n".join(lines)
