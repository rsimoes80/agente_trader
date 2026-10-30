"""Verify legacy review inputs or derive an explicit detached schema 2 (MANIFEST-01)."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from aurelia_fx.offline_integrity import canonical
from aurelia_fx.review_manifest import derive_manifest, verify_review_bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--derive-to', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.derive_to and args.manifest:
            raise ValueError('CHOOSE_DERIVE_OR_VERIFY')
        manifest_path = args.manifest
        if args.derive_to:
            target = args.derive_to.resolve()
            if target.is_relative_to(args.bundle.resolve()):
                raise ValueError('DETACHED_MANIFEST_MUST_BE_OUTSIDE_SOURCE')
            m = derive_manifest(args.bundle)
            os.umask(0o077)
            with target.open('xb') as stream:
                stream.write(canonical(m))
            manifest_path = target
        m = verify_review_bundle(args.bundle, manifest_path=manifest_path)
        print(json.dumps(dict(status='INPUTS_VERIFIED', schema_version=m['schema_version'],
                              case_id=m['case_id'], as_of=m['as_of'], trading_authority=False)))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps(dict(status='FAILED_CLOSED', error=str(exc))), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
