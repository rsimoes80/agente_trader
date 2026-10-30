import copy
import json
from pathlib import Path
import tempfile
import unittest

from aurelia_fx.offline_integrity import canonical, checked_files, decode, sha256
from aurelia_fx.review_manifest import REQUIRED, derive_manifest, verify_review_bundle


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'bundle'; self.root.mkdir()
        case=dict(facts={'synthetic':True}, side='long', as_of='2026-01-01T00:00:00+00:00', symbol='TEST')
        case['case_id']=sha256(json.dumps(case,sort_keys=True,ensure_ascii=False,allow_nan=False).encode())
        for n in REQUIRED:
            (self.root/n).write_bytes(canonical(case) if n=='case.json' else b'synthetic\n')
        self.m=dict(schema_version=1,case_id=case['case_id'],as_of=case['as_of'],trading_authority=False,
                    files={n:sha256((self.root/n).read_bytes()) for n in REQUIRED})
        self.save()

    def save(self):
        (self.root/'manifest.json').write_bytes(canonical(self.m))

    def detached(self):
        m=derive_manifest(self.root); path=self.root.parent/'schema2.json';path.write_bytes(canonical(m));return path,m

    def test_legacy_six_input_schema_is_compatible_and_still_strict(self):
        self.assertEqual(verify_review_bundle(self.root),self.m)
        (self.root/'report.md').write_text('extra report')
        self.m['files']['report.md']=sha256((self.root/'report.md').read_bytes());self.save()
        with self.assertRaisesRegex(ValueError,'REVIEW_MANIFEST_INVALID'):
            verify_review_bundle(self.root)
        sidecar,m=self.detached()
        self.assertEqual(verify_review_bundle(self.root,manifest_path=sidecar)['schema_version'],2)
        self.assertIn('report.md',m['attachments'])

    def test_derivation_preserves_all_original_bytes_and_hashes(self):
        (self.root/'report.md').write_text('report')
        self.m['files']['report.md']=sha256((self.root/'report.md').read_bytes());self.save()
        before={p.name:p.read_bytes() for p in self.root.iterdir()}
        path,m=self.detached();verify_review_bundle(self.root,manifest_path=path)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})
        self.assertEqual({**m['required_inputs'],**m['attachments']}['report.md'],self.m['files']['report.md'])

    def test_no_lost_parent_attachment_or_weakened_input_validation(self):
        (self.root/'report.md').write_text('report')
        self.m['files']['report.md']=sha256((self.root/'report.md').read_bytes());self.save()
        path,m=self.detached();m['attachments'].pop('report.md');path.write_bytes(canonical(m))
        with self.assertRaisesRegex(ValueError,'REVIEW_PARENT_ENTRIES_LOST'):
            verify_review_bundle(self.root,manifest_path=path)
        path,m=self.detached();(self.root/'hypothesis.md').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'INPUT_HASH_MISMATCH'):
            verify_review_bundle(self.root,manifest_path=path)

    def test_missing_required_file_entry_or_unknown_version_is_rejected(self):
        path,m=self.detached();m['required_inputs'].pop('sources.json');path.write_bytes(canonical(m))
        with self.assertRaisesRegex(ValueError,'REVIEW_MANIFEST_INVALID'):
            verify_review_bundle(self.root,manifest_path=path)
        self.m['schema_version']=99;self.save()
        with self.assertRaisesRegex(ValueError,'REVIEW_MANIFEST_INVALID'):
            verify_review_bundle(self.root)

    def test_authority_case_mismatch_and_tampered_case_fail_closed(self):
        self.m['trading_authority']=True;self.save()
        with self.assertRaisesRegex(ValueError,'REVIEW_MANIFEST_INVALID'):
            verify_review_bundle(self.root)
        self.m['trading_authority']=False;self.m['as_of']='different';self.save()
        with self.assertRaisesRegex(ValueError,'REVIEW_CASE_MISMATCH'):
            verify_review_bundle(self.root)
        self.m['as_of']='2026-01-01T00:00:00+00:00'
        c=decode((self.root/'case.json').read_bytes());c['facts']['synthetic']=False
        (self.root/'case.json').write_bytes(canonical(c));self.m['files']['case.json']=sha256((self.root/'case.json').read_bytes());self.save()
        with self.assertRaisesRegex(ValueError,'CASE_CHANGED'):
            verify_review_bundle(self.root)

    def test_traversal_absolute_path_and_symlink_are_rejected(self):
        external=self.root.parent/'external';external.write_bytes(b'test')
        for n in ['../external',str(external),'a//b','./case.json']:
            with self.subTest(n=n),self.assertRaises(ValueError):
                checked_files(self.root,{n:sha256(b'test')})
        (self.root/'link').symlink_to(external)
        with self.assertRaisesRegex(ValueError,'BUNDLE_SYMLINK_FORBIDDEN'):
            checked_files(self.root,{'link':sha256(b'test')})

    def test_parent_seal_and_report_seal_are_verified(self):
        path,m=self.detached();self.m['new']='change';self.save()
        with self.assertRaisesRegex(ValueError,'INPUT_HASH_MISMATCH: manifest.json'):
            verify_review_bundle(self.root,manifest_path=path)

    def test_duplicate_json_keys_invalid_hashes_and_bool_version_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE_JSON_KEY'):
            decode(b'{"a":1,"a":2}')
        with self.assertRaisesRegex(ValueError,'INVALID_SHA256'):
            checked_files(self.root,{'case.json':'abc'})
        self.m['schema_version']=True;self.save()
        with self.assertRaisesRegex(ValueError,'REVIEW_MANIFEST_INVALID'):
            verify_review_bundle(self.root)

    def test_declared_archive_hashes_cannot_be_discarded_during_derivation(self):
        (self.root/'report.md').write_text('original')
        self.m['files']['report.md']=sha256((self.root/'report.md').read_bytes());self.save()
        (self.root/'report.md').write_text('changed')
        with self.assertRaisesRegex(ValueError,'INPUT_HASH_MISMATCH'):
            derive_manifest(self.root)
