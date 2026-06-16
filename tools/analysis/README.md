# tools/analysis/

Offline analysis scripts moved from the repository root.

| Script | Purpose |
|---|---|
| `analyze_synthetic_fit_dataset.py` | Batch analytics over the synthetic FIT dataset |
| `analyze_uploaded_fit_archives.py` | Inspect uploaded FIT archives |
| `analyze_uploaded_fit_full_engine_audit.py` | Run every backend engine over uploaded FIT files |

Run from the repository root so `engines` imports resolve:

```bash
python tools/analysis/analyze_synthetic_fit_dataset.py
```
