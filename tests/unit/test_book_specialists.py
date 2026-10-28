import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from aurelia_fx.book_profiles import PROFILES,BY_ID
from aurelia_fx.book_skills import build_skills,load_skill
from aurelia_fx.book_specialists import market_case,analyze,coordinate,validate_analysis
from aurelia_fx.literature_learning import validate_techniques


class BookSpecialistTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.text='Uma correção deve preservar a estrutura da tendência antes de uma nova entrada.'
        self.inventory=[];self.cards=[]
        for profile in PROFILES:
            folder=self.root/'knowledge_skills'/profile.id;folder.mkdir(parents=True)
            (folder/'SKILL.md').write_text('Use only source cards; research, no orders.')
            for document in profile.documents:
                pdf=self.root/'Aprendizado'/document;pdf.parent.mkdir(exist_ok=True);pdf.write_text(document)
                sha=hashlib.sha256(pdf.read_bytes()).hexdigest();cache=Path('data/references_cache/learning-library')/sha
                (self.root/cache).mkdir(parents=True)
                source=dict(document=document,sha256=sha,pages=1,cache=str(cache));self.inventory.append(source)
                page=dict(page=1,text=self.text,text_sha256=hashlib.sha256(self.text.encode()).hexdigest(),method='native')
                (self.root/cache/'0001.json').write_text(json.dumps(page))
                item=dict(name='Estrutura',kind='context',summary='Preservar estrutura.',quote=self.text,
                          scope='Synthetic fixture',conditions=[],invalidations=[],numeric_rules=[])
                self.cards.extend(validate_techniques({'techniques':[item]},source,page))
        (self.root/'data/references_cache/learning-library/inventory.json').write_text(json.dumps(self.inventory))
        self.snapshot=dict(timestamp_utc='2026-10-28T12:05:00+00:00',symbol='EURUSD',
                           context_trend=dict(direction='bullish',state='BULL_CONFIRMED'),regime='TREND')
        self.bars=[dict(timestamp='2026-10-28T12:00:00+00:00',open=1.1,high=1.2,low=1.,close=1.15,volume=30)]
        self.case=market_case(self.snapshot,self.bars)
        build_skills(self.cards,root=self.root)
        self.skill=load_skill(BY_ID['pullback'],root=self.root)
        self.finding=dict(stage='context',assessment='supports',explanation='Synthetic interpretation.',
                          card_ids=[self.skill['cards'][0]['card_id']],fact_ids=['system.regime'],
                          missing_conditions=[],invalidation='Structure breaks.')

    def test_shared_model_slot_is_exclusive_and_released_after_error(self):
        import fcntl
        from aurelia_fx.literature_model import model_slot
        path=self.root/'model.lock'
        with self.assertRaisesRegex(RuntimeError,'fixture'):
            with model_slot(path):
                with path.open('a') as other:
                    with self.assertRaises(BlockingIOError):fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
                raise RuntimeError('fixture')
        with path.open('a') as other:
            fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
            fcntl.flock(other,fcntl.LOCK_UN)

    def test_editorial_curation_checks_source_and_literal_anchor(self):
        from curate_book_skill import curate
        source=self.inventory[0]
        page=json.loads((self.root/source['cache']/'0001.json').read_text())
        item=dict(page=1,anchor='Uma correção',name='Structure',kind='context',summary='Structure matters.',conditions=[],invalidations=[])
        spec=dict(source_sha256=source['sha256'],scope='Synthetic fixture',techniques=[item])
        cards=curate(spec,source,{1:page})
        self.assertEqual(cards[0]['quote'],self.text)
        self.assertFalse(cards[0]['trading_authority'])
        with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):curate({**spec,'source_sha256':'x'},source,{1:page})
        spec['techniques']=[{**item,'anchor':'missing literal'}]
        with self.assertRaisesRegex(ValueError,'ANCHOR_MISSING'):curate(spec,source,{1:page})

    def test_eight_skills_and_single_douglas_work(self):
        manifests=build_skills(self.cards,root=self.root)
        self.assertEqual(len(manifests),8)
        douglas=next(m for m in manifests if m['specialist_id']=='douglas')
        self.assertEqual(len(douglas['documents']),2)
        self.assertTrue(all(not m['trading_authority'] and not m['semantic_review_complete'] for m in manifests))

    def test_mutated_pdf_or_card_rejected(self):
        document=self.root/'Aprendizado'/self.inventory[0]['document'];document.write_text('changed')
        with self.assertRaisesRegex(ValueError,'BOOK_SOURCE_CHANGED'):build_skills(self.cards,root=self.root)

    def test_modified_cached_text_rejected(self):
        page=self.root/self.inventory[0]['cache']/'0001.json'
        payload=json.loads(page.read_text());payload['text']='altered';page.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError,'CARD_PAGE_CHANGED'):build_skills(self.cards,root=self.root)

    def test_modified_skill_topic_rejected(self):
        topic=self.root/'data/references_cache/book-skills/pullback/references/context.json'
        topic.write_text('[]')
        with self.assertRaisesRegex(ValueError,'SKILL_REFERENCE_CHANGED'):load_skill(BY_ID['pullback'],root=self.root)

    def test_card_loading_has_explicit_budget(self):
        skill=load_skill(BY_ID['douglas'],root=self.root,max_cards=1)
        self.assertEqual(skill['loaded_card_count'],0) # context outside Douglas's kinds
        self.assertEqual(skill['available_card_count'],0)

    def test_open_candle_and_unsorted_history_rejected(self):
        with self.assertRaisesRegex(ValueError,'FUTURE_OR_OPEN_CANDLE'):
            market_case(self.snapshot,[{**self.bars[0],'timestamp':'2026-10-28T12:05:00+00:00'}])
        with self.assertRaisesRegex(ValueError,'CANDLES_NOT_ORDERED'):
            market_case(self.snapshot,self.bars+self.bars)

    def test_future_context_timestamp_is_rejected(self):
        changed=copy.deepcopy(self.snapshot)
        changed['context_trend']['timestamp_utc']='2026-10-28T13:00:00+00:00'
        with self.assertRaisesRegex(ValueError,'FUTURE_CONTEXT_FACT'):market_case(changed,self.bars)

    def test_unconfirmed_trend_does_not_call_model(self):
        case=market_case({**self.snapshot,'context_trend':{}},self.bars);model=Mock()
        self.assertEqual(analyze(self.skill,case,model=model)['status'],'unconfirmed_trend');model.assert_not_called()

    def test_valid_analysis_keeps_evidence_values_and_source(self):
        model=Mock(return_value={'findings':[self.finding]})
        result=analyze(self.skill,self.case,model=model)
        self.assertFalse(result['trading_authority'])
        self.assertEqual(result['findings'][0]['observed_facts'],{'system.regime':'TREND'})
        self.assertEqual(result['findings'][0]['sources'][0]['pdf_page'],1)
        self.assertFalse(result['findings'][0]['semantic_entailment_reviewed'])

    def test_contradictory_model_support_is_explicitly_downgraded_to_uncertain(self):
        output={'findings':[{**self.finding,'missing_conditions':['Volume traded unavailable']}]}
        original=copy.deepcopy(output)
        result=analyze(self.skill,self.case,model=Mock(return_value=output))
        self.assertEqual(output,original)
        self.assertEqual(result['findings'][0]['assessment'],'uncertain')
        self.assertEqual(result['consistency_adjustments'][0]['reason'],'MISSING_CONDITION_CANNOT_SUPPORT')
        self.assertEqual(result['consistency_adjustments'][0]['model_assessment'],'supports')
        council=coordinate(self.case,[result])
        self.assertIn('context',council['missing_stages'])
        self.assertFalse(council['trading_authority'])

    def test_invented_sources_facts_order_fields_and_missing_support_rejected(self):
        for update in ({'card_ids':['invented']},{'fact_ids':['future.price']},{'entry':1.123},
                       {'stage':'order'},{'missing_conditions':['Volume unavailable']}):
            with self.subTest(update=update),self.assertRaises(ValueError):
                validate_analysis({'findings':[{**self.finding,**update}]},self.skill,self.case)
        with self.assertRaises(ValueError):
            validate_analysis({'findings':[],'trading_authority':True},self.skill,self.case)

    def test_psychology_specialist_cannot_issue_price_trigger(self):
        skill=load_skill(BY_ID['douglas'],root=self.root)
        skill['cards']=self.skill['cards']
        with self.assertRaisesRegex(ValueError,'SPECIALIST_SCOPE_EXCEEDED'):
            validate_analysis({'findings':[{**self.finding,'stage':'trigger'}]},skill,self.case)

    def test_different_market_case_rejected(self):
        report=validate_analysis({'findings':[self.finding]},self.skill,self.case)
        report['case_id']='different'
        with self.assertRaisesRegex(ValueError,'CASE_OR_AUTHORITY'):coordinate(self.case,[report])

    def test_conflicts_preserved_and_never_vote_to_trade(self):
        first=validate_analysis({'findings':[self.finding]},self.skill,self.case)
        second={**first,'specialist_id':'pring','findings':[{**first['findings'][0],'assessment':'opposes'}]}
        result=coordinate(self.case,[first,second])
        self.assertEqual(result['conflicting_stages'],['context'])
        self.assertIn('trigger',result['missing_stages'])
        self.assertFalse(result['orders_enabled']);self.assertEqual(result['action'],'RESEARCH_ONLY')

    def test_even_complete_council_requires_review_and_replay(self):
        report=validate_analysis({'findings':[self.finding]},self.skill,self.case)
        report['findings']=[{**report['findings'][0],'stage':s} for s in ('context','region','trigger','invalidation','exit')]
        result=coordinate(self.case,[report])
        self.assertEqual(result['status'],'candidate_for_semantic_review')
        self.assertFalse(result['trading_authority']);self.assertTrue(result['requires_replay_validation'])

    def test_changed_case_and_duplicate_specialist_rejected(self):
        changed=copy.deepcopy(self.case);changed['side']='short'
        with self.assertRaisesRegex(ValueError,'CASE_CHANGED'):analyze(self.skill,changed,model=Mock())
        report=validate_analysis({'findings':[]},self.skill,self.case)
        with self.assertRaisesRegex(ValueError,'DUPLICATE_SPECIALIST'):coordinate(self.case,[report,report])
