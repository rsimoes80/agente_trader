import copy
import unittest
from unittest.mock import patch
from aurelia_fx.literature_basis import basis_blocker, references_hash, STAGES
from aurelia_fx.literature_learning import validate_techniques
from aurelia_fx.literature_blueprint import validate_blueprint
from aurelia_fx.entry_trend import entry_blocker


class LiteratureGroundingTests(unittest.TestCase):
    def setUp(self):
        self.text = 'A correção precisa preservar a estrutura da tendência antes de uma entrada.'
        self.source = {'document': 'fixture.pdf', 'sha256': 'a'*64}
        self.page = {'page': 3, 'text': self.text, 'text_sha256': 'b'*64, 'method': 'native'}
        self.item = dict(name='Estrutura', kind='context', summary='Preservar estrutura.',
                         quote=self.text, scope='Texto de teste', conditions=[], invalidations=[], numeric_rules=[])

    def test_literal_source_is_not_execution_authority(self):
        card = validate_techniques({'techniques':[self.item]}, self.source, self.page)[0]
        self.assertTrue(card['source_quote_verified'])
        self.assertFalse(card['trading_authority'])
        self.assertFalse(card['semantic_entailment_reviewed'])

    def test_fabricated_quote_number_and_authority_rejected(self):
        for updates in ({'quote':'Esta frase suficientemente longa não existe no original.'},
                        {'numeric_rules':[{'value':21,'quote':self.text}]},
                        {'trading_authority':True}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                validate_techniques({'techniques':[{**self.item, **updates}]},self.source,self.page)

    def fixture_approval(self):
        refs=[dict(stage=s,card_id='card',source_sha256='a'*64,page_text_sha256='b'*64,pdf_page=3) for s in sorted(STAGES)]
        approval={'plans':{'plan':{'status':'approved_for_demo','validation_report_id':'report',
                                   'reference_sha256':references_hash(refs)}},
                  'cards':{'card':dict(status='approved_for_demo',semantic_entailment_reviewed=True,
                                      allowed_stages=list(STAGES),source_sha256='a'*64,page_text_sha256='b'*64,pdf_page=3)}}
        return {'plan_id':'plan','references':refs},approval

    def test_complete_reviewed_basis_and_tampering(self):
        basis,approval=self.fixture_approval()
        self.assertIsNone(basis_blocker(basis,approval))
        for field,value in [('source_sha256','c'*64),('page_text_sha256','c'*64),('pdf_page',4)]:
            changed=copy.deepcopy(basis);changed['references'][0][field]=value
            self.assertEqual(basis_blocker(changed,approval),'LITERATURE_SOURCE_MISMATCH')
        basis['references'].pop()
        self.assertEqual(basis_blocker(basis,approval),'LITERATURE_STAGE_MISSING')

    def test_unreviewed_card_cannot_be_promoted_by_plan(self):
        basis,approval=self.fixture_approval()
        approval['cards']['card']['semantic_entailment_reviewed']=False
        self.assertEqual(basis_blocker(basis,approval),'LITERATURE_RULE_NOT_APPROVED')

    def test_legacy_learning_cannot_rewrite_book_plan(self):
        from aurelia_fx.continual_learning import apply
        with self.assertRaisesRegex(ValueError,'LITERATURE_PLAN_REQUIRES_SEPARATE_LEARNING'):
            apply({'snapshot':{'literature_basis':{'plan_id':'reviewed-plan'}}},'target_3r')

    def test_guard_blocks_legacy_snapshot(self):
        with patch.dict('os.environ',{'AURELIA_REQUIRE_LITERATURE':'1'}):
            self.assertEqual(entry_blocker({'regime':'TREND'}),'LITERATURE_BASIS_REQUIRED')

    def test_blueprint_requires_sources_and_rejects_countertrend(self):
        card=validate_techniques({'techniques':[self.item]},self.source,self.page)[0]
        plan=dict(family='pullback_in_trend',direction_policy='confirmed_h1_only',
                  **{s:[{'description':'Hipótese de teste','card_ids':[card['card_id']]}] for s in STAGES})
        self.assertFalse(validate_blueprint(plan,[card])['trading_authority'])
        for update in ({'direction_policy':'any'},{'trigger':[]},
                       {'numeric_parameters':[{'value':21,'card_id':card['card_id']}]}):
            with self.subTest(update=update),self.assertRaises(ValueError):validate_blueprint({**plan,**update},[card])
