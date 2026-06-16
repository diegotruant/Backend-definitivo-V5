#!/usr/bin/env python3
"""
Validate interval_detector on Gigi's 9 real FIT files.

Ground truth (from conversation with Gigi):
  - cdea1e7e (12 apr, 79min):  HIIT (lap-structured, 51 laps)
  - 44fdf4f5 (19 apr, 38min):  TEST (sprint test)
  - e92dcce6 (15 mag, 47min):  TEST (sprint test)
  - caea716b (22 apr, 64min):  HIIT (lap-structured, 51 laps)
  - 064adf70 (24 apr, 54min):  HIIT (lap-structured, 51 laps)
  - ramp_test_01:              TEST/ramp_test
  - 2x8_test:                  TEST/ftp_2x8
  - flow_protocol_1:           TEST/mixed_test (sprint + cp12)
  - workout_20260521:          TEST/single_sprint (warmup + 1 sprint)

We measure:
  - Category correctness (TEST/HIIT/STEADY/FREE)
  - Subtype correctness (when meaningful)
  - Confidence and source (filename/laps/signal)
  - Qualified anchors extracted (for TEST)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import fitparse
from engines.performance.interval_detector import classify_session


FIT_DIR = Path("/mnt/user-data/uploads")
FTP_GIGI = 250  # rough estimate; refined later

# Ground truth as best we know from Gigi's labels
GROUND_TRUTH = {
    "cdea1e7e-af06-4514-96b6-d5460adec0a1.fit":         ("HIIT", "?"),
    "44fdf4f5-63fe-4aa1-b6d7-3a524fb93cd2.fit":         ("TEST", "?sprint_set?"),
    "e92dcce6-382b-4a79-bb39-f02bdccce8cd.fit":         ("TEST", "?sprint_set?"),
    "caea716b-11ba-4927-9f15-c69cec849b44.fit":         ("HIIT", "?"),
    "064adf70-a3ac-4787-99d7-890f8498629b.fit":         ("HIIT", "?"),
    "activity_1778678330524_ramp_test_01.fit":          ("TEST", "ramp_test"),
    "activity_1779381936319_2x8_test.fit":              ("TEST", "ftp_2x8"),
    "activity_1778862759641_flow_protocol_1.fit":       ("TEST", "mixed_test"),
    "activity_1779380871124_workout_20260521.fit":      ("TEST", "single_sprint"),
}


def load_fit(path: Path):
    ff = fitparse.FitFile(str(path))
    powers = []
    for rec in ff.get_messages("record"):
        for f in rec.fields:
            if f.name == "power":
                powers.append(f.value if f.value is not None else 0)
                break
    laps = []
    for lap in ff.get_messages("lap"):
        info = {}
        for f in lap.fields:
            if f.value is not None:
                if f.name == "total_elapsed_time":
                    info["duration_s"] = float(f.value)
                elif f.name == "avg_power":
                    info["avg_power_w"] = float(f.value)
                elif f.name == "max_power":
                    info["max_power_w"] = float(f.value)
                elif f.name == "avg_heart_rate":
                    info["avg_hr"] = float(f.value)
        if info:
            laps.append(info)
    return powers, laps


def main():
    print("=" * 78)
    print("  Interval detector validation — 9 real FIT files")
    print("=" * 78)
    
    results = []
    
    for fname, (expected_cat, expected_sub) in GROUND_TRUTH.items():
        path = FIT_DIR / fname
        if not path.exists():
            print(f"\n  ✗ {fname[:40]}... NOT FOUND")
            continue
        
        powers, laps = load_fit(path)
        
        # Use real filename so Strategy A works for the parlante ones
        result = classify_session(
            powers,
            filename=fname,
            laps=laps,
            ftp=FTP_GIGI,
        )
        
        category_match = result.category == expected_cat
        subtype_match = (
            expected_sub == "?" or 
            "?" in expected_sub or
            result.subtype == expected_sub
        )
        ok = category_match and subtype_match
        marker = "✓" if ok else ("~" if category_match else "✗")
        
        short_name = fname.replace("activity_", "").replace(".fit", "")
        if len(short_name) > 35:
            short_name = short_name[:35] + "..."
        
        print(f"\n  {marker} {short_name}")
        print(f"      ground truth:   {expected_cat} / {expected_sub}")
        print(f"      classified:     {result.category} / {result.subtype}")
        print(f"      confidence:     {result.confidence:.2f}  (source: {result.source})")
        print(f"      duration:       {result.duration_s/60:.1f} min")
        print(f"      avg/NP/IF:      {result.avg_power_w:.0f}W / "
              f"{result.normalized_power_w:.0f}W / {result.intensity_factor:.2f}")
        
        if result.qualified_anchors:
            anchors_str = ", ".join(
                f"{a.duration_s}s@{a.power_w:.0f}W" for a in result.qualified_anchors
            )
            print(f"      anchors:        {anchors_str}")
        
        if result.stimulus_vector:
            sv = result.stimulus_vector.to_dict()
            print(f"      stimulus:       "
                  f"base={sv['aerobic_base_min']:.0f}', "
                  f"tempo={sv['tempo_min']:.0f}', "
                  f"thr={sv['threshold_min']:.1f}', "
                  f"vo2={sv['vo2max_min']:.1f}', "
                  f"ana={sv['anaerobic_min']:.1f}'")
        
        for note in result.notes[:2]:
            print(f"      note: {note[:90]}")
        
        results.append((fname, expected_cat, expected_sub, result, ok, category_match))
    
    # Summary
    print()
    print("=" * 78)
    print("  SUMMARY")
    print("=" * 78)
    n = len(results)
    cat_correct = sum(1 for *_, cm in results if cm)
    full_correct = sum(1 for *_, ok, _ in results if ok)
    print(f"  Category correct:  {cat_correct}/{n}  ({100*cat_correct/n:.0f}%)")
    print(f"  Full match:        {full_correct}/{n}  ({100*full_correct/n:.0f}%)")
    print()
    
    # Breakdown by source
    by_source = {}
    for *_, result, _, _ in results:
        by_source.setdefault(result.source, []).append(result.category)
    print("  Used per strategy:")
    for src, cats in by_source.items():
        print(f"    {src}: {len(cats)} files ({', '.join(set(cats))})")


if __name__ == "__main__":
    main()
