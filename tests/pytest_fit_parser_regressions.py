from __future__ import annotations

from types import SimpleNamespace

import pytest

import engines.io.fit_parser as fp


def test_fitdecode_field_extraction_uses_frame_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeDataMessage:
        def __init__(self, name: str, fields: list[object]) -> None:
            self.name = name
            self.fields = fields

    class _FakeReader:
        def __init__(self, *_args, **_kwargs) -> None:
            self._frames = [
                _FakeDataMessage("record", [SimpleNamespace(name="power", value=310)]),
                _FakeDataMessage("session", [SimpleNamespace(name="sport", value="cycling")]),
            ]

        def __enter__(self):
            return iter(self._frames)

        def __exit__(self, *_args) -> bool:
            return False

    fake_fitdecode = SimpleNamespace(
        CrcCheck=SimpleNamespace(RAISE=1, DISABLED=0),
        FitReader=_FakeReader,
        records=SimpleNamespace(FitDataMessage=_FakeDataMessage),
    )
    monkeypatch.setattr("engines.io.fit_parser.fitdecode", fake_fitdecode, raising=False)

    records, sessions, device_infos, hrv_msgs, lap_msgs = fp._extract_messages_with_fitdecode(
        b"ignored",
        check_crc=True,
    )

    assert records == [{"power": 310}]
    assert sessions == [{"sport": "cycling"}]
    assert device_infos == []
    assert hrv_msgs == []
    assert lap_msgs == []


def test_normalize_lap_messages_coerces_naive_start_time_to_utc_iso() -> None:
    naive = fp.datetime(2025, 6, 15, 8, 0, 0)
    laps = fp.normalize_lap_messages(
        [
            {
                "total_elapsed_time": 120,
                "start_time": naive,
                "avg_power": 226,
            }
        ]
    )
    assert laps[0]["start_time"] == "2025-06-15T08:00:00+00:00"


def test_hrv_dict_messages_are_consumed_without_fields_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = fp.datetime(2026, 1, 1, 9, 0, 0)

    monkeypatch.setattr(
        fp,
        "_extract_messages",
        lambda *_args, **_kwargs: (
            [{"timestamp": start, "power": 220, "heart_rate": 145}],
            [{"start_time": start, "total_elapsed_time": 1.0, "sport": "cycling"}],
            [],
            [{"time": [0.2, 0.2, 0.2]}],
            [],
        ),
    )

    stream = fp.parse_fit_file_enhanced(__file__, repair_synthetic_header=False, check_crc=False)
    assert any(stream.rr_intervals)
