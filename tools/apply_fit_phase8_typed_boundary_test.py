"""Update the obsolete direct-decoder expectation for PR #26 once."""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST = ROOT / "tests" / "pytest_phase8_coverage_100.py"
EXPECTED_SHA = "be44dd370b5869b6b6d501f52dbaf16b552631b0"

OLD = '''        with pytest.raises(fp.FitParseCRCError):
            fp._extract_messages(b"payload", check_crc=True)
'''
NEW = '''        with pytest.raises(fp.FitDecoderError) as exc:
            fp._extract_messages(b"payload", check_crc=True)
        assert exc.value.reason == "CRC_MISMATCH"
        assert exc.value.backend == "fitdecode"
        assert isinstance(exc.value.__cause__, fp.FitParseCRCError)
'''


def blob_sha(path: Path) -> str:
    payload = path.read_bytes()
    return hashlib.sha1(
        f"blob {len(payload)}\0".encode("utf-8") + payload
    ).hexdigest()


def main() -> None:
    if blob_sha(TEST) != EXPECTED_SHA:
        raise RuntimeError("phase8 test file does not match reviewed main baseline")

    source = TEST.read_text(encoding="utf-8")
    if source.count(OLD) != 1:
        raise RuntimeError("typed boundary test anchor missing or ambiguous")
    TEST.write_text(source.replace(OLD, NEW, 1), encoding="utf-8")
    compile(TEST.read_text(encoding="utf-8"), str(TEST), "exec")
    print("Phase8 FIT boundary expectation updated.")


if __name__ == "__main__":
    main()
