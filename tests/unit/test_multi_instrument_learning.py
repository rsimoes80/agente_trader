"""Synthetic parallel learning paths; never send orders or claim an edge."""
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from types import SimpleNamespace
import unittest

from aurelia_fx import continual_learning as cl, exploratory_learning as el, hypothesis_review as hr
from aurelia_fx.domain import Candle, Candidate
from .test_instrument_research import profile


class MultiInstrumentLearningTests(unittest.TestCase):
    def setUp(self):
        self.at=datetime(2026,10,19,13,tzinfo=timezone.utc)
        gold=profile()
        euro=replace(profile('EURUSD'),
            contract=replace(gold.contract,symbol='EURUSD',digits=5,point=.00001,tick_size=.00001,
                             contract_size=100000.,calculation_mode=0),
            price_unit=.0001,max_spread_units=2.,value_per_price_per_lot=100000.,
            costs=replace(gold.costs,commission_per_lot_side=3.5,slippage_price=.00002))
        self.profiles={'XAUUSD':gold,'EURUSD':euro}
        self.labs={symbol:{} for symbol in self.profiles}
        for symbol,p in self.profiles.items():
            cl.initialize(self.labs[symbol],self.at-timedelta(minutes=10),'.01',profile=p)

    def setup(self,symbol,*,regime='TREND',at=None):
        p=self.profiles[symbol];at=at or self.at
        price,distance=(4000.,10.) if symbol=='XAUUSD' else (1.1,.002)
        return dict(candidate=Candidate('long',price,price-distance,price+3*distance,
                    at+timedelta(minutes=10),('fixture',)),signal_at=at.isoformat(),
                    atr=distance,price_unit=p.price_unit,learning_namespace=p.learning_namespace,
                    volatility_bands_units=(3,8),learning_source='fixture-clock',learning_model='same-base-model',
                    snapshot=dict(snapshot_id='fixture',symbol=symbol,profile_id=p.fingerprint,
                    session=['london'],regime=regime,regime_config_hash='fixture',
                    macro_trend=dict(direction='bullish',state='BULL_CONFIRMED'),
                    context_trend=dict(direction='bullish',state='BULL_CONFIRMED')))

    def features(self):
        return dict(body_atr=.1,stop_atr=1.,spread_stop=.02,forecast_3_atr=.2,forecast_6_atr=.2)

    def bar(self,symbol,*,at=None,target=False):
        price,distance=(4000.,10.) if symbol=='XAUUSD' else (1.1,.002)
        return Candle(at or self.at,price,price+(3.1 if target else .1)*distance,
                      price-.1*distance,price,100.,20. if symbol=='XAUUSD' else 1.)

    def test_both_assets_close_at_own_scale_and_restart_without_duplicates(self):
        events={}
        for symbol,lab in self.labs.items():
            el.initialize(lab['continual'],self.at-timedelta(minutes=10))
            cl.consider(lab,self.setup(symbol),self.features())
            el.consider(lab['continual'],self.setup(symbol,regime='RANGE'),self.features())
            recovered=json.loads(json.dumps(lab))
            bars=[self.bar(symbol,target=True)];now=self.at+timedelta(minutes=5)
            events[symbol]=cl.advance(lab,bars,now)
            self.assertEqual(events[symbol],cl.advance(recovered,bars,now))
            self.assertEqual(lab,recovered)
            self.assertEqual(cl.advance(lab,bars,now),[])
            baseline=next(e for e in events[symbol] if e['variant']=='baseline')
            self.assertAlmostEqual(baseline['net_pnl'],24.72 if symbol=='XAUUSD' else 4.81)
            self.assertEqual(baseline['symbol'],symbol)
            state=lab['continual'];research=state['exploratory']
            self.assertEqual(research['closed'],1)
            self.assertEqual(research['hypothesis_review']['reviewed'],1)
            self.assertEqual(state['hypothesis_review']['reviewed'],1)
            self.assertEqual(cl.summary(lab)['symbol'],symbol)
            self.assertTrue(all(key.startswith(self.profiles[symbol].learning_namespace) for key in state['contexts']))
        self.assertFalse({r['event_id'] for r in events['EURUSD']} & {r['event_id'] for r in events['XAUUSD']})

    def test_foreign_signals_and_results_never_change_other_asset(self):
        gold=self.labs['XAUUSD'];before=copy.deepcopy(gold)
        for action in (lambda:cl.consider(gold,self.setup('EURUSD'),self.features()),
                       lambda:el.consider(gold['continual'],self.setup('EURUSD'),self.features()),
                       lambda:cl.choose(gold,self.setup('EURUSD'),self.features(),'fixture')):
            with self.assertRaisesRegex(ValueError,'INSTRUMENT_MISMATCH'):action()
            self.assertEqual(gold,before)
        h=cl.choose(self.labs['EURUSD'],self.setup('EURUSD'),self.features(),'fixture')
        with self.assertRaisesRegex(ValueError,'LEARNING_RESULT_INSTRUMENT_MISMATCH'):
            cl.real_result(gold,h,1.,1.)
        self.assertEqual(gold,before)

    def test_actual_results_update_only_the_correct_context(self):
        gold=self.labs['XAUUSD'];euro=copy.deepcopy(self.labs['EURUSD'])
        h=cl.choose(gold,self.setup('XAUUSD'),self.features(),'fixture')
        cl.real_result(gold,h,-1.,-1.)
        self.assertEqual(cl.summary(gold)['real_results'],1)
        self.assertEqual(self.labs['EURUSD'],euro)
        self.assertEqual(gold['continual']['champion'],'baseline')
        bad={**h,'learning_context':cl.context(self.setup('EURUSD'))}
        with self.assertRaisesRegex(ValueError,'LEARNING_RESULT_CONTEXT_MISMATCH'):
            cl.real_result(gold,bad,1.,1.)
        self.assertEqual(cl.summary(gold)['real_results'],1)

    def test_new_cost_or_contract_requires_a_new_learning_namespace(self):
        lab=self.labs['XAUUSD'];before=copy.deepcopy(lab)
        p=self.profiles['XAUUSD']
        changed=replace(p,costs=replace(p.costs,commission_per_lot_side=8))
        with self.assertRaisesRegex(ValueError,'PROFILE_CHANGE_REQUIRES_NEW_NAMESPACE'):
            cl.initialize(lab,self.at,'.01',profile=changed)
        self.assertEqual(lab,before)
        fresh={};cl.initialize(fresh,self.at,'.01',profile=changed)
        self.assertEqual(fresh['continual']['contexts'],{})
        self.assertNotEqual(fresh['continual']['spec_hash'],lab['continual']['spec_hash'])

    def test_lot_change_cannot_discard_queued_simulated_exposure(self):
        lab=self.labs['XAUUSD'];cl.consider(lab,self.setup('XAUUSD'),self.features())
        before=copy.deepcopy(lab)
        with self.assertRaisesRegex(ValueError,'EXPOSURES_MUST_BE_RECONCILED'):
            cl.initialize(lab,self.at,'.02',profile=self.profiles['XAUUSD'])
        self.assertEqual(lab,before)

    def test_gold_critique_uses_dollars_per_lot_not_euro_commission(self):
        p=self.profiles['XAUUSD'];s=self.setup('XAUUSD');features=self.features()
        facts=hr.critique(s,features,profile=p)
        # $0.20 spread + 2*$0.02 slippage + $6/100 price-value per lot.
        self.assertAlmostEqual(facts['cost_comparison']['estimated_round_trip_cost'],.30)
        self.assertEqual(facts['profile_id'],p.fingerprint)
        with self.assertRaisesRegex(ValueError,'CRITIQUE_INSTRUMENT_MISMATCH'):
            hr.critique(s,features)

    def test_calendar_pause_is_allowed_but_missing_open_slot_censors_exposure(self):
        p=self.profiles['XAUUSD'];lab=self.labs['XAUUSD']
        cl.consider(lab,self.setup('XAUUSD'),self.features())
        cl.advance(lab,[self.bar('XAUUSD')],self.at+timedelta(minutes=5))
        later=self.at+timedelta(minutes=15)
        result=cl.advance(lab,[self.bar('XAUUSD',at=later)],later+timedelta(minutes=5))
        self.assertTrue(any(e['scope']=='excluded_unreliable_exposure' for e in result))
        self.assertEqual(lab['continual']['outcomes'],[])
        for checkpoint in lab['continual']['portfolios'].values():
            self.assertEqual(checkpoint['instrument_context']['profile_id'],p.fingerprint)

    def test_sessions_are_explicit_and_part_of_the_profile_identity(self):
        p=self.profiles['XAUUSD']
        changed=replace(p,sessions=tuple(replace(s,opens_minute=10*60) for s in p.sessions))
        self.assertNotEqual(changed.fingerprint,p.fingerprint)
        with self.assertRaisesRegex(ValueError,'RESEARCH_SESSIONS_REQUIRED'):
            cl.initialize({},self.at,'.01',profile=replace(p,sessions=()))

    def test_review_discovers_and_freezes_future_cohorts_per_instrument(self):
        proposals={}
        for symbol,lab in self.labs.items():
            state=lab['continual'];p=self.profiles[symbol];setup=self.setup(symbol)
            facts=hr.critique(setup,self.features(),profile=p)
            for i in range(20):
                signal=self.at+timedelta(hours=i)
                f={**facts,'signal_at':signal.isoformat()}
                event=dict(intelligence_context={**setup['snapshot'],'hypothesis_critique':f},
                           rule_compliance=True,financial_result=dict(net_pnl=-1.,gross_pnl=-.8,result_in_r=-1.))
                result=dict(variant='baseline',symbol=symbol,profile_id=p.fingerprint,
                    context=cl.context(setup),entry_at=signal.isoformat(),
                    exit_at=(signal+timedelta(minutes=5)).isoformat(),net_pnl=-1.,result_in_r=-1.,event_id=symbol+str(i))
                hr.review(state,event,result)
            proposal=state['hypothesis_review']['proposal'];proposals[symbol]=proposal
            self.assertEqual(proposal['symbol'],symbol)
            self.assertEqual(proposal['validation'],[])
            formed=hr.utc(proposal['formed_at'])
            future=self.setup(symbol,at=formed+timedelta(minutes=5))
            hr.consider_portfolios(state,future,self.features(),cl.context(setup))
            checkpoint=proposal['portfolios']['base']
            self.assertEqual(checkpoint['instrument_context']['profile_id'],p.fingerprint)
            self.assertIsNone(proposal['portfolios']['filtered']['request'])
            hr.evaluate(state,hr.utc(proposal['ends_at'])+timedelta(days=1))
            self.assertEqual(proposal['status'],'INSUFFICIENT_FUTURE_SAMPLE')
        self.assertNotEqual(proposals['EURUSD']['id'],proposals['XAUUSD']['id'])

    def test_checkpoint_cannot_hide_a_foreign_position_or_different_lot(self):
        lab=self.labs['XAUUSD'];p=self.profiles['XAUUSD']
        cl.consider(lab,self.setup('XAUUSD'),self.features())
        cl.advance(lab,[self.bar('XAUUSD')],self.at+timedelta(minutes=5))
        checkpoint=copy.deepcopy(lab['continual']['portfolios']['baseline'])
        checkpoint['position']['request']['intelligence_context']['symbol']='EURUSD'
        with self.assertRaisesRegex(ValueError,'SIMULATION_INSTRUMENT_MISMATCH'):
            cl.decode_sim(checkpoint,.01,profile=p)
        checkpoint=copy.deepcopy(lab['continual']['portfolios']['baseline'])
        checkpoint['position']['units']=1000
        with self.assertRaisesRegex(ValueError,'SIMULATION_CHECKPOINT_LOT_MISMATCH'):
            cl.decode_sim(checkpoint,.01,profile=p)

    def test_dataset_builder_runs_the_instrument_calendar_and_costed_benchmark(self):
        from aurelia_fx.agent_dataset import build_samples
        from aurelia_fx.instrument_research import ResearchSession
        records={}
        class Connection:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def execute(self,query,args):self.keys=args[0];return self
            def fetchall(self):
                return [dict(record_key=key,payload_json=json.dumps(records[('agent_forecast_cache',key)]))
                        for key in self.keys if ('agent_forecast_cache',key) in records]
        class Memory:
            pool=SimpleNamespace(connection=Connection)
            def record_project_data(self,kind,key,payload):records[kind,key]=copy.deepcopy(payload)
        class Adapter:
            def forecast_batch(self,values):return [dict(quantiles=[[3999.,4000.05,4001.]]*12) for row in values]
        p=replace(self.profiles['XAUUSD'],sessions=(ResearchSession('fixture','UTC',0,0),))
        start=self.at-timedelta(hours=1)
        rows=[dict(timestamp=(start+timedelta(minutes=5*i)).isoformat(),open=4000.,high=4001.,
                   low=3999.,close=4000.,volume=100.,spread_pips=20.,symbol='XAUUSD') for i in range(108)]
        baseline=dict(symbol='XAUUSD',as_of=(start+timedelta(hours=9)).isoformat(),
                      training_days=1,clock_id='fixture',baseline_id='fixture')
        kwargs=dict(baseline=baseline,lot='.01',contract=p.contract.as_dict(),
                    forecast_config=SimpleNamespace(context=64,min_context=64,fingerprint='fixture'),
                    adapter=Adapter(),progress=lambda **kw:None,check=lambda:None,profile=p)
        report,parts,_=build_samples(Memory(),rows,**kwargs)
        manifest=report['manifest']
        self.assertEqual(manifest['symbol'],'XAUUSD')
        self.assertEqual(manifest['profile_id'],p.fingerprint)
        self.assertIn((p.record_type('agent_training_dataset'),report['run_id']),records)
        self.assertNotIn(('agent_training_dataset',report['run_id']),records)
        samples=[v for (kind,key),v in records.items() if kind==p.record_type('agent_benchmark_sample')]
        self.assertGreater(len(samples),0)
        self.assertTrue(all(v['execution']['instrument']['quantity_unit']=='lots' for v in samples))
        self.assertTrue(all(v['execution']['financial_result']['commission']==.06 for v in samples))
        with self.assertRaisesRegex(ValueError,'TRAINING_DATASET_INSTRUMENT_MISMATCH'):
            build_samples(Memory(),rows,**{**kwargs,'baseline':{**baseline,'symbol':'EURUSD'}})


@unittest.skipUnless(os.environ.get('TIMESTRAL_TEST_POSTGRES')=='1','PostgreSQL opt-in')
class MultiInstrumentLearningStorageTests(unittest.TestCase):
    def setUp(self):
        from .test_operation_control import OperationPostgresTests
        self.fixture=OperationPostgresTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.memory=self.fixture.control.memory;self.c=self.fixture.c
        def record(kind,key,payload):
            text,digest=self.memory._encode(payload)
            self.c.execute('INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256) VALUES(%s,%s,%s,%s)',(kind,key,text,digest))
        self.memory.record_project_data=record
        self.research=MultiInstrumentLearningTests();self.research.setUp()

    def test_persistent_snapshots_restore_only_the_correct_instrument(self):
        from aurelia_fx.learning_storage import pack,hydrate
        packed={}
        for symbol,lab in self.research.labs.items():
            p=self.research.profiles[symbol]
            account=dict(symbol=symbol,profile_id=p.fingerprint,lab_state=copy.deepcopy(lab))
            pack(self.memory,self.c,account);packed[symbol]=account
            self.assertNotIn('continual',account['lab_state'])
            self.assertEqual(hydrate(self.memory,copy.deepcopy(account))['lab_state'],lab)
        self.assertNotEqual(packed['EURUSD']['lab_state']['continual_ref'],packed['XAUUSD']['lab_state']['continual_ref'])
        bad=copy.deepcopy(packed['EURUSD'])
        bad['lab_state']['continual_ref']=packed['XAUUSD']['lab_state']['continual_ref']
        with self.assertRaisesRegex(ValueError,'PERSISTENT_LEARNING_INSTRUMENT_MISMATCH'):
            hydrate(self.memory,bad)

    def test_wrong_account_envelope_never_packs_gold_as_euro(self):
        from aurelia_fx.learning_storage import pack
        account=dict(lab_state=copy.deepcopy(self.research.labs['XAUUSD']))
        with self.assertRaisesRegex(ValueError,'PERSISTENT_LEARNING_INSTRUMENT_MISMATCH'):
            pack(self.memory,self.c,account)
        self.assertIn('continual',account['lab_state'])

    def test_historical_labels_and_priors_are_isolated_by_profile(self):
        from aurelia_fx.agent_dataset import label
        from aurelia_fx.agent_strategy import SPEC,strategy_spec
        from aurelia_fx.autonomous_lab import AutonomousLab,REGIME_HASH
        r=self.research;p=r.profiles['XAUUSD'];setup=r.setup('XAUUSD')
        setup['production_eligible']=True;setup['snapshot']['regime_config_hash']=REGIME_HASH
        features={**r.features(),'side':1,'h1_direction_known':1}
        sample,_=label(self.memory,setup,[r.bar('XAUUSD',target=True)],run_id='gold-fixture',
            experiment_hash='same-fixture',kind='technical',features=features,cache_id='fixture',units=.01,profile=p)
        self.assertAlmostEqual(sample['net_pnl'],29.72)
        now=r.at+timedelta(days=1)
        manifest=dict(clock_id='fixture',model_configuration='fixture',as_of=now.isoformat(),
                      boundaries=[now.isoformat()],training_days=30,strategy=SPEC)
        self.memory.record_project_data('agent_training_dataset','legacy',dict(run_id='legacy',manifest=manifest,sample_ids=[]))
        policy=AutonomousLab('fixture',profile=p)
        self.assertEqual(policy.seed(self.memory,clock_id='fixture',configuration='fixture',as_of=now)['historical_samples'],0)
        manifest={**manifest,'symbol':'XAUUSD','profile_id':p.fingerprint,'strategy':strategy_spec(p)}
        self.memory.record_project_data(p.record_type('agent_training_dataset'),'gold-fixture',
            dict(run_id='gold-fixture',manifest=manifest,sample_ids=[sample['sample_id']]))
        seeded=policy.seed(self.memory,clock_id='fixture',configuration='fixture',as_of=now)
        self.assertEqual(seeded['historical_samples'],1)
        self.assertTrue(all(k.startswith(p.learning_namespace) for k in seeded['history']))
        self.assertEqual(AutonomousLab('fixture').seed(self.memory,clock_id='fixture',configuration='fixture',as_of=now)['historical_samples'],0)
        self.memory.record_project_data(p.record_type('agent_training_sample'),sample['sample_id'],{**sample,'symbol':'EURUSD'})
        with self.assertRaisesRegex(ValueError,'SEED_SAMPLE_INSTRUMENT_MISMATCH'):
            policy.seed(self.memory,clock_id='fixture',configuration='fixture',as_of=now)


if __name__=='__main__':unittest.main()
