# ── SIA src/19_cli.py ── (god_mode_v3.py lines 14593–14809) ────────────────────

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
        "--taint",
        action="store_true",
        help="Enable taint-source classification and include taint metadata in the JSON report.",
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
        "--plugin",
        default="",
        metavar="NAMES",
        help=(
            "Comma-separated plugin names to activate (e.g. 'frappe'). "
            "Currently supported: frappe."
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
        plugins=[p.strip() for p in args.plugin.split(",") if p.strip()] if args.plugin else None,
    )
    report = analyzer.run(
        top_n=max(1, args.top),
        include_graph=not args.summary_only,
        context_line_budget=max(20, args.context_lines),
        include_git_hotspots=not args.no_git_hotspots,
        ask_query=ask_query,
        ask_line_budget=max(20, args.ask_lines),
        enable_taint=args.taint,
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
