"""Persistent online strategy research, isolated counterfactuals and gated adaptation.

All mutation belongs to the account checkpoint transaction. No broker imports.
"""
import copy
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
import json,math

from .agent_model import fingerprint
from .agent_research import simulator,request_for,SESSIONS
from .domain import Candidate,Candle
from .execution_simulator import EntryRequest,Position
from .historical.core import utc
from .sessions import SessionEngine
from .broker_calendar import unexpected_broker_gap
from .entry_trend import entry_blocker
from . import hypothesis_review

VERSION='continual-context-v1'
VARIANTS={
    'baseline':dict(name='Pullback atual · alvo 2,5R',arm='context_pullback',reward=2.5,filter='none'),
    'target_3r':dict(name='Pullback · alvo 3R',arm='context_pullback',reward=3.,filter='none'),
    'target_35r':dict(name='Pullback · alvo 3,5R',arm='context_pullback',reward=3.5,filter='none'),
    'forecast':dict(name='Pullback · confirmação Timestral',arm='forecast_pullback',reward=2.5,filter='forecast'),
    'body_3r':dict(name='Candle forte · alvo 3R',arm='price_action_pullback',reward=3.,filter='body'),
}
SPEC=dict(version=VERSION,variants=VARIANTS,min_days=7,min_trades=20,min_context_trades=8,
    online_half_life_trades=20,rollback_after=10,rollback_mean_r=-.25,
    model_rollback_after=20,model_rollback_loss_fraction=.7,reward_clip_r=3,
    scope='prospective costed shadow portfolios, real outcomes separate',
    risk='existing limits unchanged; H4/H1 trend mandatory',auto_promote=True)
SPEC_HASH=fingerprint(SPEC)

def initialize(lab,at,units):
    old=lab.get('continual')
    if old and old.get('spec_hash')==SPEC_HASH and old.get('units')==units:return old
    state=dict(version=VERSION,spec_hash=SPEC_HASH,units=units,registered_at=utc(at).isoformat(),
        last_bar=None,last_signal=None,observations=0,eligible_signals=0,champion='baseline',
        contexts={},portfolios={},outcomes=[],changes=[],real={},excluded_legacy=0,
        evidence_status='COLLECTING',last_change=None)
    if old:state['previous_version']=dict(version=old.get('version'),last_bar=old.get('last_bar'))
    if old and old.get('version')==VERSION:
        state['real']=copy.deepcopy(old.get('real',{}));state['contexts']=copy.deepcopy(old.get('contexts',{}))
        for key in ('suspended','recent_real','model_rollback_request','last_real_result'):
            if key in old:state[key]=copy.deepcopy(old[key])
    lab['continual']=state
    return state

def context(setup):
    s=setup['snapshot'];vol=setup['atr']/1e-4
    return '|'.join((VERSION,setup.get('learning_source','unversioned'),setup.get('learning_model','unversioned'),s.get('regime_config_hash','unknown'),s['regime'],
        setup['candidate'].side,'+'.join(sorted(s.get('session',[]))),
        'vol:'+('low' if vol<3 else 'medium' if vol<8 else 'high')))

def accepts(variant,features):
    rule=VARIANTS[variant]['filter']
    return (rule!='forecast' or all(features.get('forecast_'+str(h)+'_atr',-1)>0 for h in (3,6))) and (rule!='body' or features.get('body_atr',0)>=.5)

def apply(setup,variant):
    if variant not in VARIANTS:raise ValueError('Unknown strategy variant')
    original=setup['candidate'];blocker=entry_blocker(setup['snapshot'],original.side)
    if blocker:raise ValueError(blocker)
    result={**setup};sign=1 if original.side=='long' else -1
    target=original.entry+sign*abs(original.entry-original.stop)*VARIANTS[variant]['reward']
    result['candidate']=Candidate(original.side,original.entry,original.stop,target,original.expires_at,original.evidence,original.contradictions)
    return result

def encode_sim(sim):
    data={k:getattr(sim,k) for k in ('balance','peak_equity','daily_start','day','daily_entries','account_locked')}
    data['request']=asdict(sim.request) if sim.request else None
    data['position']=asdict(sim.position) if sim.position else None
    data['equity_curve']=sim.equity_curve[-1:]
    return json.loads(json.dumps(data,default=lambda v:v.isoformat()))

def decode_request(d):
    d=copy.deepcopy(d);candidate=d.pop('candidate');candidate['expires_at']=utc(candidate['expires_at'])
    d['submitted_at']=utc(d['submitted_at'])
    return EntryRequest(candidate=Candidate(**candidate),**d)

def decode_sim(data,units):
    sim=simulator(units)
    if not data:return sim
    for k in ('balance','peak_equity','daily_start','day','daily_entries','account_locked','equity_curve'):
        setattr(sim,k,copy.deepcopy(data[k]))
    sim.request=decode_request(data['request']) if data.get('request') else None
    if data.get('position'):
        p=copy.deepcopy(data['position']);p['request']=decode_request(p['request']);p['entry_at']=utc(p['entry_at'])
        sim.position=Position(**p)
    return sim

def add_stats(cell,pnl,reward):
    if not all(math.isfinite(v) for v in (pnl,reward)):raise ValueError('Invalid learning reward')
    reward=max(-3.,min(3.,reward));decay=2**(-1/20)
    cell['n']=cell.get('n',0)+1;cell['net_pnl']=cell.get('net_pnl',0)+pnl
    cell['wins']=cell.get('wins',0)+int(pnl>0);cell['losses']=cell.get('losses',0)+int(pnl<0)
    cell['sum_r']=cell.get('sum_r',0)+reward;cell['sum_sq_r']=cell.get('sum_sq_r',0)+reward*reward
    cell['weight']=cell.get('weight',0)*decay+1;cell['weighted_r']=cell.get('weighted_r',0)*decay+reward
    cell['recent_mean_r']=cell['weighted_r']/cell['weight']

def real_result(lab,hypothesis,pnl,reward):
    state=lab.get('continual')
    if not state:return
    if hypothesis.get('learning_version')!=VERSION or hypothesis.get('learning_spec_hash')!=SPEC_HASH:
        state['excluded_legacy']+=1;return
    key=hypothesis['learning_context'];variant=hypothesis['variant_id']
    if variant not in VARIANTS:raise ValueError('Unrecognized result variant')
    cell=state['real'].setdefault(key,{}).setdefault(variant,{})
    add_stats(cell,pnl,reward)
    state['last_real_result']=dict(context=key,variant=variant,net_pnl=pnl,result_in_r=reward)
    model=hypothesis.get('model_configuration')
    state['recent_real']=(state.get('recent_real',[])+[dict(model=model,reward=reward,net_pnl=pnl)])[-100:]
    recent=[r for r in state['recent_real'] if model and r['model']==model][-20:]
    if len(recent)>=20 and sum(r['reward'] for r in recent)/20<-.25 and sum(r['net_pnl']<0 for r in recent)/20>.7:
        state['model_rollback_request']=dict(model_configuration=model,reason='RECENT_MODEL_RESULTS_DETERIORATED',samples=20)
    if cell['n']>=10 and cell['recent_mean_r']<-.25:
        state.setdefault('suspended',{})[key]=dict(variant=variant,reason='RECENT_NET_REWARD_NEGATIVE',n=cell['n'])

def promote(state,at):
    if utc(at)-utc(state['registered_at'])<timedelta(days=7):return
    # Same opportunity stream and costed one-position portfolios, evaluated by day.
    outcomes=state['outcomes'];base=[o for o in outcomes if o['variant']=='baseline']
    candidates=[]
    for variant in VARIANTS:
        if variant=='baseline':continue
        rows=[o for o in outcomes if o['variant']==variant]
        if min(len(base),len(rows))<20:continue
        days=sorted({o['exit_at'][:10] for o in rows+base})
        if len(days)<7:continue
        differences=[sum(o['net_pnl'] for o in rows if o['exit_at'].startswith(d))-sum(o['net_pnl'] for o in base if o['exit_at'].startswith(d)) for d in days]
        mean=sum(differences)/len(days)
        variance=sum((v-mean)**2 for v in differences)/(len(days)-1)
        lower=mean-2.58*math.sqrt(variance/len(days))  # Conservative daily comparison, finite catalog.
        net=sum(o['net_pnl'] for o in rows)
        def drawdown(items):
            equity=peak=10000.;worst=0.
            for o in items:
                equity+=o['net_pnl'];peak=max(peak,equity);worst=max(worst,peak-equity)
            return worst
        if net>0 and lower>0 and drawdown(rows)<=drawdown(base):candidates.append((net,variant))
    chosen=max(candidates)[1] if candidates else 'baseline'
    if chosen!=state['champion']:
        change=dict(at=utc(at).isoformat(),previous=state['champion'],selected=chosen,
            reason='PROSPECTIVE_COSTED_PORTFOLIO_EVIDENCE' if chosen!='baseline' else 'EVIDENCE_NO_LONGER_SUPPORTS_VARIANT',observations=state['observations'])
        state['changes']=(state['changes']+[change])[-30:];state['last_change']=change;state['champion']=chosen
    state['evidence_status']='VALIDATED_ALTERNATIVE' if chosen!='baseline' else 'COLLECTING'

def advance(lab,rows,at):
    state=lab['continual'];events=[];sessions=SessionEngine(SESSIONS)
    portfolios={k:decode_sim(state['portfolios'].get(k),state['units']) for k in VARIANTS}
    for row in rows:
        bar=row if isinstance(row,Candle) else Candle(utc(row['timestamp']),*[row[k] for k in ('open','high','low','close')],row.get('volume',0),row.get('spread_pips'))
        if bar.timestamp+timedelta(seconds=300)>utc(at):continue
        if state['last_bar'] and bar.timestamp<=utc(state['last_bar']):continue
        if bar.timestamp+timedelta(seconds=300)<=utc(state['registered_at']):continue
        previous=state.get('last_bar');valid=True
        if previous:
            # Calendar gaps are allowed; unexpected missing exposure bars are not.
            prior=Candle(utc(previous),bar.open,bar.open,bar.open,bar.open)
            valid=not unexpected_broker_gap(prior,bar,300)
        hypothesis_review.advance_portfolios(state,bar,valid,sessions.identify(bar.timestamp).active_sessions)
        for variant,sim in portfolios.items():
            fresh=sim.advance(bar,data_valid=valid,active_sessions=sessions.identify(bar.timestamp).active_sessions)
            for event in fresh:
                if event['status']=='closed':
                    f=event['financial_result'];key=event['intelligence_context']['learning_context']
                    result=dict(variant=variant,context=key,entry_at=event['entry_at'],exit_at=event['observed_at'],
                        net_pnl=f['net_pnl'],result_in_r=f['result_in_r'],scope='prospective_shadow_not_broker',event_id=event['event_id'])
                    state['outcomes'].append(result)
                    hypothesis_review.review(state,event,result)
                    add_stats(state['contexts'].setdefault(key,{}).setdefault(variant,{}),f['net_pnl'],f['result_in_r'])
                    events.append(result)
                elif event['status']=='censored':
                    research=hypothesis_review.state_for(state)
                    research['censored']+=1
                    if research['proposal'] and research['proposal']['status']=='COLLECTING_FUTURE':
                        research['proposal']['status']='INVALIDATED_DATA_GAP'
                    research['reviews']=[]
                    state['censored']=state.get('censored',0)+1
                    state['registered_at']=(bar.timestamp+timedelta(seconds=300)).isoformat()
                    state['outcomes']=[];state['champion']='baseline';state['evidence_status']='RESTARTED_AFTER_DATA_GAP'
                    events.append(dict(scope='excluded_unreliable_exposure',variant=variant,at=event['observed_at']))
            sim.events.clear()
        if any(s.account_locked for s in portfolios.values()):portfolios={k:simulator(state['units']) for k in VARIANTS}
        state['last_bar']=bar.timestamp.isoformat();state['observations']+=1
    cutoff=(utc(at)-timedelta(days=90)).isoformat()
    state['outcomes']=[o for o in state['outcomes'] if o['exit_at']>=cutoff][-2000:]
    state['portfolios']={k:encode_sim(s) for k,s in portfolios.items()}
    promote(state,at)
    hypothesis_review.evaluate(state,at)
    return events

def consider(lab,setup,features):
    state=lab['continual'];signal=setup['signal_at']
    if utc(signal)<=utc(state['registered_at']) or signal==state['last_signal']:return
    if entry_blocker(setup['snapshot'],setup['candidate'].side):return
    state['last_signal']=signal;state['eligible_signals']+=1;key=context(setup)
    hypothesis_review.consider_portfolios(state,setup,features,key)
    for variant in VARIANTS:
        sim=decode_sim(state['portfolios'].get(variant),state['units'])
        if not sim.busy and not sim.account_locked and accepts(variant,features):
            modified=apply(setup,variant);modified['snapshot']={**setup['snapshot'],'learning_context':key,
                'hypothesis_critique':hypothesis_review.critique(setup,features)}
            sim.submit(request_for(modified,fingerprint(dict(study=state['registered_at'],signal=signal,variant=variant))))
        state['portfolios'][variant]=encode_sim(sim)

def choose(lab,setup,features,protocol_id):
    state=lab['continual'];key=context(setup);variant=state['champion']
    # A global winner also needs positive evidence in the current comparable context.
    local=state['contexts'].get(key,{}).get(variant,{})
    if variant!='baseline' and (local.get('n',0)<8 or local.get('recent_mean_r',0)<=0):variant='baseline'
    suspension=state.get('suspended',{}).get(key)
    if suspension and suspension['variant']==variant:
        # Keep researching in shadow; recovery needs eight fresh context outcomes after suspension.
        shadow=state['contexts'].get(key,{}).get(variant,{})
        if shadow.get('n',0)<suspension.get('shadow_n',shadow.get('n',0))+8 or shadow.get('recent_mean_r',0)<=0:
            suspension.setdefault('shadow_n',shadow.get('n',0))
            return dict(wait=True,reason='LEARNED_CONTEXT_SUSPENDED',variant_id=variant)
        state['suspended'].pop(key,None)
    if not accepts(variant,features):return dict(wait=True,reason='LEARNED_VARIANT_FILTER_WAIT',variant_id=variant)
    spec=VARIANTS[variant]
    return dict(id=spec['arm'],name=spec['name'],context=key,protocol_id=protocol_id,
        variant_id=variant,learning_version=VERSION,learning_spec_hash=SPEC_HASH,learning_context=key,
        model_configuration=setup.get('learning_model'),
        reason='Alternativa validada neste contexto.' if variant!='baseline' else 'Estrategia base enquanto alternativas acumulam evidencia.',
        selection_score=local.get('recent_mean_r',0),wait=False)

def summary(lab):
    state=lab.get('continual')
    if not state:return None
    variants=[]
    for key,spec in VARIANTS.items():
        rows=[o for o in state['outcomes'] if o['variant']==key]
        variants.append(dict(id=key,name=spec['name'],closed=len(rows),wins=sum(o['net_pnl']>0 for o in rows),
            net_pnl=sum(o['net_pnl'] for o in rows),active=key==state['champion']))
    study=lab.get('model_study') or {}
    return dict(version=VERSION,automatic=True,registered_at=state['registered_at'],observations=state['observations'],
        eligible_signals=state['eligible_signals'],evidence_status=state['evidence_status'],champion=state['champion'],
        champion_name=VARIANTS[state['champion']]['name'],variants=variants,real_results=sum(v.get('n',0) for cell in state['real'].values() for v in cell.values()),
        last_result=state.get('last_real_result'),last_change=state['last_change'],changes=state['changes'][-5:],
        min_days=7,min_trades=20,censored=state.get('censored',0),suspended_contexts=len(state.get('suspended',{})),
        hypothesis_review=hypothesis_review.summary(state),
        model_study={k:study.get(k) for k in ('run_id','registered_at','forecast_count','status','closed','error')} if study else None)
