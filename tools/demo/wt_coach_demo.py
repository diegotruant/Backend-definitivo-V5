#!/usr/bin/env python3
"""
Demo 5 minuti per coach World Tour — validazione Mader + Team Learning.

Uso:
  python3 tools/demo/wt_coach_demo.py
  python3 tools/demo/wt_coach_demo.py --no-pause    # senza pause (CI / replay veloce)
  python3 tools/demo/wt_coach_demo.py --json          # output machine-readable

Narrativa:
  1. Nuovo atleta (Marco) — profilo da MMP, stima MLSS del modello
  2. Test Mader in presenza — verdetto validated / non validated
  3. Tre colleghi già testati — il team accumula errori osservati
  4. Stima successiva di Marco — correzione team con audit trail
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engines.core.athlete_context import AthleteContext
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.metabolic.team_learning_engine import (
    CorrectionConfig,
    TeamCalibrationModel,
    ValidationEvent,
    validation_events_from_prediction_and_lab,
)
from engines.performance.test_protocols import run_test as run_in_person_test

# ---------------------------------------------------------------------------
# Demo data — atleta protagonista + 3 colleghi già validati in settimana test
# ---------------------------------------------------------------------------

TEAM_ID = "wt_demo_squadra"
PHENOTYPE = "climber"

MARCO = {
    "athlete_id": "marco_rossi_07",
    "name": "Marco Rossi",
    "weight_kg": 62.0,
    "sex": "M",
    "training_years": 8,
    "discipline": "CLIMB",
}

MARCO_MMP = {
    "5": 850,
    "60": 400,
    "300": 285,
    "720": 275,
    "1200": 278,
    "3600": 262,
}

PAOLO = {
    "athlete_id": "paolo_nuovo_12",
    "name": "Paolo C.",
    "weight_kg": 58.0,
    "mmp": {
        "5": 900,
        "60": 420,
        "300": 310,
        "720": 295,
        "1200": 288,
        "3600": 275,
    },
}

MADER_ENVELOPE = {
    "test_type": "mader",
    "timestamp": "2026-06-10T09:30:00",
    "athlete": {
        "id": MARCO["athlete_id"],
        "type": "registered",
        "name": "Marco",
        "surname": "Rossi",
        "weight_kg": MARCO["weight_kg"],
        "sex": MARCO["sex"],
        "training_years": MARCO["training_years"],
        "discipline": MARCO["discipline"],
    },
    "device": {
        "trainer": "Wahoo KICKR",
        "power_source": "trainer",
        "control_mode": "erg",
    },
    "test_data": {
        "steps": [
            {"step": 1, "power_w": 180, "lactate_mmol": 1.1, "hr_mean": 118, "duration_s": 300},
            {"step": 2, "power_w": 210, "lactate_mmol": 1.5, "hr_mean": 132, "duration_s": 300},
            {"step": 3, "power_w": 240, "lactate_mmol": 2.2, "hr_mean": 145, "duration_s": 300},
            {"step": 4, "power_w": 265, "lactate_mmol": 3.8, "hr_mean": 158, "duration_s": 300},
            {"step": 5, "power_w": 285, "lactate_mmol": 5.9, "hr_mean": 168, "duration_s": 300},
            {"step": 6, "power_w": 305, "lactate_mmol": 9.1, "hr_mean": 176, "duration_s": 300},
        ],
        "mmp": MARCO_MMP,
    },
}

# Colleghi: il modello sovrastima sistematicamente MLSS di ~12-15 W (pattern WT reale)
TEAM_PRIOR_EVENTS = [
    {"athlete_id": "collega_01", "name": "Luca B.", "predicted": 385, "measured": 370},
    {"athlete_id": "collega_02", "name": "Tom H.", "predicted": 372, "measured": 358},
    {"athlete_id": "collega_03", "name": "Jonas V.", "predicted": 398, "measured": 382},
]


# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"


def _supports_color() -> bool:
    return sys.stdout.isatty()


def paint(text: str, *codes: str) -> str:
    if not _supports_color() or not codes:
        return text
    return "".join(codes) + text + C.RESET


def banner(title: str, subtitle: str = "") -> None:
    print()
    print(paint("=" * 72, C.BOLD, C.CYAN))
    print(paint(f"  {title}", C.BOLD, C.CYAN))
    if subtitle:
        print(paint(f"  {subtitle}", C.DIM))
    print(paint("=" * 72, C.BOLD, C.CYAN))
    print()


def act(n: int, title: str, minutes: str) -> None:
    print()
    print(paint(f"─── ATTO {n} ({minutes}) — {title} ", C.BOLD, C.BLUE) + paint("─" * 20, C.DIM))


def say(text: str) -> None:
    print(paint("  » ", C.MAGENTA) + text)


def kv(key: str, value: Any, *, highlight: bool = False) -> None:
    color = C.GREEN if highlight else ""
    print(f"    {paint(key + ':', C.DIM)} {paint(str(value), color) if color else value}")


def coach_line(text: str) -> None:
    print()
    print(paint("  COACH:", C.BOLD, C.YELLOW) + f" {text}")
    print()


def pause(seconds: float, enabled: bool) -> None:
    if enabled and seconds > 0:
        time.sleep(seconds)


# ---------------------------------------------------------------------------
# Demo acts
# ---------------------------------------------------------------------------


def act1_mmp_snapshot() -> Dict[str, Any]:
    act(1, "Profilo non invasivo da MMP", "~1 min")
    say(f"Nuovo ingaggio: {MARCO['name']} ({PHENOTYPE}, {MARCO['weight_kg']} kg)")
    say("Curva MMP espressiva — sprint, glicolitico, VO2max, soglia presenti.")

    ctx = AthleteContext(
        gender="MALE",
        training_years=float(MARCO["training_years"]),
        discipline=MARCO["discipline"],
    )
    profiler = MetabolicProfiler(weight=MARCO["weight_kg"], context=ctx)
    snapshot = profiler.generate_metabolic_snapshot(MARCO_MMP)

    kv("status", snapshot.get("status"))
    kv("MLSS stimata (modello)", f"{snapshot.get('mlss_power_watts')} W", highlight=True)
    kv("VO2max stimato", f"{snapshot.get('estimated_vo2max')} ml/kg/min")
    kv("VLamax stimato", snapshot.get("estimated_vlamax_mmol_L_s"))
    kv("confidence_score", snapshot.get("confidence_score"))
    exp = snapshot.get("expressiveness") or {}
    kv("fully_expressive", exp.get("fully_expressive"))
    if exp.get("missing_windows"):
        kv("missing_windows", exp.get("missing_windows"))

    coach_line(
        "Prima di fidarmi del monitoraggio solo da potenza, voglio validare "
        "il modello con un test al lattato in sala."
    )
    return snapshot


def act2_mader_test(pre_test_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    act(2, "Test Mader in presenza — verdetto", "~1.5 min")
    say("POST /test/in-person — 6 step al lattato, D-max vs modello Mader.")

    ctx = AthleteContext(
        gender="MALE",
        training_years=float(MARCO["training_years"]),
        discipline=MARCO["discipline"],
    )
    profiler = MetabolicProfiler(weight=MARCO["weight_kg"], context=ctx)
    result = run_in_person_test(MADER_ENVELOPE, profiler=profiler)

    mlss_model = result.get("mlss_model_watts")
    mlss_true = result.get("mlss_true_watts")
    error_pct = result.get("error_pct")
    validated = result.get("validated")
    verdict = result.get("verdict", "")

    kv("status", result.get("status"))
    kv("MLSS da lattato (D-max)", f"{mlss_true} W", highlight=True)
    kv("MLSS predetta da MMP", f"{mlss_model} W", highlight=True)
    kv("errore", f"{result.get('error_watts')} W ({error_pct}%)")
    kv("tolleranza", f"±{result.get('tolerance_pct', 8)}%")
    kv("validated", validated, highlight=True)
    conf = result.get("confidence")
    if conf is None:
        conf = (result.get("api_contract") or {}).get("confidence")
    kv("confidence verdetto", conf if conf is not None else "—")
    kv("severità", result.get("severity", "—"))

    print()
    if validated:
        print(paint("  ✓ MODEL VALIDATED", C.BOLD, C.GREEN))
    else:
        print(paint("  ✗ MODEL NOT VALIDATED", C.BOLD, C.RED))

    # Tronca verdetto per terminale
    short_verdict = verdict[:220] + ("..." if len(verdict) > 220 else "")
    print(paint(f"\n  \"{short_verdict}\"\n", C.DIM))

    if validated:
        coach_line(
            "Perfetto: per Marco posso passare al monitoraggio non invasivo. "
            "Ma il modello aveva già una predizione PRIMA del test — quella va "
            "archiviata per imparare sugli errori di squadra."
        )
    else:
        coach_line(
            "Il modello non è ancora affidabile per questo atleta. "
            "Verifico MMP e calibrazione del misuratore prima di procedere."
        )

    result["_pre_test_snapshot"] = pre_test_snapshot
    return result


def act3_team_learning() -> TeamCalibrationModel:
    act(3, "Tre colleghi validati — memoria di squadra", "~1 min")
    say("Durante la settimana di test, altri grimpeurs hanno già fatto Mader.")
    say("Ogni evento registra: predizione PRIMA del test vs valore misurato.")

    events: List[ValidationEvent] = []
    print()
    for row in TEAM_PRIOR_EVENTS:
        err = row["measured"] - row["predicted"]
        print(
            f"    {row['name']:10}  predetto {row['predicted']:3} W  →  "
            f"misurato {row['measured']:3} W  ({err:+d} W)"
        )
        events.append(
            ValidationEvent(
                athlete_id=row["athlete_id"],
                team_id=TEAM_ID,
                parameter="mlss",
                predicted_value=float(row["predicted"]),
                measured_value=float(row["measured"]),
                test_date=date(2026, 6, 8),
                model_version="v5.2.1",
                protocol="mader_lactate",
                phenotype=PHENOTYPE,
                data_depth_score=0.9,
                measurement_confidence=0.95,
            )
        )

    # Demo: soglia team a 3 eventi (in produzione default = 5)
    config = CorrectionConfig(min_team_events=3, min_phenotype_events=3)
    model = TeamCalibrationModel.fit(events, team_id=TEAM_ID, config=config)

    team_block = model.stats("mlss", phenotype=PHENOTYPE).get("team") or model.stats("mlss").get("team")
    print()
    if team_block:
        kv("eventi team", team_block["n"])
        kv("bias medio osservato", f"{team_block['weighted_bias']:+.1f} W", highlight=True)
        kv("MAE", f"{team_block['mae']:.1f} W")

    coach_line(
        "Il modello sovrastima sistematicamente la MLSS sui nostri grimpeurs. "
        "Non è un bug del singolo atleta — è un bias di cohort che possiamo correggere."
    )
    return model


def act4_apply_calibration(
    model: TeamCalibrationModel,
    mader_result: Dict[str, Any],
    pre_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    act(4, "Neo-pro successivo — stima con calibrazione team", "~1 min")
    say(f"Arriva {PAOLO['name']} (58 kg) — ancora NESSUN test al lattato.")
    say("POST /team/calibration/apply — correzione bounded + audit.")

    ctx = AthleteContext(gender="MALE", training_years=6, discipline="CLIMB")
    paolo_snapshot = MetabolicProfiler(weight=PAOLO["weight_kg"], context=ctx).generate_metabolic_snapshot(
        PAOLO["mmp"]
    )
    raw_mlss = paolo_snapshot.get("mlss_power_watts")

    correction = model.correction_for(
        "mlss",
        float(raw_mlss),
        athlete_id=PAOLO["athlete_id"],
        phenotype=PHENOTYPE,
        data_depth_score=0.9,
    )

    calibrated = model.calibrate_snapshot(
        dict(paolo_snapshot),
        athlete_id=PAOLO["athlete_id"],
        phenotype=PHENOTYPE,
        data_depth_score=0.9,
    )

    kv("MLSS grezza (solo modello)", f"{raw_mlss} W")
    kv("correzione team", f"{correction.get('correction'):+.1f} W", highlight=True)
    kv("MLSS calibrata", f"{calibrated.get('mlss_power_watts')} W", highlight=True)
    kv("cap massimo", f"±{correction.get('cap')} W")
    kv("correzione applicata", correction.get("applied"))

    components = correction.get("components") or []
    if components:
        print()
        say("Audit — da dove viene la correzione:")
        for comp in components:
            bias = comp.get("raw_bias")
            print(
                f"      [{comp.get('scope')}] bias {bias:+.1f} W "
                f"(n={comp.get('n')}, peso={comp.get('blend_weight')})"
            )

    # Registra il test di Marco nel modello (per la stagione successiva)
    marco_events = validation_events_from_prediction_and_lab(
        athlete_id=MARCO["athlete_id"],
        team_id=TEAM_ID,
        predicted_snapshot={
            "mlss_power_watts": mader_result.get("mlss_model_watts")
            or pre_snapshot.get("mlss_power_watts"),
        },
        measured={"measured_mlss": mader_result.get("mlss_true_watts")},
        test_date="2026-06-10",
        protocol="mader_lactate",
        phenotype=PHENOTYPE,
        model_version="v5.2.1",
    )
    model.add_events(marco_events)
    kv("eventi totali nel modello", len(model.events))

    coach_line(
        f"Per {PAOLO['name']} non abbiamo ancora il lattato, ma la squadra ha già "
        "imparato che il modello sovrastima i grimpeurs. La stima è più conservativa "
        "— e tracciata. Dopo il test Mader di Paolo, il ciclo ricomincia."
    )

    return {
        "paolo_pre_calibration": paolo_snapshot,
        "correction": correction,
        "calibrated_snapshot": calibrated,
        "marco_validation_recorded": True,
        "updated_model_events": len(model.events),
    }


def epilogue() -> None:
    banner("FINE DEMO", "Messaggio chiave per il coach WT")
    print(
        paint(
            "  « Non è un'AI che stima l'FTP. È un motore Mader che:\n"
            "     1. si valida col lattato,\n"
            "     2. ammette quando non è affidabile,\n"
            "     3. impara gli errori del TUO team — con audit. »\n",
            C.BOLD,
        )
    )
    print(paint("  Endpoint mostrati:", C.DIM))
    print("    POST /profile/snapshot")
    print("    POST /test/in-person")
    print("    POST /team/calibration/update")
    print("    POST /team/calibration/apply")
    print()


def run_demo(pause_enabled: bool = True, as_json: bool = False) -> Dict[str, Any]:
    output: Dict[str, Any] = {"team_id": TEAM_ID, "athlete": MARCO}

    if not as_json:
        banner(
            "DEMO COACH WORLD TOUR",
            "Validazione Mader + Team Learning  |  ~5 minuti",
        )
        say("Esegui con --no-pause per saltare le pause tra gli atti.")
        pause(1.5, pause_enabled)

    snapshot = act1_mmp_snapshot()
    output["pre_test_snapshot"] = snapshot
    pause(2.0, pause_enabled and not as_json)

    mader = act2_mader_test(snapshot)
    output["mader_result"] = {k: v for k, v in mader.items() if not k.startswith("_")}
    pause(2.0, pause_enabled and not as_json)

    model = act3_team_learning()
    output["team_prior_n"] = len(TEAM_PRIOR_EVENTS)
    pause(2.0, pause_enabled and not as_json)

    calibration = act4_apply_calibration(model, mader, snapshot)
    output["calibration"] = calibration
    pause(1.0, pause_enabled and not as_json)

    if not as_json:
        epilogue()
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Demo 5 min coach World Tour")
    parser.add_argument("--no-pause", action="store_true", help="Esegui senza pause")
    parser.add_argument("--json", action="store_true", help="Output JSON (per integrazioni)")
    args = parser.parse_args()

    try:
        result = run_demo(pause_enabled=not args.no_pause, as_json=args.json)
    except Exception as exc:
        print(paint(f"ERRORE: {exc}", C.RED), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
