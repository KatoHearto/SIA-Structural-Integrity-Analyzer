# ── SIA src/18_sia_commands.py ── (god_mode_v3.py lines 14333–14592) ────────────────────

def _run_sia_why(symbol: str, report_path: str) -> None:
    import sys as _sys

    try:
        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)
    except Exception as exc:
        print(f"Error loading {report_path}: {exc}", file=_sys.stderr)
        raise SystemExit(1)
    if not isinstance(report, dict) or "meta" not in report:
        print(f"Invalid or incompatible SIA report — missing required keys: {report_path}", file=_sys.stderr)
        raise SystemExit(1)

    risk_entry: Optional[Dict[str, object]] = None
    for entry in report.get("top_risks", []):
        if str(entry.get("symbol", "")) == symbol:
            risk_entry = entry
            break

    node_entry: Optional[Dict[str, object]] = None
    for nd in report.get("nodes", []):
        if str(nd.get("node_id", "") or nd.get("id", "") or nd.get("symbol", "")) == symbol:
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
        resolved_string_refs: List[str] = []
        if isinstance(node_entry, dict):
            resolved_string_refs = [str(ref) for ref in node_entry.get("resolved_string_refs", []) if str(ref)]
        elif isinstance(risk_entry, dict):
            resolved_string_refs = [str(ref) for ref in risk_entry.get("resolved_string_refs", []) if str(ref)]
        print(f"  Dynamic string refs  {len(resolved_string_refs)} resolved target(s)")
        for target in sorted(resolved_string_refs):
            print(f"    -> {target}")
        if git_h:
            print(f"  Git hotspot    = {git_h:.2f}")
        if signals:
            print()
            print(f"Semantic signals: {', '.join(signals)}")
        reachable = sorted(str(g) for g in risk_entry.get("reachable_guards", []) if g)
        if reachable:
            print(f"Guard coverage (from callers, depth ≤ 2): {', '.join(reachable)}")
    elif node_entry:
        lang = node_entry.get("language", "?")
        kind = node_entry.get("kind", "?")
        score = float(node_entry.get("risk_score", 0.0))
        metrics = node_entry.get("metrics", {})
        ca = metrics.get("ca", "?")
        ce = metrics.get("ce_total", "?")
        inst = metrics.get("instability", "?")
        signals = [str(s) for s in node_entry.get("semantic_signals", [])]
        resolved_string_refs = [str(ref) for ref in node_entry.get("resolved_string_refs", []) if str(ref)]
        print(f"(Not in top risks - node found with risk_score={score:.2f})")
        print(f"Language: {lang}  Kind: {kind}")
        print()
        print("Coupling")
        print(f"  Afferent  Ca = {ca}   (symbols that depend on this one)")
        print(f"  Efferent  Ce = {ce}   (symbols this one depends on)")
        print(f"  Instability    = {inst if isinstance(inst, str) else f'{inst:.2f}'}")
        print(f"  Dynamic string refs  {len(resolved_string_refs)} resolved target(s)")
        for target in sorted(resolved_string_refs):
            print(f"    -> {target}")
        if signals:
            print()
            print(f"Semantic signals: {', '.join(signals)}")
        reachable = sorted(str(g) for g in node_entry.get("reachable_guards", []) if g)
        if reachable:
            print(f"Guard coverage (from callers, depth ≤ 2): {', '.join(reachable)}")

    detail_entry = node_entry if isinstance(node_entry, dict) else (risk_entry if isinstance(risk_entry, dict) else None)
    if detail_entry and detail_entry.get("kind") == "doctype":
        pd = detail_entry.get("plugin_data", {})
        if not isinstance(pd, dict):
            pd = {}
        print(
            f"\nFrappe DocType: {pd.get('frappe_doctype_name', '')}  "
            f"module={pd.get('frappe_module', '')}  "
            f"single={pd.get('frappe_is_single', False)}  "
            f"virtual={pd.get('frappe_is_virtual', False)}"
        )
        link_refs = [str(item) for item in pd.get("frappe_link_refs", [])]
        child_refs = [str(item) for item in pd.get("frappe_child_refs", [])]
        if link_refs:
            print(f"  Link fields -> {', '.join(link_refs)}")
        if child_refs:
            print(f"  Child tables -> {', '.join(child_refs)}")
        ctrl = str(pd.get("frappe_controller_path", ""))
        if ctrl:
            print(f"  Controller: {ctrl}")

    callers: List[str] = []
    callees: List[str] = []
    edge_details = report.get("edge_details", [])
    for edge in report.get("edges", []):
        if isinstance(edge, dict):
            src = str(edge.get("source", ""))
            dst = str(edge.get("target", ""))
        elif isinstance(edge, (list, tuple)) and len(edge) >= 2:
            src = str(edge[0])
            dst = str(edge[1])
        else:
            continue

        kinds = []
        for ed in edge_details:
            if str(ed.get("source")) == src and str(ed.get("target")) == dst:
                kinds = ed.get("kinds", [])
                break
        kind_label = ""
        if "string_ref" in kinds:
            kind_label = " [ORM LOAD]"

        if dst == symbol:
            callers.append(f"{src}{kind_label}")
        if src == symbol:
            callees.append(f"{dst}{kind_label}")

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

    arch_warnings_for_symbol: List[Dict[str, object]] = []
    for aw in report.get("architectural_warnings", []):
        if str(aw.get("node_id", "")) == symbol:
            arch_warnings_for_symbol = list(aw.get("warnings", []))
            break
    if not arch_warnings_for_symbol and detail_entry:
        arch_warnings_for_symbol = list(detail_entry.get("architectural_warnings", []))
    if arch_warnings_for_symbol:
        print()
        print(f"Architectural Warnings ({len(arch_warnings_for_symbol)}):")
        for w in arch_warnings_for_symbol:
            sev = str(w.get("severity", "?")).upper()
            rule = str(w.get("rule", ""))
            msg = str(w.get("message", ""))
            print(f"  [{sev}] {rule}: {msg}")

    print(sep)


def _run_sia_diff(old_path: str, new_path: str) -> None:
    import sys as _sys

    def _load(path: str) -> Dict[str, object]:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            print(f"Error loading {path}: {exc}", file=_sys.stderr)
            raise SystemExit(1)
        if not isinstance(data, dict) or "meta" not in data:
            print(f"Invalid or incompatible SIA report — missing required keys: {path}", file=_sys.stderr)
            raise SystemExit(1)
        return data

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
