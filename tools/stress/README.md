# tools/stress/

Stress and validation harnesses moved from the repository root.

| Script | Purpose |
|---|---|
| `comprehensive_stress_test.py` | Full engine regression stress suite |
| `validate_on_real_fits.py` | Classify and validate real FIT uploads |
| `adversarial_fuzz.py` | Adversarial API fuzzing harness |

Run from the repository root:

```bash
python tools/stress/comprehensive_stress_test.py
```
