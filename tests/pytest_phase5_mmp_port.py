"""Port of tests/integration/test_mmp_aggregator.py for coverage."""

from __future__ import annotations

from datetime import date

import numpy as np

from engines.performance.mmp_aggregator import curve_to_mmp, extract_ride_curve, update_power_curve


class TestMmpAggregatorPort:
    def test_extract_ride_curve(self) -> None:
        ride = np.full(1000, 200.0)
        ride[100:130] = 400.0
        rc = extract_ride_curve(list(ride))
        assert len(rc) > 5
        assert 380 <= rc.get(30, 0) <= 400
        assert extract_ride_curve([]) == {}
        assert extract_ride_curve([0.0] * 500) == {}

    def test_update_power_curve_lifecycle(self) -> None:
        ride = np.full(1000, 200.0)
        ride[100:130] = 400.0
        res = update_power_curve(list(ride), date(2026, 1, 1), {}, "ride1", weight_kg=70)
        assert len(res.improvements) > 5
        assert res.profile_should_refresh
        assert len(res.mmp_for_profiler) > 5

        weak = np.full(1000, 150.0)
        res2 = update_power_curve(list(weak), date(2026, 1, 6), res.curve, "ride2", weight_kg=70)
        assert len(res2.improvements) == 0

        strong = np.full(1000, 200.0)
        strong[100:130] = 500.0
        res3 = update_power_curve(list(strong), date(2026, 1, 11), res.curve, "ride3", weight_kg=70)
        imp_30 = [i for i in res3.improvements if i["duration_s"] == 30]
        assert len(imp_30) == 1

    def test_despike_and_curve_to_mmp(self) -> None:
        spike = np.full(2000, 220.0)
        spike[1000] = 1500.0
        rc_spike = extract_ride_curve(list(spike), despike=True)
        assert rc_spike.get(1, 0) < 600

        sprint = np.full(100, 200.0)
        sprint[40:50] = 1100.0
        rc_sprint = extract_ride_curve(list(sprint), despike=True)
        assert rc_sprint.get(5, 0) > 900

        mmp = curve_to_mmp({60: {"power_w": 400.0}, 300: {"power_w": 320.0}})
        assert 60 in mmp and 300 in mmp
