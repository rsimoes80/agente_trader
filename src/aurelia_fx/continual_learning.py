"""Persistent online strategy research, isolated counterfactuals and gated adaptation.

All mutation belongs to the account checkpoint transaction. No broker imports.
"""
import copy
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
import json,math

from .agent_model import fingerprint
from .agent_research import simulator,request_for,SESSIONS,simulation_window
from .domain import Candidate,Candle
from .execution_simulator import EntryRequest,Position
from .historical.core import utc
from .sessions import SessionEngine
from .broker_calendar import unexpected_broker_gap
from .entry_trend import entry_blocker, POLICY_ID, STRICT_POLICY_ID
from . import hypothesis_review, exploratory_learning

VERSION='continual-context-v1' if POLICY_ID == STRICT_POLICY_ID else 'continual-context-v2-'+POLICY_ID
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
    risk=('existing limits unchanged; H4/H1 trend mandatory' if POLICY_ID == STRICT_POLICY_ID else
          'existing limits unchanged; confirmed H1 and matching side mandatory'),auto_promote=True)
SPEC_HASH=fingerprint(SPEC)

def profile_for(state):
    from .instrument_research import InstrumentResearchProfile
    data=state.get('research_profile')
    if not data:
        if state.get('profile_id') or state.get('symbol','EURUSD')!='EURUSD':
            raise ValueError('LEARNING_PROFILE_REQUIRED')
        return None
    profile=InstrumentResearchProfile.from_dict(data)
    if state.get('profile_id')!=profile.fingerprint or state.get('symbol')!=profile.symbol:
        raise ValueError('LEARNING_PROFILE_INTEGRITY_ERROR')
    return profile


def spec_for(profile):
    return fingerprint(dict(base=SPEC_HASH,profile=profile.fingerprint)) if profile else SPEC_HASH


def initialize(lab,at,units,*,profile=None):
    if profile:
        units=profile.execution_config(units).fixed_units
        profile.session_windows()
    spec_hash=spec_for(profile)
    old=lab.get('continual')
    if old:
        old_profile=profile_for(old)
        if (old_profile.fingerprint if old_profile else None)!=(profile.fingerprint if profile else None):
            raise ValueError('LEARNING_PROFILE_CHANGE_REQUIRES_NEW_NAMESPACE')
    if lab and profile and (lab.get('symbol')!=profile.symbol or lab.get('profile_id')!=profile.fingerprint):
        raise ValueError('LEARNING_LAB_INSTRUMENT_MISMATCH')
    if not profile and lab.get('profile_id'):
        raise ValueError('LEARNING_LAB_INSTRUMENT_MISMATCH')
    if old and old.get('spec_hash')==spec_hash and old.get('units')==units:return old
    if old and profile:
        busy=any(p and (p.get('request') or p.get('position')) for p in old.get('portfolios',{}).values())
        exploratory=old.get('exploratory') or {}
        portfolios=[exploratory.get('portfolio')]
        for owner in (old,exploratory):
            portfolios.extend(((owner.get('hypothesis_review') or {}).get('proposal') or {}).get('portfolios',{}).values())
        if busy or any(p and (p.get('request') or p.get('position')) for p in portfolios):
            raise ValueError('LEARNING_EXPOSURES_MUST_BE_RECONCILED')
    state=dict(version=VERSION,spec_hash=spec_hash,units=units,registered_at=utc(at).isoformat(),
        last_bar=None,last_signal=None,observations=0,eligible_signals=0,champion='baseline',
        contexts={},portfolios={},outcomes=[],changes=[],real={},excluded_legacy=0,
        evidence_status='COLLECTING',last_change=None)
    if profile:
        state.update(symbol=profile.symbol,profile_id=profile.fingerprint,research_profile=profile.as_dict())
        lab.update(symbol=profile.symbol,profile_id=profile.fingerprint)
    if old:state['previous_version']=dict(version=old.get('version'),last_bar=old.get('last_bar'))
    if old and old.get('version')==VERSION:
        state['real']=copy.deepcopy(old.get('real',{}));state['contexts']=copy.deepcopy(old.get('contexts',{}))
        for key in ('suspended','recent_real','model_rollback_request','last_real_result'):
            if key in old:state[key]=copy.deepcopy(old[key])
    lab['continual']=state
    return state

def context(setup):
    s=setup['snapshot'];vol=setup['atr']/setup.get('price_unit',1e-4)
    if s.get('symbol','EURUSD')!='EURUSD' and not setup.get('learning_namespace'):
        raise ValueError('INSTRUMENT_LEARNING_NAMESPACE_REQUIRED')
    bands=setup.get('volatility_bands_units') if setup.get('learning_namespace') else (3,8)
    volatility='unclassified' if bands is None else 'low' if vol<bands[0] else 'medium' if vol<bands[1] else 'high'
    parts=(VERSION,setup.get('learning_source','unversioned'),setup.get('learning_model','unversioned'),s.get('regime_config_hash','unknown'),s['regime'],
        setup['candidate'].side,'+'.join(sorted(s.get('session',[]))),
        'vol:'+volatility)
    return '|'.join(((setup['learning_namespace'],) if setup.get('learning_namespace') else ())+parts)

def check_scope(state,setup):
    profile=profile_for(state)
    if state.get('profile_id')!=setup['snapshot'].get('profile_id') or state.get('symbol','EURUSD')!=setup['snapshot'].get('symbol','EURUSD'):
        raise ValueError('LEARNING_PORTFOLIO_INSTRUMENT_MISMATCH')
    if profile and (setup.get('learning_namespace')!=profile.learning_namespace or setup.get('price_unit')!=profile.price_unit):
        raise ValueError('LEARNING_CONTEXT_INSTRUMENT_MISMATCH')

def accepts(variant,features):
    rule=VARIANTS[variant]['filter']
    return (rule!='forecast' or all(features.get('forecast_'+str(h)+'_atr',-1)>0 for h in (3,6))) and (rule!='body' or features.get('body_atr',0)>=.5)

def apply(setup,variant):
    # Legacy target variants have no authority to rewrite a source-linked plan.
    if setup.get('snapshot',{}).get('literature_basis') is not None:
        raise ValueError('LITERATURE_PLAN_REQUIRES_SEPARATE_LEARNING')
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
    if sim.instrument_context:
        data['instrument_context']=sim.instrument_context
        data['execution_config']=asdict(sim.config)
    return json.loads(json.dumps(data,default=lambda v:v.isoformat()))

def decode_request(d):
    d=copy.deepcopy(d);candidate=d.pop('candidate');candidate['expires_at']=utc(candidate['expires_at'])
    d['submitted_at']=utc(d['submitted_at'])
    return EntryRequest(candidate=Candidate(**candidate),**d)

def decode_sim(data,units,*,profile=None):
    if data and data.get('instrument_context') and profile is None:
        raise ValueError('SIMULATION_CHECKPOINT_INSTRUMENT_MISMATCH')
    sim=simulator(units,profile=profile)
    if not data:return sim
    if data.get('instrument_context')!=sim.instrument_context or (sim.instrument_context and data.get('execution_config')!=asdict(sim.config)):
        raise ValueError('SIMULATION_CHECKPOINT_INSTRUMENT_MISMATCH')
    for k in ('balance','peak_equity','daily_start','day','daily_entries','account_locked','equity_curve'):
        setattr(sim,k,copy.deepcopy(data[k]))
    sim.request=decode_request(data['request']) if data.get('request') else None
    if data.get('position'):
        p=copy.deepcopy(data['position']);p['request']=decode_request(p['request']);p['entry_at']=utc(p['entry_at'])
        sim.position=Position(**p)
    if sim.request:sim.validate_request_scope(sim.request)
    if sim.position:
        sim.validate_request_scope(sim.position.request)
        if profile and sim.position.units!=sim.config.fixed_units:
            raise ValueError('SIMULATION_CHECKPOINT_LOT_MISMATCH')
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
    profile=profile_for(state)
    if hypothesis.get('profile_id')!=state.get('profile_id') or hypothesis.get('symbol','EURUSD')!=state.get('symbol','EURUSD'):
        raise ValueError('LEARNING_RESULT_INSTRUMENT_MISMATCH')
    if hypothesis.get('learning_version')!=VERSION or hypothesis.get('learning_spec_hash')!=state['spec_hash']:
        state['excluded_legacy']+=1;return
    if profile and not hypothesis.get('learning_context','').startswith(profile.learning_namespace+'|'):
        raise ValueError('LEARNING_RESULT_CONTEXT_MISMATCH')
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
    state=lab['continual'];profile=profile_for(state);events=[];sessions=SessionEngine(profile.session_windows() if profile else SESSIONS)
    gap_detector=profile.calendar.unexpected_gap if profile else unexpected_broker_gap
    portfolios={k:decode_sim(state['portfolios'].get(k),state['units'],profile=profile) for k in VARIANTS}
    for row in rows:
        bar=row if isinstance(row,Candle) else Candle(utc(row['timestamp']),*[row[k] for k in ('open','high','low','close')],row.get('volume',0),row.get('spread_pips'))
        if bar.timestamp+timedelta(seconds=300)>utc(at):continue
        if state['last_bar'] and bar.timestamp<=utc(state['last_bar']):continue
        if bar.timestamp+timedelta(seconds=300)<=utc(state['registered_at']):continue
        previous=state.get('last_bar');valid=True
        if previous:
            # Calendar gaps are allowed; unexpected missing exposure bars are not.
            prior=Candle(utc(previous),bar.open,bar.open,bar.open,bar.open)
            valid=not gap_detector(prior,bar,300)
        active,closing=simulation_window(profile,bar,sessions.identify(bar.timestamp).active_sessions)
        from . import fibonacci_research
        fibonacci_research.guarded(state,'advance',bar,at,valid,active,closing)
        hypothesis_review.advance_portfolios(state,bar,valid,active)
        exploratory_learning.advance(state,bar,at,active)
        for variant,sim in portfolios.items():
            fresh=sim.advance(bar,data_valid=valid,active_sessions=active,force_close_reason=closing)
            for event in fresh:
                if event['status']=='closed':
                    f=event['financial_result'];key=event['intelligence_context']['learning_context']
                    result=dict(variant=variant,context=key,entry_at=event['entry_at'],exit_at=event['observed_at'],
                        **(dict(symbol=profile.symbol,profile_id=profile.fingerprint) if profile else {}),
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
        if any(s.account_locked for s in portfolios.values()):portfolios={k:simulator(state['units'],profile=profile) for k in VARIANTS}
        state['last_bar']=bar.timestamp.isoformat();state['observations']+=1
    cutoff=(utc(at)-timedelta(days=90)).isoformat()
    state['outcomes']=[o for o in state['outcomes'] if o['exit_at']>=cutoff][-2000:]
    state['portfolios']={k:encode_sim(s) for k,s in portfolios.items()}
    promote(state,at)
    hypothesis_review.evaluate(state,at)
    return events

def consider(lab,setup,features,*,history=None):
    state=lab['continual'];check_scope(state,setup);signal=setup['signal_at']
    profile=profile_for(state)
    if utc(signal)<=utc(state['registered_at']) or signal==state['last_signal']:return
    if entry_blocker(setup['snapshot'],setup['candidate'].side):return
    if history is not None:
        from . import fibonacci_research
        fibonacci_research.guarded(state,'consider',setup,history)
    state['last_signal']=signal;state['eligible_signals']+=1;key=context(setup)
    hypothesis_review.consider_portfolios(state,setup,features,key)
    for variant in VARIANTS:
        sim=decode_sim(state['portfolios'].get(variant),state['units'],profile=profile)
        if not sim.busy and not sim.account_locked and accepts(variant,features):
            modified=apply(setup,variant);modified['snapshot']={**setup['snapshot'],'learning_context':key,
                'hypothesis_critique':hypothesis_review.critique(setup,features,profile=profile)}
            sim.submit(request_for(modified,fingerprint(dict(study=state['registered_at'],signal=signal,variant=variant))))
        state['portfolios'][variant]=encode_sim(sim)

def choose(lab,setup,features,protocol_id):
    state=lab['continual'];check_scope(state,setup);key=context(setup);variant=state['champion']
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
        **(dict(symbol=state['symbol'],profile_id=state['profile_id']) if state.get('profile_id') else {}),
        variant_id=variant,learning_version=VERSION,learning_spec_hash=state['spec_hash'],learning_context=key,
        model_configuration=setup.get('learning_model'),
        reason='Alternativa validada neste contexto.' if variant!='baseline' else 'Estrategia base enquanto alternativas acumulam evidencia.',
        selection_score=local.get('recent_mean_r',0),wait=False)

def summary(lab):
    from .learning_evolution import summary as evolution_summary
    from .fibonacci_research import summary as fibonacci_summary
    state=lab.get('continual')
    if not state:return None
    variants=[]
    for key,spec in VARIANTS.items():
        rows=[o for o in state['outcomes'] if o['variant']==key]
        variants.append(dict(id=key,name=spec['name'],closed=len(rows),wins=sum(o['net_pnl']>0 for o in rows),
            net_pnl=sum(o['net_pnl'] for o in rows),active=key==state['champion']))
    study=lab.get('model_study') or {}
    return dict(version=VERSION,automatic=True,registered_at=state['registered_at'],observations=state['observations'],
        **(dict(symbol=state['symbol'],profile_id=state['profile_id']) if state.get('profile_id') else {}),
        eligible_signals=state['eligible_signals'],evidence_status=state['evidence_status'],champion=state['champion'],
        champion_name=VARIANTS[state['champion']]['name'],variants=variants,real_results=sum(v.get('n',0) for cell in state['real'].values() for v in cell.values()),
        last_result=state.get('last_real_result'),last_change=state['last_change'],changes=state['changes'][-5:],
        min_days=7,min_trades=20,censored=state.get('censored',0),suspended_contexts=len(state.get('suspended',{})),
        hypothesis_review=hypothesis_review.summary(state),
        exploratory=exploratory_learning.summary(state),
        forecast_health=state.get('forecast_health'),
        fibonacci=fibonacci_summary(state),
        evolution=evolution_summary(state, VARIANTS),
        model_study={k:study.get(k) for k in ('run_id','registered_at','forecast_count','status','closed','error')} if study else None)
