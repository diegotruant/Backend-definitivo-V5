#!/usr/bin/env python3
"""Generate WT coach demo paper PDF (Italian) with live engine numbers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List

from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "DEMO_WT_COACH_PAPER.pdf"
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
MARGIN = 18
CONTENT_W = 174


def _load_demo_metrics() -> Dict[str, Any]:
    spec = importlib.util.spec_from_file_location("wt_demo", ROOT / "tools" / "demo" / "wt_coach_demo.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Suppress demo print during import/run
    old_stdout = sys.stdout
    sys.stdout = open("/dev/null", "w")
    try:
        spec.loader.exec_module(mod)
        data = mod.run_demo(pause_enabled=False, as_json=True)
    finally:
        sys.stdout.close()
        sys.stdout = old_stdout
    return data


class PaperPDF(FPDF):
    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=20)
        self.set_left_margin(MARGIN)
        self.set_right_margin(MARGIN)
        self.add_font("DV", "", str(FONT_DIR / "DejaVuSans.ttf"))
        self.add_font("DV", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("DV", "", 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 8, f"Digital Twin — Demo paper coach World Tour  |  {self.page_no()}", align="C")

    def cover(self) -> None:
        self.add_page()
        self.set_font("DV", "B", 20)
        self.set_text_color(25, 55, 95)
        self.ln(25)
        self.multi_cell(CONTENT_W, 10, "Digital Twin\nDemo paper per coach World Tour", align="C")
        self.ln(8)
        self.set_font("DV", "", 12)
        self.set_text_color(70, 70, 70)
        self.multi_cell(
            CONTENT_W,
            6,
            "Validazione Mader al lattato\ne Team Learning con audit trail",
            align="C",
        )
        self.ln(20)
        self.set_font("DV", "", 10)
        self.set_text_color(100, 100, 100)
        self.multi_cell(
            CONTENT_W,
            5.5,
            "Documento dimostrativo · Backend fisiologico v5.2.1\n"
            "Caso studio: Squadra Demo WT — settimana test giugno 2026",
            align="C",
        )

    def h1(self, text: str) -> None:
        self.ln(4)
        self.set_font("DV", "B", 13)
        self.set_text_color(25, 55, 95)
        self.multi_cell(CONTENT_W, 7, text)
        self.ln(2)

    def h2(self, text: str) -> None:
        self.ln(2)
        self.set_font("DV", "B", 11)
        self.set_text_color(40, 70, 110)
        self.multi_cell(CONTENT_W, 6, text)
        self.ln(1)

    def body(self, text: str) -> None:
        self.set_font("DV", "", 10)
        self.set_text_color(45, 45, 45)
        self.multi_cell(CONTENT_W, 5.2, text)
        self.ln(2)

    def quote(self, text: str) -> None:
        self.set_fill_color(245, 248, 252)
        self.set_draw_color(180, 195, 215)
        y0 = self.get_y()
        self.set_font("DV", "", 9)
        self.set_text_color(55, 55, 55)
        self.set_x(MARGIN + 4)
        self.multi_cell(CONTENT_W - 8, 5, text, fill=True)
        self.rect(MARGIN, y0, CONTENT_W, self.get_y() - y0)
        self.ln(3)

    def bullets(self, items: List[str]) -> None:
        self.set_font("DV", "", 10)
        self.set_text_color(45, 45, 45)
        for item in items:
            self.multi_cell(CONTENT_W, 5.2, f"  •  {item}")
        self.ln(2)

    def table(self, headers: List[str], rows: List[List[str]], widths: List[int]) -> None:
        self.set_font("DV", "B", 8)
        self.set_fill_color(230, 236, 245)
        self.set_text_color(25, 55, 95)
        for i, h in enumerate(headers):
            self.cell(widths[i], 6, h, border=1, fill=True)
        self.ln()
        self.set_font("DV", "", 8)
        self.set_text_color(45, 45, 45)
        for row in rows:
            x0, y0 = self.get_x(), self.get_y()
            max_h = 6
            lines_per_cell: List[List[str]] = []
            for i, cell in enumerate(row):
                lines_per_cell.append(
                    self.multi_cell(widths[i], 4.5, cell, dry_run=True, output="LINES")
                )
                max_h = max(max_h, len(lines_per_cell[-1]) * 4.5)
            for i, lines in enumerate(lines_per_cell):
                x = x0 + sum(widths[:i])
                self.rect(x, y0, widths[i], max_h)
                for j, line in enumerate(lines):
                    self.set_xy(x + 1, y0 + 1 + j * 4.5)
                    self.cell(widths[i] - 2, 4.5, line)
            self.set_xy(x0, y0 + max_h)
        self.ln(3)

    def diagram_box(self, lines: List[str]) -> None:
        self.set_fill_color(248, 249, 252)
        self.set_draw_color(160, 175, 200)
        self.set_font("DV", "", 8)
        self.set_text_color(50, 50, 50)
        y0 = self.get_y()
        for line in lines:
            self.cell(CONTENT_W, 4.8, f"  {line}", ln=True, fill=True)
        self.rect(MARGIN, y0, CONTENT_W, self.get_y() - y0)
        self.ln(3)


def build_pdf(metrics: Dict[str, Any]) -> Path:
    snap = metrics["pre_test_snapshot"]
    mader = metrics["mader_result"]
    cal = metrics["calibration"]
    corr = cal["correction"]
    paolo_raw = cal["paolo_pre_calibration"].get("mlss_power_watts")
    paolo_cal = cal["calibrated_snapshot"].get("mlss_power_watts")

    pdf = PaperPDF()
    pdf.cover()

    # Abstract
    pdf.add_page()
    pdf.h1("Abstract")
    pdf.body(
        "Questo paper illustra, attraverso un caso studio realistico, il differenziatore "
        "del backend Digital Twin: un contratto di fiducia a tre livelli tra motore Mader, "
        "test al lattato in presenza e calibrazione di squadra con audit completo."
    )
    pdf.body(
        "Il caso segue la Squadra Demo WT durante una settimana di test: Marco Rossi (nuovo "
        "grimpeur) viene validato con protocollo Mader; tre colleghi alimentano la memoria di "
        "cohort; Paolo C. (neo-pro) beneficia della correzione team prima del proprio lattato."
    )
    pdf.h2("Risultato chiave")
    pdf.quote(
        "Il sistema non sostituisce il lattato con una stima opaca: lo usa per validare il "
        "modello, registrare l'errore pre-test e correggere le stime future con limiti "
        "conservativi e tracciabilita."
    )

    # Problem
    pdf.h1("1. Il problema del coach World Tour")
    pdf.body(
        "Uno staff d'elite gestisce 25-30 atleti. Ogni stagione le stesse domande: posso "
        "fidarmi della soglia da potenza? Il numero e misurato o modellato? Perche il modello "
        "sbaglia sui miei grimpeurs? Le piattaforme generiche raramente offrono risposte "
        "auditabili."
    )
    pdf.table(
        ["Domanda", "Piattaforma generica", "Limite"],
        [
            ["Fiducia sulla soglia?", "FTP auto-aggiornato", "Nessuna validazione"],
            ["Misurato vs modellato?", "Ambiguo", "Coach non distingue"],
            ["Bias di cohort?", "Silenzio", "Nessuna memoria team"],
            ["Dopo il lattato?", "PDF statico", "Nessun verdetto operativo"],
        ],
        [52, 58, 64],
    )

    # Architecture
    pdf.h1("2. Architettura del contratto di fiducia")
    pdf.diagram_box([
        "LIVELLO 1 — FISICA (Mader): MMP -> VO2max, VLamax, MLSS | expressiveness gate",
        "         |",
        "LIVELLO 2 — VALIDAZIONE: D-max (lattato) vs MLSS da MMP | validated +/-8%",
        "         |",
        "LIVELLO 3 — TEAM LEARNING: errore = misurato - predetto | correzione bounded",
    ])
    pdf.body(
        "Il Team Learning non sostituisce Mader: impara solo la correzione residua "
        "(cap MLSS: +/-25 W o 5%)."
    )

    # Case study
    pdf.h1("3. Caso studio — Marco Rossi")
    pdf.h2("3.1 Profilo non invasivo (Fase A)")
    pdf.table(
        ["Parametro", "Valore", "Note"],
        [
            ["MLSS stimata", f"{snap.get('mlss_power_watts')} W", "Da MMP espressiva"],
            ["VO2max", f"{snap.get('estimated_vo2max')} ml/kg/min", "Modello Mader"],
            ["VLamax", f"{snap.get('estimated_vlamax_mmol_L_s')}", ""],
            ["confidence", f"{snap.get('confidence_score')}", ""],
            ["fully_expressive", str(snap.get('expressiveness', {}).get('fully_expressive', True)), "4 finestre OK"],
        ],
        [48, 40, 86],
    )

    pdf.h2("3.2 Test Mader — verdetto (Fase B)")
    pdf.table(
        ["Metrica", "Valore"],
        [
            ["MLSS lattato (D-max)", f"{mader.get('mlss_true_watts')} W"],
            ["MLSS predetta (pre-test)", f"{mader.get('mlss_model_watts')} W"],
            ["Errore", f"{mader.get('error_watts')} W ({mader.get('error_pct')}%)"],
            ["Tolleranza", f"+/-{mader.get('tolerance_pct', 8)}%"],
            ["VALIDATED", str(mader.get('validated')).upper()],
        ],
        [70, 104],
    )
    verdict = str(mader.get("verdict", ""))[:300]
    if verdict:
        pdf.quote(verdict + ("..." if len(str(mader.get("verdict", ""))) > 300 else ""))

    if mader.get("validated"):
        pdf.set_font("DV", "B", 11)
        pdf.set_text_color(20, 120, 60)
        pdf.cell(CONTENT_W, 8, "VERDETTO: MODEL VALIDATED", ln=True)
        pdf.ln(2)

    # Team learning
    pdf.add_page()
    pdf.h1("4. Memoria di squadra (Fase C)")
    pdf.body(
        "Tre grimpeurs hanno completato Mader nella stessa settimana. Per ciascuno: "
        "predizione PRIMA del test vs valore misurato."
    )
    pdf.table(
        ["Atleta", "Predetto", "Misurato", "Errore"],
        [
            ["Luca B.", "385 W", "370 W", "-15 W"],
            ["Tom H.", "372 W", "358 W", "-14 W"],
            ["Jonas V.", "398 W", "382 W", "-16 W"],
        ],
        [40, 38, 38, 58],
    )
    pdf.h2("Statistiche cohort")
    pdf.table(
        ["Statistica", "Valore"],
        [
            ["Bias medio", "-15.0 W"],
            ["MAE", "15.0 W"],
            ["Pattern", "Sovrastima sistematica MLSS su grimpeurs"],
        ],
        [70, 104],
    )
    pdf.quote(
        "Non e un difetto di Marco: e un bias di cohort. Il modello tende a sovrastimare "
        "la soglia su questo sottoinsieme della rosa."
    )

    # Paolo
    pdf.h1("5. Neo-pro calibrato — Paolo C. (Fase D)")
    pdf.body("Paolo (58 kg) ha MMP espressiva ma nessun test al lattato ancora.")
    pdf.table(
        ["Stadio", "MLSS (W)", "Fonte"],
        [
            ["Modello grezzo", f"{paolo_raw}", "/profile/snapshot"],
            ["Correzione team", f"{corr.get('correction'):+.1f}", "Team Learning"],
            ["MLSS calibrata", f"{paolo_cal}", "/team/calibration/apply"],
            ["Cap sicurezza", f"+/-{corr.get('cap')}", "Bounded"],
        ],
        [42, 38, 94],
    )
    components = corr.get("components") or []
    if components:
        pdf.h2("Audit trail")
        rows = []
        for c in components:
            rows.append([
                c.get("scope", ""),
                f"{c.get('raw_bias'):+.1f} W",
                str(c.get("n", "")),
            ])
        pdf.table(["Scope", "Bias", "n"], rows, [50, 60, 64])

    # Comparison
    pdf.h1("6. Confronto con piattaforme generiche")
    pdf.table(
        ["Capacita", "Generico", "Digital Twin"],
        [
            ["Stima soglia", "eFTP/FTP", "Mader su MMP"],
            ["Validazione lattato", "No", "Si — verdetto +/-8%"],
            ["Output inaffidabili", "Mostrati", "Mascherati (gate)"],
            ["Memoria team", "No", "Team Learning + audit"],
            ["Audit correzioni", "No", "ValidationEvent"],
        ],
        [48, 50, 76],
    )

    # Conclusion
    pdf.h1("7. Conclusioni")
    pdf.bullets([
        "Prima del lattato: profilo Mader con gate di espressivita.",
        "Con il lattato: verdetto validated con soglia e azione raccomandata.",
        "Dopo il lattato: errore pre-test archiviato; calibrazione per i prossimi.",
        "Sempre: audit trail su ogni correzione.",
    ])
    pdf.ln(2)
    pdf.quote(
        "Un motore fisiologico Mader validato dal lattato, con apprendimento residuale "
        "auditato sul cohort della squadra."
    )

    pdf.h2("Appendice — Endpoint")
    pdf.table(
        ["Endpoint", "Fase"],
        [
            ["POST /profile/snapshot", "A, D"],
            ["POST /test/in-person", "B"],
            ["POST /team/calibration/update", "C"],
            ["POST /team/calibration/apply", "D"],
        ],
        [110, 64],
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUTPUT))
    return OUTPUT


def main() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    metrics = _load_demo_metrics()
    path = build_pdf(metrics)
    print(f"Paper PDF generato: {path}")


if __name__ == "__main__":
    main()
