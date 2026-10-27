"""Prospective model comparison using future candles and observed bid/ask portfolios.

Runs beside the live agent. It cannot send broker orders.
"""
import json,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import uuid4
from .repository import TrainingRepository
from .study_adapter import PairedStudyAdapter
from .metrics import forecast_metrics,forecast_gate,paired_day_interval
from aurelia_fx.agent_model import fingerprint
from aurelia_fx.agent_paper import PaperAccount
from aurelia_fx.agent_strategy import attach_forecast
from aurelia_fx.forecasting.config import ROOT
from aurelia_fx.historical.core import utc

class OnlineStudy:
    def __init__(self,memory,lab,contract,clock_id,*,profile=None):
        self.profile=profile;self.symbol=profile.symbol if profile else 'EURUSD'
        self.scope=dict(symbol=self.symbol,profile_id=profile.fingerprint if profile else None)
        self.memory=memory;self.lab=lab;self.contract={**contract,'symbol':self.symbol} if profile else contract
        self.repo=TrainingRepository(memory,self.symbol)
        self.clock_id=clock_id
        self.adapter=None;self.next_poll=0;self.run=None;self.cache={};self.accounts={}
    def close(self):
        if self.adapter:self.adapter.close()
        self.adapter=None
    def poll(self):
        if time.monotonic()<self.next_poll:return
        self.next_poll=time.monotonic()+60;state=self.repo.latest()
        if state['status']!='AWAITING_PROSPECTIVE':
            if self.lab.get('model_study',{}).get('run_id')==state.get('run_id'):self.lab['model_study']['status']=state['status']
            self.run=None;self.close();return
        if state.get('cancel_requested'):
            self.repo.finish_cancel(state['run_id']);self.run=None;self.close();return
        from aurelia_fx.forecasting.config import load_config
        from .scope import assert_same
        try:assert_same(state,self.scope)
        except ValueError:
            self.run=None;self.close();return
        active=load_config()
        if self.profile:
            from .releases import load_asset_config
            active=load_asset_config(active,self.profile)
        release=str(Path('data/training/releases')/state['run_id']/'release.json')
        if active.local_release==release:
            from .releases import resolve
            resolve(ROOT,release,active.local_artifact_sha256)
            self.repo.publish(state['run_id'],status='PROMOTED',stage='decision',release=release,
                decision=dict(approved=True,status='PROMOTED',reasons=[],live_model_changed=False),
                message='Promocao validada recuperada apos interrupcao de publicacao.')
            self.run=None;self.close();return
        self.run=state
        if state['dataset']['source_clock_id']!=self.clock_id:
            self.repo.publish(state['run_id'],status='NOT_APPROVED',stage='decision',message='Fonte mudou: comparação prospectiva não pode misturar relógios.')
            self.run=None;self.close();return
        if self.lab.get('model_study',{}).get('run_id')!=state['run_id']:
            self.close();self.cache={};self.accounts={}
            self.lab['model_study']=dict(run_id=state['run_id'],registered_at=state['study_protocol']['registered_at'],
                pending=[],last_forecast=None,aggregates={},day_losses={},accounts={},closed={},uncertain=0,
                forecast_count=0,status='OBSERVING',max_drawdown={},peak={})
        if self.adapter is None:self.adapter=PairedStudyAdapter(state['run_id'],scope=self.scope)
    def tick(self,quote,stop=False):
        self.poll()
        if not self.run:return
        d=self.lab['model_study'];rid=d['run_id']
        if utc(quote['at'])-utc(d['registered_at'])>timedelta(days=45):
            self.repo.publish(rid,status='NOT_APPROVED',stage='decision',message='Estudo futuro encerrado por evidencia insuficiente em 45 dias.')
            self.run=None;self.close();return
        for name in ('source','candidate','active'):
            if name not in self.accounts:
                self.accounts[name]=PaperAccount('model-study:'+rid+':'+name,'0.01',self.contract,rid,self.run['dataset']['source_clock_id'],
                    checkpoint=d['accounts'].get(name),research_mode=True,profile=self.profile)
            a=self.accounts[name];a.mark(quote,force_close='OPERATOR_PAUSE' if stop else None)
            equity=a.equity(quote);d['peak'][name]=max(d['peak'].get(name,10000.),equity)
            d['max_drawdown'][name]=max(d['max_drawdown'].get(name,0.),(d['peak'][name]-equity)/d['peak'][name]*100)
            for e in a.events:
                if e['status']=='closed':
                    d['closed'][name]=d['closed'].get(name,0)+int(not e['position']['coverage_uncertain'])
                    d['uncertain']+=int(e['position']['coverage_uncertain'])
                self.memory.record_project_data(self.repo.record_type('agent_model_study_trade'),e['event_id'],dict(**self.scope,run_id=rid,arm=name,event=e,orders_sent=0))
            a.events.clear();d['accounts'][name]=a.snapshot()
    def _read_prediction(self,key):
        if key in self.cache:return self.cache[key]
        with self.memory.pool.connection() as c:
            row=c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s AND record_key=%s LIMIT 1",(self.repo.record_type('agent_model_study_forecast'),key)).fetchone()
        p=json.loads(row['payload_json'])
        if self.memory._encode(p)[1]!=row['payload_sha256']:raise ValueError('Prospective prediction changed')
        from .scope import assert_same
        assert_same(p,self.scope)
        self.cache[key]=p;return p
    def observe(self,context,closed,quote,active_adapter,setup=None,quote_fetch=None):
        if not self.run:return
        import numpy as np
        d=self.lab['model_study'];last=context[-1].timestamp.isoformat()
        known={utc(r['timestamp']).isoformat():r for r in closed if utc(r['timestamp'])+timedelta(minutes=5)<=utc(quote['at'])}
        remaining=[]
        for key in d['pending']:
            p=self._read_prediction(key);reference=utc(p['reference'])
            stamps=[(reference+timedelta(minutes=5*(i+1))).isoformat() for i in range(12)]
            if not all(t in known for t in stamps):
                if utc(last)>reference+timedelta(hours=3):
                    d['excluded_forecasts']=d.get('excluded_forecasts',0)+1;self.cache.pop(key,None)
                else:remaining.append(key)
                continue
            target=np.array([[known[t]['close'] for t in stamps]]);ref=np.array([p['reference_close']])
            source_loss={}
            for name in ('source','candidate','active','candidate_common'):
                values=p['candidate'] if name=='candidate_common' else p[name]
                levels=p['levels'] if name in ('source','candidate') else [.1,.5,.9]
                if name=='candidate_common':values=np.asarray(values)[:,[p['levels'].index(q) for q in levels]]
                metrics,loss=forecast_metrics(np.asarray(values)[None],target,ref,levels,price_unit=self.profile.price_unit if self.profile else .0001)
                agg=d['aggregates'].setdefault(name,dict(windows=0,mean_pinball_pips=0.,horizons={}))
                n=agg['windows'];agg['windows']=n+1
                agg['mean_pinball_pips']=(agg['mean_pinball_pips']*n+metrics['mean_pinball_pips'])/(n+1)
                for h,vals in metrics['horizons'].items():
                    old=agg['horizons'].setdefault(h,{k:0. for k in vals})
                    for k,v in vals.items():old[k]=(old[k]*n+v)/(n+1)
                source_loss[name]=float(loss[0])
            day=reference.date().isoformat();cell=d['day_losses'].setdefault(day,dict(n=0,source=0.,candidate=0.,active=0.,candidate_common=0.))
            cell['n']+=1
            for name,v in source_loss.items():cell[name]+=v
            self.memory.record_project_data(self.repo.record_type('agent_model_study_score'),key,dict(**self.scope,run_id=d['run_id'],reference=p['reference'],loss=source_loss,day=day))
            self.cache.pop(key,None)
        d['pending']=remaining
        if last==d['last_forecast'] or utc(last)+timedelta(minutes=5)<=utc(d['registered_at']):return
        pair=self.adapter.forecast([c.close for c in context]);active=active_adapter.forecast([c.close for c in context])
        generated=datetime.now(timezone.utc)
        if generated>=utc(last)+timedelta(minutes=10):return  # First target already closed: discard, never relabel.
        artifact=active['artifact_sha256']
        if d.get('active_artifact') and d['active_artifact']!=artifact:
            self.repo.publish(d['run_id'],status='NOT_APPROVED',message='Modelo de referencia mudou durante o estudo.',stage='decision');return
        d['active_artifact']=artifact
        p=dict(**self.scope,run_id=d['run_id'],reference=last,reference_close=context[-1].close,
            generated_at=generated.isoformat(),input_hash=fingerprint([c.as_dict() for c in context]),
            levels=pair['levels'],source=pair['source'],candidate=pair['candidate'],active=active['quantiles'])
        key=fingerprint(dict(**self.scope,run_id=d['run_id'],reference=last));self.memory.record_project_data(self.repo.record_type('agent_model_study_forecast'),key,p)
        self.cache[key]=p;d['pending'].append(key);d['last_forecast']=last;d['forecast_count']+=1
        self.repo.publish(d['run_id'],study_summary=dict(forecasts=d['forecast_count'],evaluated=d['aggregates'].get('candidate',{}).get('windows',0),
            closed_trades=d['closed'],registered_at=d['registered_at'],status='OBSERVING',orders_sent=0))
        if setup:
            from aurelia_fx.agent_research import SESSIONS
            from aurelia_fx.sessions import SessionEngine
            if quote_fetch is None:raise ValueError('Prospective entry requires a fresh observed quote after inference')
            quote=quote_fetch()
            if (utc(quote['observed_at'])-utc(setup['signal_at'])).total_seconds()>90 or (utc(quote['observed_at'])-utc(quote['at'])).total_seconds()>5:return
            self.tick(quote)
            if not self.run:return
            for name in ('source','candidate','active'):
                a=self.accounts[name]
                if a.data['position']:continue
                values=np.asarray(p[name]);levels=p['levels'] if name!='active' else [.1,.5,.9]
                feature=attach_forecast(setup,dict(quantiles=values[:,[levels.index(q) for q in (.1,.5,.9)]].tolist()))
                if feature['forecast_3_atr']<=0 or feature['forecast_6_atr']<=0:continue
                hypothesis=dict(id='forecast_pullback',protocol_id=d['run_id'],context='prospective-model-study')
                a.open(setup,feature,None,quote,active_sessions=SessionEngine(self.profile.session_windows() if self.profile else SESSIONS).identify(utc(quote['at'])).active_sessions,hypothesis=hypothesis)
                d['accounts'][name]=a.snapshot()
        self.evaluate(quote)
    def evaluate(self,quote):
        d=self.lab['model_study'];days=(utc(quote['at'])-utc(d['registered_at'])).total_seconds()/86400
        if days<7 or d['aggregates'].get('candidate',{}).get('windows',0)<200:return
        if len(d['day_losses'])<20:return
        import numpy as np
        stamps=np.array([utc(day+'T00:00:00+00:00').timestamp() for day in sorted(d['day_losses'])])
        def interval(a,b):
            cells=[d['day_losses'][day] for day in sorted(d['day_losses'])]
            return paired_day_interval([c[a] for c in cells],[c[b] for c in cells],stamps)
        gate=forecast_gate(d['aggregates']['source'],d['aggregates']['candidate'],interval('source','candidate'))
        active_gate=forecast_gate(d['aggregates']['active'],d['aggregates']['candidate_common'],interval('active','candidate_common'))
        counts=[d['closed'].get(k,0) for k in ('source','candidate','active')]
        if min(counts)<20:return
        if any(a.data['position'] for a in self.accounts.values()):return
        accounts=d['accounts'];profits={k:accounts[k]['balance']-10000 for k in accounts}
        passed=gate['passed'] and active_gate['passed'] and not d['uncertain'] and profits['candidate']>max(0,profits['source'],profits['active']) and d['max_drawdown']['candidate']<=min(d['max_drawdown']['source'],d['max_drawdown']['active'])
        report=dict(**self.scope,gate=dict(passed=passed),days=days,closed_trades_per_arm=counts,
            candidate_sha256=self.run['forecast_report']['selection']['candidate_sha256'],protocol_id=self.run['protocol_id'],
            independent_future_data=True,forecast_gate=gate,active_model_gate=active_gate,profits=profits,
            registered_at=d['registered_at'],orders_sent=0,uncertain_trades=d['uncertain'],
            distinct_days=len(d['day_losses']),evaluated_windows=d['aggregates']['candidate']['windows'])
        from .releases import atomic_json,activate
        folder=ROOT/'data/training/runs'/d['run_id'];atomic_json(folder/'prospective-report.json',report)
        if passed:
            release=activate(ROOT,d['run_id'])
            self.repo.publish(d['run_id'],status='PROMOTED',stage='decision',prospective_report=report,
                decision=dict(approved=True,status='PROMOTED',reasons=[],live_model_changed=False),
                release=release,message='Candidato validado automaticamente; troca na proxima oportunidade sem exposicao.')
        else:self.repo.publish(d['run_id'],status='NOT_APPROVED',stage='decision',prospective_report=report,message='Candidato nao superou o estudo futuro.')
        d['status']='PROMOTED' if passed else 'NOT_APPROVED'
        self.close();self.run=None
