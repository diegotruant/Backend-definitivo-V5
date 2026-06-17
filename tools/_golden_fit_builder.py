"""Build golden FIT files via garmin-fit-sdk (invoked by generate_golden_fit_assets.py)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from garmin_fit_sdk import Decoder, Stream
from garmin_fit_sdk.encoder import Encoder

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "tests" / "assets" / "fit"

MESG_FILE_ID = 0
MESG_SESSION = 18
MESG_LAP = 19
MESG_RECORD = 20
MESG_HRV = 78

MANUFACTURER = {
    "garmin": 1,
    "wahoo": 73,
    "zwift": 255,  # development
    "tacx": 6,
}


def _base_time() -> datetime:
    return datetime(2025, 6, 15, 8, 0, 0, tzinfo=timezone.utc)


def _write(name: str, messages: list[dict]) -> Path:
    path = OUT / name
    encoder = Encoder()
    for mesg in messages:
        encoder.write_mesg(mesg)
    path.write_bytes(encoder.close())
    with path.open("rb") as fh:
        if not Decoder(Stream.from_bytes_io(BytesIO(fh.read()))).is_fit():
            raise RuntimeError(f"generated invalid FIT: {name}")
    return path


def _file_id(manufacturer: str | None = None) -> dict:
    fields: dict = {"mesg_num": MESG_FILE_ID, "type": 4}
    if manufacturer:
        fields["manufacturer"] = MANUFACTURER.get(manufacturer, 255)
    return fields


def _session(t0: datetime) -> dict:
    return {"mesg_num": MESG_SESSION, "sport": 2, "start_time": t0}


def garmin_power_hr() -> None:
    t0 = _base_time()
    records = [
        {
            "mesg_num": MESG_RECORD,
            "timestamp": t0 + timedelta(seconds=i),
            "power": 200 + (i % 20),
            "heart_rate": 130 + (i % 10),
        }
        for i in range(121)
    ]
    _write("garmin_power_hr.fit", [_file_id("garmin"), _session(t0), *records])


def garmin_rr_hrv() -> None:
    t0 = _base_time()
    records = [
        {"mesg_num": MESG_RECORD, "timestamp": t0 + timedelta(seconds=i), "heart_rate": 120 + i % 5}
        for i in range(61)
    ]
    hrv = [{"mesg_num": MESG_HRV, "time": [800 + (i % 3) * 10 for i in range(8)]} for _ in range(3)]
    _write("garmin_rr_hrv.fit", [_file_id("garmin"), _session(t0), *records, *hrv])


def wahoo_power_cadence() -> None:
    t0 = _base_time()
    records = [
        {
            "mesg_num": MESG_RECORD,
            "timestamp": t0 + timedelta(seconds=i),
            "power": 180 + i % 15,
            "cadence": 85 + i % 4,
        }
        for i in range(91)
    ]
    _write("wahoo_power_cadence.fit", [_file_id("wahoo"), _session(t0), *records])


def no_power_hr_only() -> None:
    t0 = _base_time()
    records = [
        {"mesg_num": MESG_RECORD, "timestamp": t0 + timedelta(seconds=i), "heart_rate": 110 + i % 6}
        for i in range(61)
    ]
    _write("no_power_hr_only.fit", [_file_id(), _session(t0), *records])


def indoor_trainer_erg() -> None:
    t0 = _base_time()
    records = [
        {"mesg_num": MESG_RECORD, "timestamp": t0 + timedelta(seconds=i), "power": 250}
        for i in range(301)
    ]
    _write("indoor_trainer_erg.fit", [_file_id("tacx"), _session(t0), *records])


def zwift_virtual() -> None:
    t0 = _base_time()
    records = [
        {
            "mesg_num": MESG_RECORD,
            "timestamp": t0 + timedelta(seconds=i),
            "power": 190 + (i // 10) * 2,
            "heart_rate": 140 + i % 8,
            "cadence": 90,
        }
        for i in range(121)
    ]
    _write("zwift_virtual.fit", [_file_id("zwift"), _session(t0), *records])


def truncated_fit() -> None:
    full = OUT / "garmin_power_hr.fit"
    if not full.exists():
        garmin_power_hr()
    data = full.read_bytes()
    OUT.joinpath("truncated.fit").write_bytes(data[: max(64, len(data) // 3)])


def bad_crc_fit() -> None:
    full = OUT / "garmin_power_hr.fit"
    if not full.exists():
        garmin_power_hr()
    data = bytearray(full.read_bytes())
    if len(data) > 20:
        data[-5] ^= 0xFF
    OUT.joinpath("bad_crc.fit").write_bytes(data)


def minimal_power_hr_lap_hrv() -> None:
    t0 = _base_time()
    records = [
        {
            "mesg_num": MESG_RECORD,
            "timestamp": t0 + timedelta(seconds=i),
            "power": 220 + (i % 12),
            "heart_rate": 135 + (i % 7),
            "cadence": 88 + (i % 3),
        }
        for i in range(121)
    ]
    lap = {
        "mesg_num": MESG_LAP,
        "start_time": t0,
        "total_elapsed_time": 120.0,
        "avg_power": 226,
        "max_power": 240,
        "avg_heart_rate": 138,
    }
    hrv = [{"mesg_num": MESG_HRV, "time": [820, 810, 805, 815, 800, 825, 830, 810]}]
    _write(
        "minimal_power_hr_lap_hrv.fit",
        [_file_id("garmin"), _session(t0), *records, lap, *hrv],
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    minimal_power_hr_lap_hrv()
    garmin_power_hr()
    garmin_rr_hrv()
    wahoo_power_cadence()
    no_power_hr_only()
    indoor_trainer_erg()
    zwift_virtual()
    truncated_fit()
    bad_crc_fit()
    print(f"generated golden FIT assets in {OUT}")


if __name__ == "__main__":
    main()
