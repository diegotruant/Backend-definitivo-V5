# Uploaded FIT full engine audit

Race prediction requires GPX course input (marked skipped_no_gpx).
Lab ingestion requires files under data/lab_uploads/ (optional).
W' balance uses CP from MMP fit and a heuristic W' capacity (CP × 90 s, clamped).

## Engine status summary

| Engine | Status counts |
| --- | --- |
| bayesian_profiler | {'success': 6} |
| cardiac_engine | {'success': 6} |
| chart_builder | {'success': 6} |
| chart_builder_training_load | {'success': 6} |
| coggan_classifier | {'success': 6} |
| cross_validation_engine | {'success': 5, 'warning': 1} |
| data_quality_engine | {'success': 6} |
| detraining_engine | {'success': 6} |
| durability_engine | {'success': 6} |
| efforts_analyzer | {'success': 6} |
| explainability_engine | {'success': 6} |
| fit_parser | {'success': 6} |
| heat_acclimation | {'skipped_no_body_temperature': 6} |
| hourly_decay_curve | {'success': 6} |
| hrv_engine | {'success': 3, 'skipped_no_rr': 3} |
| interval_detector | {'success': 6} |
| lab_data | {'skipped_no_lab_file': 6} |
| metabolic_current | {'error': 4, 'success': 2} |
| metabolic_flexibility_engine | {'success': 6} |
| metabolic_kalman | {'success': 6} |
| metabolic_profiler | {'success': 6} |
| mmp_aggregator | {'success': 6} |
| mmp_quality | {'success': 6} |
| neural_ode | {'success': 6} |
| np_drift | {'success': 6} |
| pedaling_balance | {'skipped_no_balance': 2, 'success': 4} |
| power_engine | {'success': 6} |
| race_prediction_engine | {'skipped_no_gpx': 6} |
| thermal_engine | {'skipped_no_body_temperature': 6} |
| training_variability_engine | {'success': 6} |
| w_prime_balance_engine | {'success': 6} |
| workout_summary | {'success': 6} |
| zones_engine | {'success': 6} |

## Exceptions

No backend exceptions detected.