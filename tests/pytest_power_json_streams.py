from __future__ import annotations

from api.activity_streams import stream_from_power


def test_power_json_stream_does_not_synthesize_heart_rate() -> None:
    stream = stream_from_power([200.0, 210.0, 205.0])
    assert stream.has_power
    assert not stream.has_heart_rate
    assert stream.data_provenance["source"] == "power_json"
    assert stream.data_provenance["synthetic_signals"] == []
    assert stream.data_provenance["measured_signals"] == ["power"]


def test_power_json_stream_accepts_explicit_hr_json() -> None:
    stream = stream_from_power([200.0, 210.0, 205.0], heart_rate=[140.0, 142.0, 141.0])
    assert stream.has_power
    assert stream.has_heart_rate
    assert stream.data_provenance["measured_signals"] == ["power", "heart_rate"]
