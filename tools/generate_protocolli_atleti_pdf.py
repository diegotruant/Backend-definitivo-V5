#!/usr/bin/env python3
"""Generate athlete-facing in-person test protocol PDF (Italian)."""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "protocolli-test-atleti.pdf"
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
MARGIN = 15
CONTENT_W = 180


class ProtocolPDF(FPDF):
    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=18)
        self.set_left_margin(MARGIN)
        self.set_right_margin(MARGIN)
        self.add_font("DV", "", str(FONT_DIR / "DejaVuSans.ttf"))
        self.add_font("DV", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("DV", "", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, f"Digital Twin — Protocolli test in presenza  |  Pagina {self.page_no()}", align="C")

    def section_title(self, number: str, title: str, subtitle: str = "") -> None:
        self.add_page()
        self.set_fill_color(30, 60, 100)
        self.set_text_color(255, 255, 255)
        self.set_font("DV", "B", 14)
        self.cell(CONTENT_W, 10, f"{number}. {title}", new_x="LMARGIN", new_y="NEXT", fill=True)
        if subtitle:
            self.ln(2)
            self.set_text_color(80, 80, 80)
            self.set_font("DV", "", 10)
            self.multi_cell(CONTENT_W, 5, subtitle)
        self.ln(4)

    def h3(self, text: str) -> None:
        self.set_text_color(30, 60, 100)
        self.set_font("DV", "B", 11)
        self.cell(CONTENT_W, 7, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def body(self, text: str) -> None:
        self.set_text_color(40, 40, 40)
        self.set_font("DV", "", 10)
        self.multi_cell(CONTENT_W, 5.5, text)
        self.ln(2)

    def bullets(self, items: list[str]) -> None:
        self.set_text_color(40, 40, 40)
        self.set_font("DV", "", 10)
        for item in items:
            self.multi_cell(CONTENT_W, 5.5, f"  •  {item}")
        self.ln(2)

    def simple_table(self, headers: list[str], rows: list[list[str]], widths: list[int]) -> None:
        self.set_font("DV", "B", 9)
        self.set_fill_color(230, 236, 245)
        self.set_text_color(30, 60, 100)
        for i, h in enumerate(headers):
            self.cell(widths[i], 7, h, border=1, fill=True)
        self.ln()
        self.set_font("DV", "", 9)
        self.set_text_color(40, 40, 40)
        for row in rows:
            x0 = self.get_x()
            y0 = self.get_y()
            max_h = 7
            cell_lines: list[list[str]] = []
            for i, cell in enumerate(row):
                cell_lines.append(
                    self.multi_cell(widths[i], 5, cell, dry_run=True, output="LINES")
                )
                max_h = max(max_h, len(cell_lines[-1]) * 5)
            for i, lines in enumerate(cell_lines):
                x = x0 + sum(widths[:i])
                self.rect(x, y0, widths[i], max_h)
                for j, line in enumerate(lines):
                    self.set_xy(x + 1, y0 + 1 + j * 5)
                    self.cell(widths[i] - 2, 5, line)
            self.set_xy(x0, y0 + max_h)
        self.ln(4)

    def info_box(self, title: str, items: list[str]) -> None:
        self.set_fill_color(245, 248, 252)
        self.set_draw_color(180, 195, 215)
        y0 = self.get_y()
        self.set_font("DV", "B", 10)
        self.set_text_color(30, 60, 100)
        self.cell(CONTENT_W, 7, title, new_x="LMARGIN", new_y="NEXT", fill=True)
        self.set_font("DV", "", 9)
        self.set_text_color(50, 50, 50)
        for item in items:
            self.multi_cell(CONTENT_W, 5.5, f"  - {item}", fill=True)
        y1 = self.get_y()
        self.rect(MARGIN, y0, CONTENT_W, y1 - y0 + 1, style="D")
        self.ln(4)


def build_pdf() -> Path:
    pdf = ProtocolPDF()
    pdf.add_page()
    pdf.set_font("DV", "B", 22)
    pdf.set_text_color(30, 60, 100)
    pdf.cell(CONTENT_W, 14, "Protocolli dei test in presenza", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(4)
    pdf.set_font("DV", "", 11)
    pdf.set_text_color(60, 60, 60)
    pdf.multi_cell(
        CONTENT_W,
        6,
        "Guida per atleti e coach.\n"
        "Segui queste istruzioni il giorno del test per ottenere misure "
        "affidabili e risultati utilizzabili dal motore fisiologico.",
        align="C",
    )
    pdf.ln(6)
    pdf.info_box(
        "Prima di iniziare",
        [
            "Sonno adeguato la notte precedente (almeno 7 ore).",
            "Nessun allenamento intenso nelle 48 ore prima del test.",
            "Pasto leggero completato almeno 3 ore prima; idratazione normale.",
            "Abbigliamento comodo, asciugamano, bottiglia d'acqua.",
            "Comunica al coach eventuali farmaci, malattie recenti o affaticamento.",
        ],
    )

    # 1 MADER
    pdf.section_title(
        "1",
        "Test al lattato (Mader)",
        "Test principale di onboarding. Misura la soglia metabolica con campioni di sangue "
        "e valida il profilo fisiologico dell'atleta.",
    )
    pdf.h3("A cosa serve")
    pdf.body(
        "Stabilisce la potenza alla soglia (MLSS) tramite analisi del lattato ematico. "
        "È il riferimento più affidabile per calibrare zone di allenamento e monitoraggio."
    )
    pdf.h3("Durata totale stimata: 60-75 minuti")
    pdf.h3("Cosa ti serve")
    pdf.bullets(
        [
            "Rulli o cicloergometro in modalità ERG (potenza costante).",
            "Lancette e analizzatore di lattato (a cura dello staff).",
            "Potenziometro calibrato o trainer con misura potenza affidabile.",
        ]
    )
    pdf.h3("Protocollo passo-passo")
    pdf.simple_table(
        ["Fase", "Durata", "Cosa fare"],
        [
            ["Riscaldamento", "15-20 min", "Pedala a intensità leggera (60-70% FCmax), cadenza naturale."],
            ["Step 1", "5 min", "Mantieni la potenza indicata dal coach. A fine step: prelievo lattato."],
            ["Step 2-6", "5 min cad.", "Ogni step aumenta di 20-30 W. Prelievo a fine di ogni step."],
            ["Fine test", "-", "Ultimo step con lattato chiaramente elevato (> 6 mmol/L)."],
        ],
        [32, 28, 120],
    )
    pdf.h3("Regole importanti")
    pdf.bullets(
        [
            "Non saltare il riscaldamento.",
            "Mantieni la cadenza stabile; evita picchi o cali di potenza nello step.",
            "Il prelievo va fatto 20-30 secondi dopo la fine dello step.",
            "Segnala subito al coach se ti senti stordito, nauseato o con dolore al petto.",
            "Sono necessari almeno 5 step completi con lattato misurato.",
        ]
    )
    pdf.info_box(
        "Dopo il test",
        [
            "Recupero attivo leggero 10 min.",
            "Idratazione e spuntino se necessario.",
            "I risultati saranno disponibili tramite il coach dopo l'elaborazione.",
        ],
    )

    # 2 INCREMENTALE
    pdf.section_title(
        "2",
        "Test incrementale (senza lattato)",
        "Progressione di potenza fino a esaurimento. Fornisce potenza massima e risposta cardiaca.",
    )
    pdf.h3("A cosa serve")
    pdf.body(
        "Misura la potenza massima raggiunta e la frequenza cardiaca massima osservata. "
        "Utile per costruire la curva delle potenze massime quando non è disponibile il lattato."
    )
    pdf.h3("Durata totale stimata: 25-40 minuti")
    pdf.simple_table(
        ["Fase", "Durata", "Cosa fare"],
        [
            ["Riscaldamento", "15 min", "Intensità leggera-media, 2-3 accelerazioni brevi."],
            ["Step 1", "3 min", "Potenza iniziale moderata (indicata dal coach)."],
            ["Step successivi", "1 min", "Aumento di 10 W a ogni step fino a esaurimento."],
            ["Fine", "-", "Interrompi quando non riesci a completare lo step."],
        ],
        [32, 28, 120],
    )
    pdf.h3("Regole importanti")
    pdf.bullets(
        [
            "Dai il massimo negli ultimi step: serve una vera fatica massimale.",
            "Non tenere la mano sul cardiofrequenzimetro durante lo sforzo.",
            "Comunica al coach quando ritieni di non poter proseguire.",
        ]
    )

    # 3 CURVA P/C
    pdf.section_title(
        "3",
        "Curva potenza / cadenza",
        "Sprint massimali a diverse cadenze per trovare la cadenza ottimale di picco.",
    )
    pdf.h3("A cosa serve")
    pdf.body("Identifica la cadenza (giri/minuto) alla quale produci la potenza di picco più alta.")
    pdf.h3("Durata totale stimata: 30-40 minuti")
    pdf.simple_table(
        ["Sprint", "Cadenza", "Durata", "Recupero"],
        [
            ["1", "80 giri/min", "30-40 s max", "3-5 min leggeri"],
            ["2", "100 giri/min", "30-40 s max", "3-5 min leggeri"],
            ["3", "120 giri/min", "30-40 s max", "3-5 min leggeri"],
            ["4", "140 giri/min", "30-40 s max", "Fine o sprint extra"],
        ],
        [18, 35, 42, 85],
    )
    pdf.h3("Regole importanti")
    pdf.bullets(
        [
            "Ogni sprint deve essere un vero massimale da partenza o quasi fermo.",
            "Concentrati sulla cadenza indicata, ma pedala al massimo della tua potenza.",
            "Rispetta i tempi di recupero: servono per qualità dello sprint successivo.",
        ]
    )

    # 4 CP
    pdf.section_title(
        "4",
        "Critical Power (CP)",
        "Tre o più sforzi massimali tra 2 e 15 minuti per stimare potenza critica e W'.",
    )
    pdf.h3("A cosa serve")
    pdf.body(
        "Stima la potenza critica (sostenibile a lungo) e la riserva anaerobica (W'). "
        "Fondamentale per pianificare intervalli e gare."
    )
    pdf.h3("Durata totale stimata: 60-90 minuti")
    pdf.simple_table(
        ["Sforzo", "Durata", "Intensità", "Recupero"],
        [
            ["1", "3 min", "Massimale sostenibile", "30-45 min"],
            ["2", "5 min", "Massimale sostenibile", "30-45 min"],
            ["3", "12 min", "Massimale sostenibile", "Fine test"],
            ["(opz.) 4", "8 min", "Massimale sostenibile", "Migliora accuratezza"],
        ],
        [22, 24, 62, 72],
    )
    pdf.h3("Regole importanti")
    pdf.bullets(
        [
            "Ogni sforzo deve essere il miglior ritmo medio che riesci a tenere per tutta la durata.",
            "Parti forte ma controllato: evita di esplodere nei primi 30 secondi.",
            "I recuperi tra sforzi sono obbligatori e devono essere completi.",
            "Servono almeno 3 sforzi validi nella finestra 2-15 minuti.",
        ]
    )

    # 5 WINGATE
    pdf.section_title(
        "5",
        "Test Wingate",
        "Sprint massimale di 30 secondi per misurare potenza anaerobica e indice di fatica.",
    )
    pdf.h3("A cosa serve")
    pdf.body(
        "Misura picco di potenza, potenza media, minimo e indice di fatica "
        "in uno sprint breve e intenso."
    )
    pdf.h3("Durata totale stimata: 20-25 minuti")
    pdf.simple_table(
        ["Fase", "Durata", "Cosa fare"],
        [
            ["Riscaldamento", "10-15 min", "Leggero + 2-3 accelerazioni progressive."],
            ["Posizionamento", "-", "Sella alta, rapporto corto, posizione stabile."],
            ["Sprint", "30 s", "Partenza esplosiva e massimale per tutta la durata."],
            ["Recupero", "10-15 min", "Molto leggero, idratazione."],
        ],
        [32, 28, 120],
    )
    pdf.h3("Regole importanti")
    pdf.bullets(
        [
            "Lo sprint dura esattamente 30 secondi: non mollare prima.",
            "Se previsto, il test può includere un prelievo lattato prima e dopo lo sprint.",
            "Comunica immediatamente eventuali capogiri o nausea.",
        ]
    )

    # 6 PREPARAZIONE
    pdf.section_title("6", "Preparazione generale (tutti i test)")
    pdf.h3("24-48 ore prima")
    pdf.bullets(
        [
            "Evita gare, interval sessions o lavori sopra soglia.",
            "Mantieni idratazione normale; non provare diete nuove.",
            "Dormi almeno 7 ore la notte precedente.",
        ]
    )
    pdf.h3("Il giorno del test")
    pdf.bullets(
        [
            "Pasto leggero 3-4 ore prima (es. pasta/riso, pane, frutta).",
            "Evita alcol, caffeina in eccesso e integratori non abituali.",
            "Arriva 15 minuti prima per setup bike e calibrazione.",
            "Porta: asciugamano, acqua, abbigliamento, ciclo scarpe se usi rulli propri.",
        ]
    )
    pdf.h3("Controindicazioni - informa il coach se")
    pdf.bullets(
        [
            "Hai febbre, infezione o mal di gola nelle ultime 48 ore.",
            "Hai dolore muscolare importante o infortunio recente.",
            "Assumi farmaci che influenzano frequenza cardiaca o sensibilità allo sforzo.",
            "Ti senti affaticato oltre il normale.",
        ]
    )

    # 7 DOPO
    pdf.section_title("7", "Cosa succede dopo il test")
    pdf.body(
        "I dati raccolti (potenza, cadenza, frequenza cardiaca, lattato se previsto) "
        "vengono elaborati dal sistema fisiologico. Il coach riceve:"
    )
    pdf.bullets(
        [
            "Soglie e zone di allenamento personalizzate.",
            "Profilo metabolico (VO2max, VLamax, MLSS dove applicabile).",
            "Indicazioni su qualità del test e affidabilità dei risultati.",
            "Raccomandazioni per ripetere il test se i dati non sono sufficienti.",
        ]
    )
    pdf.info_box(
        "Per risultati affidabili",
        [
            "Segui il protocollo senza modifiche non concordate con il coach.",
            "Usa lo stesso dispositivo di misura potenza per test e allenamenti successivi.",
            "Non confrontare risultati di test fatti in condizioni molto diverse.",
        ],
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUTPUT))
    return OUTPUT


if __name__ == "__main__":
    path = build_pdf()
    print(f"PDF generato: {path}")
