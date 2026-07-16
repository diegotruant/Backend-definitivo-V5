# Zero-power and average-power contract

## Scope

This contract defines how cycling power and cadence zero values are interpreted
and how ride-level average power is exposed.

## Signal quality

- `0 W` is a valid measured power sample while coasting or stopped.
- `0 rpm` is a valid measured cadence sample while coasting.
- Zero values do not reduce numeric coverage.
- Non-finite/out-of-range samples reduce coverage.
- A parser sample flagged `QUALITY_UNRELIABLE` reduces coverage even when its
  placeholder value is numeric.
- Interpolated and forward-filled samples remain covered but are reported in
  `quality_flags`.
- A zero-only power stream is not considered usable for power analytics.

## Average power fields

| Field | Definition |
|---|---|
| `avg_power_w` | Canonical mean over the complete recorded 1 Hz timeline, including valid 0 W samples. |
| `avg_power_elapsed_w` | Explicit alias of `avg_power_w`. |
| `avg_power_pedaling_w` | Mean over samples with power strictly greater than 0 W. |
| `*_w_kg` | Corresponding value divided by athlete mass. |

`avg_power_w`, work, Normalized Power and Variability Index now use a coherent
timeline contract. The positive-only value formerly returned as
`avg_power_w` is preserved under `avg_power_pedaling_w`.

## Frontend display

The statistics page labels the canonical metric as **Average power (elapsed)**
and the positive-only metric as **Average power (pedaling)**. Clients that only
read `avg_power_w` remain structurally compatible but receive the corrected
canonical definition.

## Regression evidence

The patch was tested on ten real FIT files containing 7.61–33.94% zero-power
samples. All files retained 100% power/cadence coverage where parser unreliable
flags were absent. Statistics and power-chart summaries matched for elapsed
average, pedaling average and NP. MMP and metabolic outputs were unchanged.
