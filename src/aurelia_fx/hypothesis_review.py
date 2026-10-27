"""Evidence-grounded shadow research. No LLM, broker access or promotion.

The comparison is a trade-opportunity ablation, NOT a portfolio backtest:
skipping a trade may change subsequent position availability in a real portfolio.
All state is embedded in the existing transactional learning checkpoint.
"""
from datetime import timedelta
import math

from .agent_model import fingerprint
from .historical.core import utc

VERSION = "hypothesis-review-v3"
LABELS = {
    "CONTRADICTIONS": "A hipótese tem evidências contrárias explícitas.",
    "WEAK_BODY": "O corpo do candle é menor que metade do ATR.",
    "FORECAST_DISAGREES": "Os dois horizontes do Timestral não confirmam a entrada.",
    "FORECAST_BELOW_COST": "O deslocamento mediano de 30 minutos não supera os custos estimados.",
}
SPEC = dict(version=VERSION, discovery_min=20, subgroup_min=8,
            validation_days=14, validation_min=30, scope="shadow_opportunity_ablation",
            promotion=False, threshold="net>0 and paired mean lower bound>0",
            proposal_budget="one test per context and criticism per spec; subsequent discovery uses fresh signals only",
            estimated_costs=dict(pip_size=.0001,slippage_pips_per_side=.2,commission_per_million_side=35.),
            portfolio_comparison="independent base and filtered simulators with original costs and risk")
SPEC_HASH = fingerprint(SPEC)


def spec_for(profile):
    return fingerprint(dict(base=SPEC_HASH,profile=profile.fingerprint)) if profile else SPEC_HASH


def critique(setup, features, *, profile=None):
    expected_profile=profile.fingerprint if profile else None
    if setup['snapshot'].get('profile_id')!=expected_profile or setup['snapshot'].get('symbol','EURUSD')!=(profile.symbol if profile else 'EURUSD'):
        raise ValueError('CRITIQUE_INSTRUMENT_MISMATCH')
    config=profile.execution_config(profile.contract.volume_min) if profile else None
    candidate = setup["candidate"]
    concerns = []
    contradictions=list(candidate.contradictions)+list(setup['snapshot'].get('conflicting_evidence') or [])
    if contradictions or features.get('evidence_conflicted')==1:
        concerns.append("CONTRADICTIONS")
    body = features.get("body_atr")
    if isinstance(body, (int, float)) and math.isfinite(body) and body < .5:
        concerns.append("WEAK_BODY")
    forecasts = [features.get(f"forecast_{h}_atr") for h in (3, 6)]
    known = all(isinstance(v, (int, float)) and math.isfinite(v) for v in forecasts)
    if known and not all(v > 0 for v in forecasts):
        concerns.append("FORECAST_DISAGREES")
    costs=SPEC['estimated_costs'];missing=[] if known else ['forecast']
    # Side-oriented, closed-bar features. The price-equivalent cost screen is
    # descriptive; it is not expected P&L or an entry authorization.
    stop_atr=features.get('stop_atr');spread_stop=features.get('spread_stop')
    cost_evidence=None
    if (known and isinstance(stop_atr,(int,float)) and math.isfinite(stop_atr) and stop_atr>0
            and isinstance(spread_stop,(int,float)) and math.isfinite(spread_stop) and spread_stop>=0):
        distance=abs(candidate.entry-candidate.stop);atr=distance/stop_atr
        execution_cost=(2*config.slippage_pips*config.pip_size+
                        2*config.commission_per_million_side/1_000_000/config.value_per_price_unit) if config else (
                        2*costs['slippage_pips_per_side']*costs['pip_size']+
                        2*costs['commission_per_million_side']/1_000_000)
        estimated_cost=spread_stop*distance+execution_cost
        projected_move=forecasts[1]*atr
        cost_evidence=dict(projected_move=projected_move,estimated_round_trip_cost=estimated_cost,
                           source=profile.costs.source if profile else 'closed_signal_features_and_frozen_research_cost_assumptions',horizon_minutes=30)
        if projected_move<=estimated_cost:concerns.append('FORECAST_BELOW_COST')
    else:missing.append('forecast_cost_comparison')
    return dict(version=VERSION, spec_hash=spec_for(profile), signal_at=utc(setup["signal_at"]).isoformat(),
                **(dict(symbol=profile.symbol,profile_id=profile.fingerprint) if profile else {}),
                evidence=list(candidate.evidence), contradictions=contradictions,
                concerns=concerns, missing=missing, cost_comparison=cost_evidence,
                expectation="Atingir o alvo antes do stop, após custos e dentro do prazo do simulador.",
                invalidation=dict(stop=candidate.stop, expires_at=candidate.expires_at.isoformat()),
                authority="research_only_not_an_entry_veto")


def state_for(state):
    from .continual_learning import profile_for
    spec_hash=spec_for(profile_for(state))
    old=state.get('hypothesis_review')
    if old and old.get('spec_hash')!=spec_hash:
        state['previous_hypothesis_review']=dict(spec_hash=old.get('spec_hash'),reviewed=old.get('reviewed'))
        state.pop('hypothesis_review')
    return state.setdefault("hypothesis_review", dict(spec_hash=spec_hash, reviews=[],
                           proposal=None, reviewed=0, censored=0))


def review(state, event, result):
    """Only baseline results: parallel variants are not independent observations."""
    if result["variant"] != "baseline":
        return
    from .continual_learning import profile_for
    profile=profile_for(state)
    scope=event.get('intelligence_context',{})
    if scope.get('symbol','EURUSD')!=(profile.symbol if profile else 'EURUSD') or scope.get('profile_id')!=(profile.fingerprint if profile else None):
        raise ValueError('REVIEW_INSTRUMENT_MISMATCH')
    if profile and (result.get('symbol')!=profile.symbol or result.get('profile_id')!=profile.fingerprint):
        raise ValueError('REVIEW_RESULT_INSTRUMENT_MISMATCH')
    facts = scope.get("hypothesis_critique")
    if not facts or facts.get("spec_hash") != spec_for(profile):
        return
    research = state_for(state)
    if any(r["event_id"] == result["event_id"] for r in research["reviews"]):
        return
    financial = event["financial_result"]
    net, gross = financial["net_pnl"], financial["gross_pnl"]
    if not all(math.isfinite(v) for v in (net, gross, result["result_in_r"])):
        raise ValueError("Invalid objective review result")
    if (not math.isclose(net,result['net_pnl'],abs_tol=1e-9) or
            not math.isclose(financial.get('result_in_r',result['result_in_r']),result['result_in_r'],abs_tol=1e-9)):
        raise ValueError("Financial result disagrees with simulator event")
    if utc(facts['signal_at']) > utc(result['entry_at']) or utc(result['entry_at']) > utc(result['exit_at']):
        raise ValueError("Noncausal review timestamps")
    category = ("COSTS_CONSUMED_GROSS_GAIN" if gross > 0 and net <= 0 else
                "NET_POSITIVE" if net > 0 else "NET_NEGATIVE" if net < 0 else "FLAT")
    record = dict(**result, signal_at=facts["signal_at"], concerns=facts["concerns"],
                  gross_pnl=gross, costs=gross-net, assessment=category,
                  process="SIMULATOR_COMPLIANT" if event.get("rule_compliance") is True else "NOT_ESTABLISHED",
                  causal_conclusion="not_established", mfe_r=financial.get("mfe_r"),
                  critique=facts)
    research["reviews"].append(record)
    research["reviews"] = research["reviews"][-1000:]
    research["reviewed"] += 1
    proposal = research["proposal"]
    if proposal and proposal["status"] == "COLLECTING_FUTURE":
        if (record["context"] == proposal["context"] and
                utc(proposal["formed_at"]) < utc(record["signal_at"]) < utc(proposal["ends_at"])):
            # Separate frozen future cohort; discovery records never enter it.
            proposal["validation"].append({k:record[k] for k in
                ("event_id", "signal_at", "exit_at", "net_pnl", "concerns")})
    if proposal and proposal['status']=='COLLECTING_FUTURE':
        return
    cohort = [r for r in research["reviews"] if r["context"] == record["context"]]
    if proposal:
        cutoff=utc(proposal.get('evaluated_at',proposal['ends_at']))
        cohort=[r for r in cohort if utc(r['signal_at'])>cutoff]
    if len(cohort) < SPEC["discovery_min"]:
        return
    alternatives = []
    for code in sorted(LABELS):
        if [record['context'],code] in research.get('attempted',[]):continue
        group = [r for r in cohort if code in r["concerns"]]
        if len(group) >= SPEC["subgroup_min"] and sum(r["net_pnl"] for r in group) < 0:
            alternatives.append((sum(r["net_pnl"] for r in group), code))
    if not alternatives:
        return
    code = min(alternatives)[1]
    formed = utc(record["exit_at"])
    if proposal:
        research['history']=(research.get('history',[])+[
            {k:v for k,v in proposal.items() if k not in {'validation','portfolios','portfolio_results'}}])[-30:]
    research.setdefault('attempted',[]).append([record['context'],code])
    research["proposal"] = dict(id=fingerprint(dict(spec=research['spec_hash'], event=record["event_id"], code=code)),
        **(dict(symbol=profile.symbol,profile_id=profile.fingerprint) if profile else {}),
        context=record["context"], rule=code, formed_at=formed.isoformat(),
        ends_at=(formed+timedelta(days=SPEC["validation_days"])).isoformat(),
        status="COLLECTING_FUTURE", discovery_n=len(cohort), validation=[],
        prediction="Excluir oportunidades com esta crítica melhora o resultado líquido no mesmo contexto.",
        minimum_samples=SPEC["validation_min"], automatic_activation=False, portfolios={}, portfolio_results=[],
        scope=SPEC["scope"], followup="Requires independent costed portfolio replay before promotion")


def evaluate(state, at):
    research = state_for(state)
    proposal = research["proposal"]
    if not proposal or proposal["status"] != "COLLECTING_FUTURE":
        return
    # Wait past the fixed window and the simulator's maximum holding period.
    if utc(at) < utc(proposal["ends_at"])+timedelta(days=1):
        return
    proposal['evaluated_at']=utc(at).isoformat()
    portfolio_rows=proposal.get('portfolio_results',[])
    metrics={}
    for arm in ('base','filtered'):
        trades=[r for r in portfolio_rows if r['arm']==arm]
        metrics[arm]=dict(closed=len(trades),net_pnl=sum(r['net_pnl'] for r in trades),
            wins=sum(r['net_pnl']>0 for r in trades))
    proposal['portfolio_metrics']=metrics
    rows = proposal["validation"]
    if len(rows) < proposal["minimum_samples"]:
        proposal["status"] = "INSUFFICIENT_FUTURE_SAMPLE"
        return
    differences = [-r["net_pnl"] if proposal["rule"] in r["concerns"] else 0. for r in rows]
    mean = sum(differences)/len(rows)
    variance = sum((v-mean)**2 for v in differences)/(len(rows)-1)
    lower = mean-2.58*math.sqrt(variance/len(rows))
    filtered_net = sum(r["net_pnl"] for r in rows if proposal["rule"] not in r["concerns"])
    proposal.update(status="PROMISING_REQUIRES_PORTFOLIO_TEST" if lower > 0 and filtered_net > 0 else "NOT_SUPPORTED",
        evaluated_at=utc(at).isoformat(), baseline_net=sum(r["net_pnl"] for r in rows),
        filtered_net=filtered_net, paired_mean=mean, descriptive_lower_bound=lower,
        uncertainty="Trade observations may be dependent; bound is descriptive, not proof of profitability.")
    if proposal['status']=='PROMISING_REQUIRES_PORTFOLIO_TEST':
        proposal['status']=('PROMISING_REQUIRES_INDEPENDENT_CONFIRMATION'
            if min(metrics[a]['closed'] for a in metrics)>=proposal['minimum_samples']
            and metrics['filtered']['net_pnl']>max(0,metrics['base']['net_pnl'])
            else 'PORTFOLIO_BENEFIT_NOT_ESTABLISHED')


def advance_portfolios(state, bar, valid, active_sessions):
    """Replay two independent accounts, including opportunities freed by skipped trades."""
    from .continual_learning import decode_sim, encode_sim, profile_for
    profile=profile_for(state)
    from .agent_research import simulation_window
    active_sessions,closing=simulation_window(profile,bar,active_sessions)
    research=state_for(state);proposal=research['proposal']
    if not proposal or proposal['status']!='COLLECTING_FUTURE':return
    for arm in ('base','filtered'):
        sim=decode_sim(proposal['portfolios'].get(arm),state['units'],profile=profile)
        for event in sim.advance(bar,data_valid=valid,active_sessions=active_sessions,force_close_reason=closing):
            if event['status']=='censored':
                proposal['status']='INVALIDATED_DATA_GAP'
            elif event['status']=='closed':
                f=event['financial_result']
                proposal['portfolio_results'].append(dict(arm=arm,event_id=event['event_id'],
                    exit_at=event['observed_at'],net_pnl=f['net_pnl'],result_in_r=f['result_in_r']))
        sim.events.clear()
        proposal['portfolios'][arm]=encode_sim(sim)


def consider_portfolios(state, setup, features, key):
    from .continual_learning import decode_sim, encode_sim, profile_for, check_scope
    check_scope(state,setup);profile=profile_for(state)
    from .agent_research import request_for
    proposal=state_for(state)['proposal']
    if not proposal or proposal['status']!='COLLECTING_FUTURE':return
    if key!=proposal['context'] or not (utc(proposal['formed_at'])<utc(setup['signal_at'])<utc(proposal['ends_at'])):return
    facts=critique(setup,features,profile=profile)
    for arm in ('base','filtered'):
        sim=decode_sim(proposal['portfolios'].get(arm),state['units'],profile=profile)
        if not sim.busy and not sim.account_locked and (arm=='base' or proposal['rule'] not in facts['concerns']):
            modified={**setup,'snapshot':{**setup['snapshot'],'hypothesis_critique':facts,'learning_context':key}}
            sim.submit(request_for(modified,fingerprint(dict(proposal=proposal['id'],arm=arm,signal=setup['signal_at']))))
        proposal['portfolios'][arm]=encode_sim(sim)


def summary(state):
    research = state.get("hypothesis_review") or {}
    rows = research.get("reviews", [])
    proposal = research.get("proposal")
    return dict(version=VERSION, reviewed=research.get("reviewed", 0),
                last_review=rows[-1] if rows else None,
                proposal={k:v for k,v in proposal.items() if k not in {"validation","portfolios","portfolio_results"}} if proposal else None,
                future_samples=len(proposal["validation"]) if proposal else 0,
                completed_experiments=research.get('history',[]),
                scope=SPEC["scope"], automatic_activation=False)
