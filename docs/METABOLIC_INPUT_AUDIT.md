# Metabolic profiler input-audit contract

Every metabolic snapshot now exposes a JSON-safe `input_audit` object. Its purpose is
to make input normalization visible without changing the physiological equations or
the optimizer.

## Top-level structure

```json
{
  "schema_version": "1.0",
  "has_adjustments": true,
  "summary": {
    "clipped_fields": ["weight_kg", "expected_eta"],
    "discarded_mmp_anchors": 2,
    "duplicate_mmp_durations": 1,
    "quality_cleaner_removed_mmp_anchors": 0
  },
  "athlete": {},
  "model_inputs": {},
  "mmp": {}
}
```

`has_adjustments` becomes `true` when at least one value is clipped, an invalid MMP
anchor is discarded, a duplicate normalized duration is resolved, or the optional MMP
quality cleaner removes an anchor. Inferred values such as context-derived eta or
model-derived lactate capacity are reported but are not mislabeled as clipping.

## Athlete inputs

The audit reports both the supplied and effective values for:

- `weight_kg`, supported by this model from 40 kg upward;
- `body_fat_pct`, constrained to the model range 3–55%.

A missing or invalid body-fat input is marked `defaulted` and shows the sex-specific
value supplied by `AthleteContext`. When body fat is outside the supported range, the
entry is marked `clipped`. `context_used.body_fat_pct` now reports the same effective
value that was actually used to calculate active muscle mass.

## Model inputs

The following optional overrides are auditable:

- `expected_eta`, clipped to 0.18–0.28;
- `measured_lacap_mmol_L`, clipped to 8–30 mmol/L.

When eta is absent, the audit identifies `athlete_context` as its source. When measured
lactate capacity is absent, the final inferred value is recorded with status
`inferred_during_fit`.

## MMP normalization

The MMP section contains:

- number of entries supplied;
- number of valid observations before duplicate resolution;
- number of accepted unique durations;
- number of anchors actually passed downstream;
- invalid anchors and the reason each was discarded;
- duplicate normalized durations and the previous/replacement power;
- explicit `last_value_wins` duplicate policy;
- number of duration keys normalized from forms such as `"60s"` or `"1m"`;
- optional quality-cleaner removals when `clean_mmp_first=True`.

Invalid anchor reasons are stable strings:

- `missing_power`;
- `invalid_power`;
- `non_positive_or_non_finite_power`;
- `invalid_duration`;
- `non_positive_duration`.

Detailed lists are capped at 100 entries. `details_truncated` indicates when aggregate
counts exceed the included details.

## Segmented fitting

A segmented snapshot preserves the audit of the original full MMP, including invalid
and duplicate keys, while merging the resolved eta/lactate-capacity information from
the stage that actually performed the full-curve fit. This prevents provenance from
being lost when the aerobic and full-curve subsets are created.

## Quality flags

Successful snapshots can add these flags to `model_metadata.quality_flags`:

- `input_adjustments_applied`;
- `input_clipping_applied`;
- `mmp_anchors_discarded`;
- `mmp_duplicate_durations_resolved`.

These flags are observational only. They do not independently modify model confidence
or physiological outputs in this phase.
