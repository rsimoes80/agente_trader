"""Diagnose a sealed case offline. No broker/database/model access."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from aurelia_fx.causal_diagnostic import load_and_diagnose, markdown
from aurelia_fx.offline_integrity import canonical, sha256


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--expected-index-sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        root, output = args.bundle.resolve(), args.output.resolve()
        if output.is_relative_to(root) or root.is_relative_to(output):
            raise ValueError('OUTPUT_OVERLAPS_FROZEN_INPUT')
        if output.exists():
            raise ValueError('OUTPUT_ALREADY_EXISTS')
        report, provenance = load_and_diagnose(root, args.expected_index_sha256)
        provenance['command_sha256'] = sha256(Path(__file__).read_bytes())
        # No input is written. New output only, and no implicit parent creation.
        os.umask(0o077)
        output.mkdir(mode=0o700, exist_ok=False)
        (output / 'diagnostic.json').write_bytes(canonical(report))
        (output / 'report.md').write_text(markdown(report), encoding='utf-8')
        (output / 'timeline.jsonl').write_bytes(b''.join(
            (json.dumps(e, sort_keys=True, ensure_ascii=False) + '\n').encode() for e in report['timeline']))
        (output / 'provenance.json').write_bytes(canonical(provenance))
        hashes = {p.name: sha256(p.read_bytes()) for p in sorted(output.iterdir())}
        (output / 'artifact_hashes.json').write_bytes(canonical(hashes))
        print(json.dumps(dict(status='DIAGNOSED_OFFLINE', output=str(output), case_id=report['case_id'],
                              as_of=report['as_of'], report_sha256=provenance['report_sha256']), ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps(dict(status='FAILED_CLOSED', error=str(exc)), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
