"""Apply safety corrections to PR #26 once."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARSER = ROOT / "engines" / "io" / "fit_parser.py"
TESTS = ROOT / "tests" / "pytest_fit_parser_policy.py"
POLICY = ROOT / "docs" / "FIT_PARSER_POLICY.md"

EXPECTED = {
    PARSER: "7e0e300044d77f52182ed391797f396ca400475a",
    TESTS: "c8ca82d08c15408f98c47e108c0876a435af693b",
    POLICY: "d0f4b55c54cfef01ad41469f63dec1282fe7eb6f",
}

REPLACEMENTS = {
    PARSER: [
        ('    if isinstance(error, FitDecoderError):\n        return error\n\n    detail = str(error)\n', '    if isinstance(error, FitDecoderError):\n        return error\n    if isinstance(error, (MemoryError, RecursionError)):\n        raise error\n\n    detail = str(error)\n'),
        ('        except FitDecoderError:\n            if FITPARSE_FALLBACK_AVAILABLE and FITPARSE_AVAILABLE:\n                return _run_decoder_boundary(\n                    _extract_messages_with_fitparse,\n                    payload,\n                    check_crc=check_crc,\n                    backend="fitparse",\n                )\n            raise\n', '        except FitDecoderError as error:\n            if (\n                error.reason != "UNKNOWN"\n                and FITPARSE_FALLBACK_AVAILABLE\n                and FITPARSE_AVAILABLE\n            ):\n                return _run_decoder_boundary(\n                    _extract_messages_with_fitparse,\n                    payload,\n                    check_crc=check_crc,\n                    backend="fitparse",\n                )\n            raise\n'),
        ('    raw = None\n    if repair_synthetic_header:\n        raw = bytearray(_read_file_with_retry(fit_path))\n        # NOTE: we no longer pre-classify a file as "bad" from the 0x40 bit,\n        # because that misfires on valid files with developer-data records.\n        # raw is kept only so the fallback repair path can use it if the\n        # normal parse fails.\n\n    # Some synthetic test files declare a 14-byte header but place the data\n    # section at byte 12. That repair, however, must NEVER touch a valid file:\n    # a legitimate 14-byte header is normal, and the 0x40 bit on the first\n    # record header means "developer data", not "corrupt file". So we try to\n    # parse the file as-is first, and only attempt the byte-0 repair if normal\n    # parsing actually fails.\n    try:\n        payload = bytes(raw) if raw is not None else _read_file_with_retry(fit_path)\n    except OSError as e:\n        raise FitFileError("EMPTY_FILE", f"could not read file: {e}") from e\n', '    # Some synthetic test files declare a 14-byte header but place the data\n    # section at byte 12. That repair, however, must NEVER touch a valid file:\n    # a legitimate 14-byte header is normal, and the 0x40 bit on the first\n    # record header means "developer data", not "corrupt file". So we try to\n    # parse the file as-is first, and only attempt the byte-0 repair if normal\n    # parsing actually fails.\n    try:\n        raw = (\n            bytearray(_read_file_with_retry(fit_path))\n            if repair_synthetic_header\n            else None\n        )\n        # NOTE: we no longer pre-classify a file as "bad" from the 0x40 bit,\n        # because that misfires on valid files with developer-data records.\n        # raw is kept only so the fallback repair path can use it if the\n        # normal parse fails.\n        payload = bytes(raw) if raw is not None else _read_file_with_retry(fit_path)\n    except OSError as error:\n        raise FitFileError(\n            "EMPTY_FILE",\n            f"could not read file: {error}",\n        ) from error\n'),
    ],
    TESTS: [
        ('def test_unknown_fitdecode_error_can_use_the_legacy_fallback(\n    monkeypatch: pytest.MonkeyPatch,\n) -> None:\n    expected = ([{"power": 250}], [], [], [], [])\n    calls: list[str] = []\n\n    def _explode(_payload: bytes, *, check_crc: bool):\n        calls.append("fitdecode")\n        raise RuntimeError("undocumented fitdecode failure")\n\n    def _fallback(_payload: bytes, *, check_crc: bool):\n        calls.append("fitparse")\n        return expected\n\n    monkeypatch.setattr(fit_parser, "FITDECODE_AVAILABLE", True)\n    monkeypatch.setattr(fit_parser, "FITPARSE_FALLBACK_AVAILABLE", True)\n    monkeypatch.setattr(fit_parser, "FITPARSE_AVAILABLE", True)\n    monkeypatch.setattr(fit_parser, "_extract_messages_with_fitdecode", _explode)\n    monkeypatch.setattr(fit_parser, "_extract_messages_with_fitparse", _fallback)\n\n    assert fit_parser._extract_messages(b"payload", check_crc=True) == expected\n    assert calls == ["fitdecode", "fitparse"]\n', 'def test_unknown_fitdecode_error_does_not_use_the_legacy_fallback(\n    monkeypatch: pytest.MonkeyPatch,\n) -> None:\n    calls: list[str] = []\n\n    def _explode(_payload: bytes, *, check_crc: bool):\n        calls.append("fitdecode")\n        raise RuntimeError("undocumented fitdecode failure")\n\n    def _fallback(_payload: bytes, *, check_crc: bool):\n        calls.append("fitparse")\n        return ([{"power": 250}], [], [], [], [])\n\n    monkeypatch.setattr(fit_parser, "FITDECODE_AVAILABLE", True)\n    monkeypatch.setattr(fit_parser, "FITPARSE_FALLBACK_AVAILABLE", True)\n    monkeypatch.setattr(fit_parser, "FITPARSE_AVAILABLE", True)\n    monkeypatch.setattr(fit_parser, "_extract_messages_with_fitdecode", _explode)\n    monkeypatch.setattr(fit_parser, "_extract_messages_with_fitparse", _fallback)\n\n    with pytest.raises(fit_parser.FitDecoderError) as exc:\n        fit_parser._extract_messages(b"payload", check_crc=True)\n\n    assert exc.value.backend == "fitdecode"\n    assert exc.value.reason == "UNKNOWN"\n    assert calls == ["fitdecode"]\n'),
        ('def test_unknown_fitdecode_error_is_typed_when_no_fallback_exists(\n    monkeypatch: pytest.MonkeyPatch,\n) -> None:\n', '@pytest.mark.parametrize(\n    "fatal_error",\n    [MemoryError("oom"), RecursionError("deep")],\n)\ndef test_decoder_boundary_does_not_hide_fatal_errors(\n    fatal_error: Exception,\n) -> None:\n    def _explode(_payload: bytes, *, check_crc: bool):\n        raise fatal_error\n\n    with pytest.raises(type(fatal_error)):\n        fit_parser._run_decoder_boundary(\n            _explode,\n            b"payload",\n            check_crc=True,\n            backend="fitdecode",\n        )\n\n\n' + 'def test_unknown_fitdecode_error_is_typed_when_no_fallback_exists(\n    monkeypatch: pytest.MonkeyPatch,\n) -> None:\n'),
    ],
    POLICY: [
        ("Il boundary contiene l'unico `except Exception` ammesso nel parser FIT e converte immediatamente ogni errore in `FitDecoderError`, valorizzando:\n", "Il boundary contiene l'unico `except Exception` ammesso nel parser FIT e converte immediatamente ogni errore non fatale in `FitDecoderError`, valorizzando:\n"),
        ("Il parser principale gestisce soltanto `FitDecoderError`. Nel percorso di recupero l'errore interno viene convertito in `FitFileError` mantenendo invariati i reason code esterni.\n", "`MemoryError` e `RecursionError` non vengono convertiti: devono propagarsi perché indicano un problema di risorse o di processo.\n\nIl parser principale gestisce soltanto `FitDecoderError`. Nel percorso di recupero l'errore interno viene convertito in `FitFileError` mantenendo invariati i reason code esterni. Il fallback `fitparse` viene tentato per errori FIT classificati, ma non per `UNKNOWN`, così un errore applicativo non viene nascosto.\n"),
        ('- le eccezioni note e sconosciute dei decoder vengano trasformate in `FitDecoderError`;\n- il parser pubblico non interpreti direttamente le gerarchie di eccezioni delle librerie;\n', '- le eccezioni non fatali dei decoder vengano trasformate in `FitDecoderError`;\n- `MemoryError` e `RecursionError` non vengano nascosti;\n- `UNKNOWN` non abiliti il fallback legacy;\n- il parser pubblico non interpreti direttamente le gerarchie di eccezioni delle librerie;\n'),
    ],
}


def _blob_sha(path: Path) -> str:
    payload = path.read_bytes()
    return hashlib.sha1(
        f"blob {len(payload)}\0".encode("utf-8") + payload
    ).hexdigest()


def _replace_once(text: str, old: str, new: str, path: Path) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{path} replacement anchor count is {count}, expected 1"
        )
    return text.replace(old, new, 1)


def _generic_catch_owners(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    owners: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if any(
            isinstance(child, ast.ExceptHandler)
            and isinstance(child.type, ast.Name)
            and child.type.id == "Exception"
            for child in ast.walk(node)
        ):
            owners.append(node.name)
    return owners


def main() -> None:
    for path, expected in EXPECTED.items():
        actual = _blob_sha(path)
        if actual != expected:
            raise RuntimeError(
                f"{path} hash {actual} does not match reviewed baseline {expected}"
            )

    for path, replacements in REPLACEMENTS.items():
        text = path.read_text(encoding="utf-8")
        for old, new in replacements:
            text = _replace_once(text, old, new, path)
        path.write_text(text, encoding="utf-8")

    ast.parse(PARSER.read_text(encoding="utf-8"))
    ast.parse(TESTS.read_text(encoding="utf-8"))

    if _generic_catch_owners(PARSER) != ["_run_decoder_boundary"]:
        raise RuntimeError("generic catch escaped the decoder boundary")

    parser_text = PARSER.read_text(encoding="utf-8")
    if 'error.reason != "UNKNOWN"' not in parser_text:
        raise RuntimeError("UNKNOWN fallback guard missing")
    if "MemoryError, RecursionError" not in parser_text:
        raise RuntimeError("fatal decoder error guard missing")

    print("PR #26 FIT boundary safety corrections applied.")


if __name__ == "__main__":
    main()
