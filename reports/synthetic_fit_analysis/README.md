# Synthetic FIT dataset analysis

Generated with `analyze_synthetic_fit_dataset.py` using the backend engines.

## Dataset summary

- Athletes: 50
- FIT files parsed: 2500
- FIT files with errors: 0
- Total analyzed duration: 4506.3 h
- Total TSS: 331657.4
- Mean data quality score: 0.906

## Top 10 by estimated FTP

| Athlete | FTP W | Best 20 min W | Total TSS | Avg quality | Metabolic status |
| --- | ---: | ---: | ---: | ---: | --- |
| 033_Athlete_33 | 555.4 | 584.6 | 3928.2 | 0.936 | success |
| 016_Athlete_16 | 542.0 | 570.5 | 4948.0 | 0.939 | success |
| 029_Athlete_29 | 525.4 | 553.1 | 4544.5 | 0.939 | success |
| 026_Athlete_26 | 477.3 | 502.4 | 4420.8 | 0.94 | success |
| 023_Athlete_23 | 464.2 | 488.6 | 5324.5 | 0.94 | success |
| 035_Athlete_35 | 461.5 | 485.8 | 4058.7 | 0.936 | success |
| 019_Athlete_19 | 454.2 | 478.1 | 4320.3 | 0.939 | success |
| 021_Athlete_21 | 430.7 | 453.4 | 4130.6 | 0.939 | success |
| 036_Athlete_36 | 429.3 | 451.9 | 4285.1 | 0.94 | success |
| 022_Athlete_22 | 394.6 | 415.4 | 4483.0 | 0.94 | success |

## Top 10 by estimated VO2max

| Athlete | VO2max | VLamax | MLSS W | FatMax W | Confidence |
| --- | ---: | ---: | ---: | ---: | ---: |
| 016_Athlete_16 | 85.9 | 0.205 | 495.0 | 372.5 | 0.05 |
| 026_Athlete_26 | 85.9 | 0.2049 | 495.0 | 372.5 | 0.05 |
| 029_Athlete_29 | 85.9 | 0.205 | 495.0 | 372.5 | 0.05 |
| 033_Athlete_33 | 85.9 | 0.205 | 495.0 | 372.5 | 0.05 |
| 023_Athlete_23 | 85.8 | 0.2328 | 485.0 | 362.5 | 0.05 |
| 035_Athlete_35 | 85.8 | 0.2196 | 490.0 | 367.5 | 0.05 |
| 019_Athlete_19 | 85.4 | 0.2861 | 470.0 | 345.0 | 0.05 |
| 021_Athlete_21 | 83.3 | 0.3245 | 450.0 | 325.0 | 0.05 |
| 036_Athlete_36 | 82.3 | 0.3167 | 445.0 | 320.0 | 0.05 |
| 024_Athlete_24 | 73.8 | 0.2217 | 410.0 | 302.5 | 0.05 |

## Notes

- The source files are synthetic and required a lightweight synthetic binary parser.
- Power/HR/cadence records are expanded to a 1 Hz timeline before running the backend.
- Metabolic estimates are model-derived from aggregate MMP per athlete and are not lab validated.
- Detailed per-athlete and per-file outputs are in the CSV files next to this report.
