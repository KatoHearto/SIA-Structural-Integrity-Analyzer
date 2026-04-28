# SPRINT R1 — Restrukturierung: Build-Modell + src/ Layout

**Version:** 3.62 (keine Versionsänderung — reine Reorganisation)  
**File:** `god_mode_v3.py` → wird Build-Artefakt  
**Workers:** A + B (koordiniert, kein Code-Overlap)

---

## Ziel

`god_mode_v3.py` (14.809 Zeilen) wird in navigierbare `src/`-Module aufgeteilt.
`build.py` konkateniert sie zurück zu `god_mode_v3.py`. Das Endresultat für Nutzer
ist identisch. Für Worker gilt ab jetzt: Modul-Dateien bearbeiten, nie `god_mode_v3.py`
direkt.

---

## Kritische Regel

**Kein Code wird verändert.** Nur Schneiden und Verschieben. Kein Umbenennen von
Funktionen, kein Refactoring, keine Importe hinzufügen. Jede Zeile landet genau
einmal in genau einer `src/`-Datei. `build.py` setzt sie in der richtigen Reihenfolge
wieder zusammen.

---

## Bekannte Dateistruktur

```
god_mode_v3.py
  Zeilen    1 –  402   Imports, Konstanten, Regex, _TAINT_SOURCE_KINDS
  Zeilen  403 –  691   Hilfsdatenklassen: SymbolNode, ResolutionOutcome,
                        CallCollector, ImportCollector, StringRefCollector
  Zeilen  692 –  834   class StructuralIntegrityAnalyzerV3 + __init__
  Zeilen  835 –  950   run(), _scan_files()
  Zeilen  951 – 1298   Frappe/JSON-Scanner
  Zeilen 1299 – 1455   Parser-Dispatcher (_parse_file, _parse_non_python_file)
  Zeilen 1456 – 2024   JS/TS-Parser-Methoden
  Zeilen 2025 – 2058   Go-Parser
  Zeilen 2059 – 2259   Java-Parser (Modul + C#, Kotlin, PHP, Ruby)
  Zeilen 2260 – 3159   Java-Symbol-Extraktoren (detailliert)
  Zeilen 3160 – 3219   Rust-Parser
  Zeilen 3220 – 3559   _build_indices()
  Zeilen 3560 – 3913   _compute_taint_metadata() + Frappe-Hook-Paths (Sprint 32)
  Zeilen 3914 – 9500   Graph-Aufbau, Metriken, Signale, Analyse (Worker-A-Grenze)
  Zeilen 9500 –13575   Semantische Analyse, Behavioral Flow, LLM-Context-Pack
  Zeilen 13576–13969   Top-Level-Validierungs-Funktionen (außerhalb Klasse)
  Zeilen 13970–14188   build_worker_result_report()
  Zeilen 14189–14332   _build_markdown_report()
  Zeilen 14333–14592   _run_sia_why(), _run_sia_diff()
  Zeilen 14593–14809   main() + CLI
```

---

## Ziel-Layout nach Sprint

```
src/
  00_header.py           Imports, Konstanten, Regex, _TAINT_SOURCE_KINDS (1–402)
  01_core_classes.py     SymbolNode, ResolutionOutcome, Collector-Klassen (403–691)
  02_analyzer_init.py    class StructuralIntegrityAnalyzerV3 + __init__ (692–834)
  03_run_scan.py         run(), _scan_files() (835–950)
  04_frappe_scanner.py   Frappe/JSON-Scanner (951–1298)
  05_parser_dispatch.py  _parse_file, _parse_non_python_file (1299–1455)
  06_parser_js.py        JS/TS-Parser-Methoden (1456–2024)
  07_parser_go.py        Go-Parser (2025–2058)
  08_parser_java.py      Java-Parser + Symbol-Extraktoren (2059–3159)
  09_parser_rust.py      Rust-Parser (3160–3219)
  10_parser_other.py     C#, Kotlin, PHP, Ruby (eingebettet in 2059–3159,
                          exakter Bereich Worker A ermittelt)
  11_graph_indices.py    _build_indices() (3220–3559)
  12_taint.py            _compute_taint_metadata() + Hook-Paths (3560–3913)
  13_graph_metrics.py    Graph-Aufbau, PageRank, Betweenness, Layers (3914–9500)
  14_analysis.py         Semantik, Behavioral Flow, LLM-Pack (9500–13575)
  15_worker_validation.py Top-Level-Validierung (13576–13969)
  16_report_builders.py  build_worker_result_report() (13970–14188)
  17_markdown_report.py  _build_markdown_report() (14189–14332)
  18_sia_commands.py     _run_sia_why(), _run_sia_diff() (14333–14592)
  19_cli.py              main() + CLI (14593–14809)

build.py                 Konkateniert src/00 … src/19 → god_mode_v3.py
god_mode_v3.py           BUILD-ARTEFAKT — nie direkt bearbeiten

tests/
  fixtures/
    minimal/             war .sia_fixture/
    multilang/           war .multilang_fixture/
    polyglot/            war .polyglot_graph_fixture/
```

---

## Worker A — Zuständigkeit

**Aufgabe:** Zeilen 1–9500 in `src/00_` bis `src/13_` extrahieren.

Vorgehen:
1. `god_mode_v3.py` lesen
2. Exakte Schnittlinien für jedes Modul bestimmen (Klassenanfang/-ende von
   Methoden ist die natürliche Grenze — nie mitten in eine Methode schneiden)
3. Jede `src/`-Datei mit einem einzeiligen Kommentar-Header beginnen:
   ```python
   # ── SIA src/06_parser_js.py ── (god_mode_v3.py lines 1456–2024) ──────────
   ```
4. Inhalt exakt kopieren — keine Änderungen
5. Fixtures verschieben:
   - `.sia_fixture/`          → `tests/fixtures/minimal/`
   - `.multilang_fixture/`    → `tests/fixtures/multilang/`
   - `.polyglot_graph_fixture/` → `tests/fixtures/polyglot/`

Ausgabe in `worker_output_a.md`:
- Tatsächliche Zeilenbereiche pro Datei (können von der Schätzung oben abweichen)
- Bestätigung: keine Zeile fehlt, keine Zeile doppelt

---

## Worker B — Zuständigkeit

**Aufgabe:** Zeilen 9500–14809 in `src/14_` bis `src/19_` extrahieren + `build.py`
schreiben + Gesamtverifikation.

Vorgehen:
1. Zeilen 9500–14809 in die entsprechenden `src/`-Dateien extrahieren (gleiche
   Regeln wie Worker A — Kommentar-Header, kein Code-Change)
2. `build.py` schreiben:

```python
#!/usr/bin/env python3
"""Build god_mode_v3.py from src/ modules."""
import pathlib

MODULES = [
    "src/00_header.py",
    "src/01_core_classes.py",
    "src/02_analyzer_init.py",
    "src/03_run_scan.py",
    "src/04_frappe_scanner.py",
    "src/05_parser_dispatch.py",
    "src/06_parser_js.py",
    "src/07_parser_go.py",
    "src/08_parser_java.py",
    "src/09_parser_rust.py",
    "src/10_parser_other.py",
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
    parts.append(pathlib.Path(mod).read_text(encoding="utf-8"))

out.write_text("\n".join(parts), encoding="utf-8")
print(f"Built god_mode_v3.py ({out.stat().st_size:,} bytes, {len(parts)} modules)")
```

3. `python build.py` ausführen → `god_mode_v3.py` wird neu generiert

---

## Verifikationsprotokoll (Worker B führt aus)

```bash
# 1. Syntax
python -m py_compile god_mode_v3.py
# Erwartet: kein Output

# 2. Analyse-Ergebnis identisch zu Sprint-32-Baseline
python god_mode_v3.py . --out r1_test.json --no-git-hotspots --filter-language Python
# Erwartet: nodes=397  edges=688  cycles=1  parse_errors=0
# (identisch mit Sprint-32-Plain-Run aus worker_output_a.md)

# 3. Taint läuft noch
python god_mode_v3.py . --out r1_taint.json --taint --no-git-hotspots --filter-language Python
# Erwartet: nodes=409  edges=703  entry_points=16  tainted_params=17

# 4. Zeilenzahl plausibel (Kommentar-Header addieren ein paar Zeilen)
wc -l god_mode_v3.py
# Erwartet: 14809 + Anzahl der src/-Dateien (±20 Zeilen für Header-Kommentare)
```

Alle vier Checks müssen grün sein. Bei Abweichung: Diff zwischen altem und neuem
`god_mode_v3.py` zeigen wo die Diskrepanz liegt.

---

## Was sich nach diesem Sprint ändert

**Für Worker:**
- Nie mehr `god_mode_v3.py` direkt bearbeiten
- Nach jeder Änderung an einer `src/`-Datei: `python build.py` ausführen
- `py_compile` läuft auf `god_mode_v3.py` (dem Build-Output), nicht auf `src/`-Files
- Version-Bump: in `src/00_header.py` (dort liegt die version-Konstante bei Zeile ~773)

**Für Brain (Orchestrator):**
- Sprint-Briefings referenzieren ab jetzt `src/`-Dateien statt Zeilennummern
- WORKER_GUIDE.md wird nach diesem Sprint aktualisiert

**Für Nutzer:** Nichts. `god_mode_v3.py` ist identisch.

---

## Was sich NICHT ändert

- Kein Code, keine Logik, keine Konstanten
- Keine neuen Features, keine Bug-Fixes
- Keine Versionsänderung (3.62 bleibt 3.62)
- Alle bestehenden CLI-Flags funktionieren unverändert
