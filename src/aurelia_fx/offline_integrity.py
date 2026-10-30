"""Standard-library integrity primitives; no project runtime imports or I/O on import."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_JSON_KEY: ' + key)
        result[key] = value
    return result


def decode(data: bytes):
    return json.loads(data, object_pairs_hook=_unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       indent=2) + '\n').encode()


def safe_file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or '\\' in name:
        raise ValueError('UNSAFE_BUNDLE_PATH')
    parts = PurePosixPath(name)
    if parts.is_absolute() or parts.as_posix() != name or any(p in {'.', '..'} for p in parts.parts):
        raise ValueError('UNSAFE_BUNDLE_PATH')
    path = root
    for part in parts.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('BUNDLE_SYMLINK_FORBIDDEN')
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('BUNDLE_FILE_MISSING: ' + name)
    return path


def checked_files(root: Path, hashes: dict) -> dict[str, bytes]:
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError('EMPTY_HASH_INDEX')
    snapshot = {}
    for name, expected in hashes.items():
        if not isinstance(expected, str) or re.fullmatch('[a-f0-9]{64}', expected) is None:
            raise ValueError('INVALID_SHA256')
        data = safe_file(root, name).read_bytes()
        if sha256(data) != expected:
            raise ValueError('INPUT_HASH_MISMATCH: ' + name)
        snapshot[name] = data
    return snapshot


def validate_case(case):
    if not isinstance(case, dict) or not isinstance(case.get('facts'), dict) or not case['facts']:
        raise ValueError('INVALID_MARKET_CASE')
    unsigned = {k: v for k, v in case.items() if k != 'case_id'}
    # Same serialization as book_skills.digest; avoid importing model runtime.
    digest = sha256(json.dumps(unsigned, sort_keys=True, ensure_ascii=False,
                              allow_nan=False).encode())
    if case.get('case_id') != digest:
        raise ValueError('CASE_CHANGED')
    if case.get('side') not in (None, 'long', 'short'):
        raise ValueError('INVALID_CASE_SIDE')
