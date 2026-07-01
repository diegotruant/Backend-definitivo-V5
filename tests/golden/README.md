# Scientific golden fixtures

These JSON files are versioned scientific regression fixtures for the stateless backend core.
They are not a substitute for external laboratory validation. Their purpose is to catch
unintended model drift during refactors.

## Fixture families

- `metabolic_lab_cases.json` — representative MMP profiles and direct protocol cases.
- `lactate_lab_cases.json` — independent lactate-derived threshold anchors and model-vs-lab validation cases.
- `durability_cases.json` — long-ride durability and power-pattern regressions.
- `workout_compliance_cases.json` — prescribed workout vs activity comparison cases.
- `adaptive_load_cases.json` — load/recommendation regression cases.
- `twin_state_cases.json` — state build, validate, and update cases.

## Rules

Golden fixtures should test stable scientific behavior, not implementation internals.
Prefer ranges and monotonic expectations over exact floating-point values unless the
formula is deterministic and deliberately locked.

A new fixture should include:

1. a stable `id`;
2. a short `description` explaining the physiological scenario;
3. the smallest input payload that represents the case;
4. expected ranges or categorical outcomes;
5. confidence/masking expectations when input expressiveness is incomplete.

## Interpretation

A golden-test failure means one of three things:

1. the model regressed;
2. the model intentionally changed and the fixture expectation must be reviewed;
3. the fixture itself was too narrow or poorly justified.

Do not blindly update expected values. First decide whether the changed output is more
physiologically correct than the previous baseline.
