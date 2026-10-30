import hashlib,json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from aurelia_fx.book_specialists import market_case
from aurelia_fx.egm_review import prepare,verify,PAGES,CODE


class ReviewBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        pdf=self.root/'Aprendizado/EBOOK-MANUAL-DO-PULLBACK.pdf';pdf.parent.mkdir();pdf.write_bytes(b'synthetic-pdf-fixture')
        cache=self.root/'data/references_cache/learning-library';cache.mkdir(parents=True)
        source=dict(document=pdf.name,sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),cache=str(cache.relative_to(self.root)))
        (cache/'inventory.json').write_text(json.dumps([source]))
        for number in PAGES:
            text='Synthetic page '+str(number)
            (cache/f'{number:04d}.json').write_text(json.dumps(dict(text=text,text_sha256=hashlib.sha256(text.encode()).hexdigest(),method='native')))
        code=self.root/'src/aurelia_fx';code.mkdir(parents=True)
        for name in CODE:(code/name).write_text('# synthetic snapshot\n')
        self.case=market_case(dict(symbol='EURUSD',timestamp_utc='2026-10-30T10:05:00+00:00',
                                  context_trend=dict(direction='bullish',state='BULL_CONFIRMED')),
                              [dict(timestamp='2026-10-30T10:00:00+00:00',open=1.,high=1.2,low=.9,close=1.1)])

    def test_frozen_inputs_remain_valid_after_live_code_changes(self):
        folder=prepare(self.root,self.case)
        (self.root/'src/aurelia_fx/agent_strategy.py').write_text('# changed live file\n')
        manifest=verify(folder)
        self.assertEqual(manifest['case_id'],self.case['case_id'])
        self.assertFalse(manifest['trading_authority'])
        self.assertEqual((folder/'code_agent_strategy.py.txt').read_text(),'# synthetic snapshot\n')

    def test_case_tampering_is_detected(self):
        folder=prepare(self.root,self.case);path=folder/'case.json'
        payload=json.loads(path.read_text());payload['as_of']='2026-10-31T10:05:00+00:00';path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError,'REVIEW_INPUT_CHANGED'):verify(folder)

    def test_omitted_hash_entries_cannot_report_verified(self):
        folder=prepare(self.root,self.case);path=folder/'manifest.json'
        payload=json.loads(path.read_text());payload['files']={};path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError,'REVIEW_MANIFEST_INVALID'):verify(folder)

    def test_changed_pdf_or_extracted_text_is_rejected(self):
        pdf=self.root/'Aprendizado/EBOOK-MANUAL-DO-PULLBACK.pdf';original=pdf.read_bytes();pdf.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'REVIEW_PDF_CHANGED'):prepare(self.root,self.case)
        pdf.write_bytes(original)
        page=self.root/f'data/references_cache/learning-library/{PAGES[0]:04d}.json'
        payload=json.loads(page.read_text());payload['text']='changed';page.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError,'REVIEW_PAGE_CHANGED'):prepare(self.root,self.case)
