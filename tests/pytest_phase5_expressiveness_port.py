"""Port of tests/integration/test_v350_expressiveness.py for coverage."""

from __future__ import annotations

from engines.core.athlete_context import AthleteContext
from engines.metabolic.mader_constants import ExpressivenessReport, MaderConstants
from engines.metabolic.metabolic_profiler import MetabolicProfiler
from engines.performance.interval_detector import QualifiedAnchor, protocol_completeness


class TestExpressivenessPort:
    def test_expressiveness_report_api(self) -> None:
        r = ExpressivenessReport.from_mmp({5: 800, 60: 450, 300: 320, 1200: 280})
        assert r.fully_expressive
        assert r.vlamax_reliable
        assert r.mlss_reliable

        flat = ExpressivenessReport.from_mmp({300: 340, 1200: 290, 3600: 270})
        assert not flat.fully_expressive
        assert not flat.vlamax_reliable
        assert flat.mlss_reliable

        short = ExpressivenessReport.from_mmp({5: 800, 30: 620, 60: 470, 180: 380})
        assert not short.mlss_reliable

        empty = ExpressivenessReport.from_mmp({})
        assert not empty.vlamax_reliable and not empty.mlss_reliable

        d = ExpressivenessReport.from_mmp({5: 800, 60: 450, 1200: 280}).to_dict()
        assert {"coverage", "reliability", "fully_expressive", "tier"}.issubset(d.keys())
        assert d["tier"] == "REFERENCE"

    def test_gate_on_flat_and_full_mmp(self) -> None:
        ctx = AthleteContext(gender="MALE", training_years=5, discipline="ROAD")
        profiler = MetabolicProfiler(weight=72, context=ctx)

        flat_snap = profiler.generate_metabolic_snapshot({300: 340, 600: 300, 1200: 290, 3600: 270})
        assert flat_snap.get("status") == "success"
        assert flat_snap.get("estimated_vlamax_mmol_L_s") is None
        assert flat_snap.get("metabolic_phenotype") is None
        assert flat_snap.get("mlss_power_watts") is not None
        assert flat_snap["confidence_score"] <= 0.40
        assert "unmasked_estimates" in flat_snap

        short_snap = profiler.generate_metabolic_snapshot({5: 950, 30: 620, 60: 470, 180: 380})
        assert short_snap.get("mlss_power_watts") is None
        assert short_snap.get("estimated_vo2max") is None

        good_snap = profiler.generate_metabolic_snapshot(
            {5: 950, 30: 620, 60: 470, 300: 340, 1200: 290, 3600: 270}
        )
        assert good_snap["expressiveness"]["fully_expressive"]
        assert good_snap["estimated_vo2max"] is not None
        assert good_snap["estimated_vlamax_mmol_L_s"] is not None

    def test_mader_constants_override_and_edges(self) -> None:
        ctx = AthleteContext(gender="MALE", training_years=5, discipline="ROAD")
        custom = MaderConstants(ks1=0.0635, ks2=1.30, _source="nolte_2025_review")
        profiler = MetabolicProfiler(weight=72, context=ctx, mader_constants=custom)
        assert profiler.const.ks1 == 0.0635
        assert profiler.const._source == "nolte_2025_review"

        mmp = {5: 950, 30: 620, 60: 470, 300: 340, 1200: 290, 3600: 270}
        snap = profiler.generate_metabolic_snapshot(mmp)
        assert snap["context_used"]["mader_constants"]["ks1"] == 0.0635
        assert custom.to_dict()["source"] == "nolte_2025_review"

        bad = profiler.generate_metabolic_snapshot({60: 400})
        assert bad.get("status") == "error"

        cleaned = profiler.generate_metabolic_snapshot(
            {300: 340, 720: 300, 1200: 290, 1800: 285, 3600: 270},
            clean_mmp_first=True,
        )
        assert "mmp_quality" in cleaned
        assert cleaned.get("estimated_vlamax_mmol_L_s") is None

    def test_protocol_completeness(self) -> None:
        anchors = [
            QualifiedAnchor(duration_s=15, power_w=900, anchor_reliability=1.0, source_subtype="sprint"),
            QualifiedAnchor(duration_s=60, power_w=520, anchor_reliability=1.0, source_subtype="cp1"),
            QualifiedAnchor(duration_s=300, power_w=360, anchor_reliability=0.9, source_subtype="cp5"),
            QualifiedAnchor(duration_s=1200, power_w=285, anchor_reliability=1.0, source_subtype="ftp_20min"),
        ]
        comp = protocol_completeness(anchors)
        assert comp.n_qualified_anchors == 4
        assert "threshold" in comp.covered_windows
