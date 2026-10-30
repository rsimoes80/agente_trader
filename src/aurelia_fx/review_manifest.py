"""MANIFEST-01: detached schema 2; legacy schema 1 remains strict and unmodified."""
from __future__ import annotations

from pathlib import Path
from .offline_integrity import checked_files, decode, safe_file, sha256, validate_case

REQUIRED = frozenset({'case.json', 'sources.json', 'hypothesis.md',
                     'code_agent_strategy.py.txt', 'code_entry_trend.py.txt',
                     'code_literature_basis.py.txt'})


def _identity(manifest, case):
    validate_case(case)
    if manifest.get('trading_authority') is not False:
        raise ValueError('REVIEW_MANIFEST_INVALID')
    if any(manifest.get(k) != case.get(k) for k in ('case_id', 'as_of')):
        raise ValueError('REVIEW_CASE_MISMATCH')


def verify_review_bundle(folder, *, manifest_path=None):
    root = Path(folder)
    raw = (Path(manifest_path) if manifest_path else safe_file(root, 'manifest.json')).read_bytes()
    m = decode(raw)
    version = m.get('schema_version')
    if type(version) is not int or version not in {1, 2}:
        raise ValueError('REVIEW_MANIFEST_INVALID')
    if version == 1:
        if not isinstance(m.get('files'), dict) or set(m['files']) != REQUIRED:
            raise ValueError('REVIEW_MANIFEST_INVALID')
        snapshot = checked_files(root, m['files'])
    else:
        inputs, attachments = m.get('required_inputs'), m.get('attachments')
        if (not isinstance(inputs, dict) or set(inputs) != REQUIRED
                or not isinstance(attachments, dict) or set(inputs) & set(attachments)):
            raise ValueError('REVIEW_MANIFEST_INVALID')
        parent = m.get('parent_manifest', {})
        if parent.get('path') != 'manifest.json':
            raise ValueError('REVIEW_PARENT_INVALID')
        all_hashes = {**inputs, **attachments}
        if 'manifest.json' in all_hashes:
            raise ValueError('REVIEW_MANIFEST_INVALID')
        snapshot = checked_files(root, {**all_hashes, parent['path']: parent.get('sha256')})
        original = decode(snapshot['manifest.json'])
        _identity(original, decode(snapshot['case.json']))
        original_files = original.get('files')
        if (type(original.get('schema_version')) is not int or original['schema_version'] != 1
                or not isinstance(original_files, dict) or not REQUIRED <= set(original_files)
                or any(all_hashes.get(n) != h for n, h in original_files.items())):
            raise ValueError('REVIEW_PARENT_ENTRIES_LOST')
    _identity(m, decode(snapshot['case.json']))
    return m


def derive_manifest(folder):
    """Return a detached manifest; never write or delete anything in the source bundle."""
    root = Path(folder)
    raw = safe_file(root, 'manifest.json').read_bytes()
    parent = decode(raw)
    files = parent.get('files')
    if (type(parent.get('schema_version')) is not int or parent['schema_version'] != 1
            or not isinstance(files, dict) or not REQUIRED <= set(files)):
        raise ValueError('REVIEW_MANIFEST_INVALID')
    snapshot = checked_files(root, files)
    case = decode(snapshot['case.json'])
    _identity(parent, case)
    # Preserve and verify every declared hash, including post-review reports.
    index_path = root / 'artifact_hashes.json'
    hashes = dict(files)
    if index_path.exists():
        index_raw = safe_file(root, 'artifact_hashes.json').read_bytes()
        index = decode(index_raw)
        checked_files(root, index)
        for n, h in index.items():
            if n in hashes and hashes[n] != h:
                raise ValueError('REVIEW_HASH_INDEX_CONFLICT')
            hashes[n] = h
        hashes['artifact_hashes.json'] = sha256(index_raw)
    # All source documents are covered, not just the six legacy inputs.
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('BUNDLE_SYMLINK_FORBIDDEN')
        if path.is_file():
            name = path.relative_to(root).as_posix()
            data = safe_file(root, name).read_bytes()
            if name in hashes and sha256(data) != hashes[name]:
                raise ValueError('INPUT_HASH_MISMATCH: ' + name)
            if name != 'manifest.json':
                hashes[name] = sha256(data)
    return dict(schema_version=2, case_id=case['case_id'], as_of=case['as_of'],
                trading_authority=False,
                parent_manifest=dict(path='manifest.json', sha256=sha256(raw)),
                required_inputs={n: hashes[n] for n in sorted(REQUIRED)},
                attachments={n: h for n, h in sorted(hashes.items()) if n not in REQUIRED and n != 'manifest.json'},
                scope='Integrity only; attachments do not imply review or trading approval.')
