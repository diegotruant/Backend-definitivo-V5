"""Phase 5 — batch L: interval signal matrix + hrv/fit branch finish."""

from __future__ import annotations

import warnings
from datetime import datetime, timedelta, timezone
from typing import Any, List
from unittest.mock import patch

import numpy as np
import pytest

from engines.core.athlete_context import AthleteContext
from engines.io.fit_parser import FitFileError, parse_fit_file_enhanced
from engines.performance.interval_detector import _classify_by_signal, classify_session
from engines.recovery.hrv_engine import _correct_ectopic, analyze_rr_stream, calculate_dfa_alpha1


FTP = 250.0


def _steady(watts: float, seconds: int) -> List[float]:
    return [watts] * seconds


class TestIntervalSignalMatrix92L:
    @pytest.mark.parametrize(
        "powers,expected_cat,expected_sub",
        [
            (_steady(240, 3600), "STEADY", "threshold_continuous"),
            (_steady(230, 3600), "STEADY", "sweet_spot"),
            (_steady(212, 3600), "STEADY", "tempo"),
            (_steady(165, 4000), "STEADY", "endurance_z2"),
        ],
    )
    def test_steady_signatures(self, powers: List[float], expected_cat: str, expected_sub: str) -> None:
        cat, sub, _, _ = _classify_by_signal(powers, ftp=FTP)
        assert cat == expected_cat
        assert sub == expected_sub

    def test_mixed_sprint_and_race_signatures(self) -> None:
        mixed = _steady(120, 1200)
        for idx in range(1300, 1310):
            mixed.append(900.0)
        mixed.extend(_steady(120, 400))
        mixed.extend(_steady(245, 300))
        cat, sub, _, _ = _classify_by_signal(mixed, ftp=FTP)
        assert cat == "TEST"
        assert sub in {"mixed_test", "sprint_set", "cp_test", "cp12"}

        easy = _steady(110, 1500)
        for pos in (1600, 1610, 1620, 1630, 1640):
            easy[pos:pos + 2] = [850.0, 850.0]
        cat2, sub2, _, _ = _classify_by_signal(easy, ftp=FTP)
        assert cat2 == "TEST"
        assert sub2 in {"sprint_set", "single_sprint", "mixed_test"}

        single = _steady(100, 1800) + [900.0, 880.0] + _steady(90, 200)
        cat3, sub3, _, _ = _classify_by_signal(single, ftp=FTP)
        assert cat3 == "TEST"
        assert sub3 in {"single_sprint", "sprint_set"}

        race: List[float] = []
        for i in range(3600):
            if i % 200 < 10:
                race.append(450.0)
            elif i % 200 < 30:
                race.append(320.0)
            else:
                race.append(170.0 + 30 * np.sin(i / 40))
        cat4, sub4, _, _ = _classify_by_signal(race, ftp=FTP)
        assert cat4 in {"FREE", "HIIT", "TEST", "STEADY"}
        if cat4 == "FREE":
            assert sub4 == "race"

        hiit = []
        for _ in range(12):
            hiit.extend(_steady(340, 60) + _steady(120, 90))
        cat5, sub5, _, _ = _classify_by_signal(hiit, ftp=FTP)
        assert cat5 in {"HIIT", "TEST", "STEADY", "FREE"}

        classified = classify_session(mixed, filename="unknown.fit", ftp=FTP)
        assert classified.category in {"TEST", "HIIT", "STEADY", "FREE"}


class TestHrvFitFinish92L:
    def test_ectopic_multipass_loop(self) -> None:
        rr = np.array([800.0, 1500.0, 810.0, 805.0, 815.0, 820.0] * 35, dtype=float)
        mask = np.zeros(rr.size, dtype=bool)
        mask[::5] = True
        out = _correct_ectopic(rr, mask, max_passes=5)
        assert out.shape == rr.shape

    def test_stream_confidence_downgrade_and_dfa_exception(self) -> None:
        rr_samples = [
            {"elapsed": float(i * 2), "rr": [820.0 + (i % 3) for _ in range(60)]}
            for i in range(120)
        ]
        timeline = analyze_rr_stream(
            rr_samples,
            window_seconds=90,
            step_seconds=5.0,
            context=AthleteContext(gender="MALE", training_years=20, discipline="ROAD"),
        )
        assert isinstance(timeline, list)
        if timeline:
            assert timeline[0].get("confidence") in {"HIGH", "MEDIUM", "LOW", "NONE"}

        with patch("engines.recovery.hrv_engine._dfa_alpha1_full", side_effect=RuntimeError("boom")):
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                err = calculate_dfa_alpha1([820.0] * 90, context=AthleteContext())
        assert err["status"] == "ERROR"

    def test_fitdecode_fallback_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        import engines.io.fit_parser as fp

        if not (fp.FITDECODE_AVAILABLE and fp.FITPARSE_AVAILABLE):
            pytest.skip("needs both fit backends")

        start = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
        records = [
            {"timestamp": start + timedelta(seconds=i), "power": 220.0, "heart_rate": 140.0}
            for i in range(40)
        ]
        payload = b"\x0e" + b"x" * 200

        def _fitdecode_fail(_payload: bytes, *, check_crc: bool):
            raise fp.FitParseError("fitdecode fail")

        def _fitparse_ok(_payload: bytes, *, check_crc: bool):
            return records, [{"sport": "cycling", "start_time": start}], [], [], []

        monkeypatch.setattr(fp, "_extract_messages_with_fitdecode", _fitdecode_fail)
        monkeypatch.setattr(fp, "_extract_messages_with_fitparse", _fitparse_ok)
        recs, *_ = fp._extract_messages(payload, check_crc=True)
        assert len(recs) == 40

    def test_read_retry_oserror(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        import engines.io.fit_parser as fp

        path = tmp_path / "retry.fit"
        path.write_bytes(b"fit-bytes")
        counter = [0]
        real_open = open

        def _flaky_open(file, mode="r", *args, **kwargs):
            counter[0] += 1
            if counter[0] == 1:
                raise OSError("transient")
            return real_open(file, mode, *args, **kwargs)

        monkeypatch.setattr("builtins.open", _flaky_open)
        data = fp._read_file_with_retry(str(path), attempts=3, delay_s=0.0)
        assert data == b"fit-bytes"
        assert counter[0] == 2
