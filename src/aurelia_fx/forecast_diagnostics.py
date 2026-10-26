"""Causal cached-forecast audit; diagnostic returns are NOT portfolio returns."""
from collections import Counter
from datetime import timedelta
import math
import random
from statistics import mean

from .agent_model import fingerprint
from .historical.core import utc

SPEC = dict(version='forecast-information-audit-v3', horizons=[3,6,12], pip_size=.0001,
    slippage_pips_side=.2, commission_per_million_side=35., bootstrap_draws=2000,
    seed=20261026, bootstrap_block='UTC calendar week, Monday start',
    deduplication='longest verified context per reference/model/config; lexical cache key tie break',
    baseline='last close; mean drift; empirical horizon-change Q10/Q50/Q90 over exact input context',
    economic_scope='overlapping fixed-horizon signed price changes, not executable portfolio P&L')


def empirical_quantile(values, q):
    ordered=sorted(values)
    if not ordered or not 0<=q<=1:raise ValueError('Invalid empirical quantile')
    position=(len(ordered)-1)*q;lower=int(position);upper=min(lower+1,len(ordered)-1)
    return ordered[lower]+(position-lower)*(ordered[upper]-ordered[lower])


def cases(candles, caches):
    """Verify every past input hash before using cached forecasts or future labels."""
    index={c.timestamp:i for i,c in enumerate(candles)}
    if len(index)!=len(candles) or any(b.timestamp<=a.timestamp for a,b in zip(candles,candles[1:])):
        raise ValueError('Unordered or duplicate source candles')
    counters=Counter();valid={}
    for cache in caches:
        counters['caches_read']+=1
        reference=utc(cache['input_last']);i=index.get(reference);n=cache['input_bars']
        if i is None or type(n) is not int or n<2 or i+1<n:
            counters['outside_input_coverage']+=1;continue
        context=candles[i+1-n:i+1]
        if any((b.timestamp-a.timestamp).total_seconds()!=300 for a,b in zip(context,context[1:])):
            counters['input_gap']+=1;continue
        if fingerprint([c.as_dict() for c in context])!=cache['input_hash']:
            counters['input_hash_mismatch']+=1;continue
        output=cache['output'];quantiles=output['quantiles']
        if (output['levels']!=[.1,.5,.9] or len(quantiles)!=12 or any(
                len(q)!=3 or not all(math.isfinite(v) and v>0 for v in q) or list(q)!=sorted(q) for q in quantiles)):
            counters['invalid_quantiles']+=1;continue
        model=fingerprint({k:output[k] for k in ('model','revision','artifact_sha256','sdk_revision')})
        key=(reference,model,cache['configuration'])
        previous=valid.get(key)
        if previous:
            counters['duplicate_reference']+=1
            if (-n,cache['cache_key'])>=(-previous['input_bars'],previous['cache_key']):continue
        valid[key]=cache
    result=[]
    for (reference,model,configuration),cache in sorted(valid.items()):
        i=index[reference];n=cache['input_bars'];base=candles[i].close
        drift=(base-candles[i+1-n].close)/(n-1)
        for h in SPEC['horizons']:
            if i+h>=len(candles):counters['future_outside_coverage']+=1;continue
            future=candles[i+1:i+h+1]
            if any(c.timestamp!=reference+timedelta(minutes=5*(j+1)) for j,c in enumerate(future)):
                counters['future_gap']+=1;continue
            low,median,high=cache['output']['quantiles'][h-1];actual=future[-1].close
            context=candles[i+1-n:i+1]
            changes=[context[j].close-context[j-h].close for j in range(h,len(context))]
            if not changes:counters['insufficient_empirical_context']+=1;continue
            empirical=[base+empirical_quantile(changes,q) for q in (.1,.5,.9)]
            predicted_change=(median-base)/SPEC['pip_size'];actual_change=(actual-base)/SPEC['pip_size']
            sign=1 if predicted_change>1e-6 else -1 if predicted_change< -1e-6 else 0
            realised=1 if actual_change>1e-6 else -1 if actual_change< -1e-6 else 0
            spread=candles[i].spread_pips
            cost=(spread+2*SPEC['slippage_pips_side']+2*SPEC['commission_per_million_side']/1e6/SPEC['pip_size']
                  if spread is not None and math.isfinite(spread) and spread>=0 else None)
            monday=reference.date()-timedelta(days=reference.weekday())
            result.append(dict(cache_key=cache['cache_key'],model_key=model,configuration=configuration,
                reference=reference.isoformat(),known_at=(reference+timedelta(minutes=5)).isoformat(),
                target_closed_at=(future[-1].timestamp+timedelta(minutes=5)).isoformat(),horizon=h,
                week=monday.isoformat(),input_bars=n,hourly_reference=(reference.minute==55),
                forecast_mae_pips=abs(median-actual)/SPEC['pip_size'],
                persistence_mae_pips=abs(base-actual)/SPEC['pip_size'],
                drift_mae_pips=abs(base+h*drift-actual)/SPEC['pip_size'],
                empirical_mae_pips=abs(empirical[1]-actual)/SPEC['pip_size'],
                empirical_coverage=empirical[0]<=actual<=empirical[2],
                predicted_change_pips=predicted_change,actual_change_pips=actual_change,
                directional_hit=sign==realised,directional_nonflat=bool(sign and realised),
                covered=low<=actual<=high,nominal_coverage=.8,
                quantile_pinball_pips=mean(max(q*(actual-v),(q-1)*(actual-v))/SPEC['pip_size']
                    for q,v in zip((.1,.5,.9),(low,median,high))),
                persistence_pinball_pips=mean(max(q*(actual-base),(q-1)*(actual-base))/SPEC['pip_size'] for q in (.1,.5,.9)),
                empirical_pinball_pips=mean(max(q*(actual-v),(q-1)*(actual-v))/SPEC['pip_size']
                    for q,v in zip((.1,.5,.9),empirical)),
                cost_pips=cost,median_exceeds_cost=cost is not None and abs(predicted_change)>cost,
                signed_move_after_assumed_cost_pips=sign*actual_change-cost if cost is not None and sign else None))
    return result,dict(counters)


def week_interval(rows, baseline='persistence_mae_pips', model='forecast_mae_pips'):
    """Paired week-block bootstrap of a baseline loss minus model loss."""
    groups={}
    for r in rows:
        group=groups.setdefault(r['week'],[0.,0])
        group[0]+=r[baseline]-r[model];group[1]+=1
    blocks=list(groups.values())
    if len(blocks)<4:return dict(weeks=len(blocks),interval=None,reason='INSUFFICIENT_WEEKS')
    rng=random.Random(SPEC['seed']);values=[]
    for _ in range(SPEC['bootstrap_draws']):
        chosen=rng.choices(blocks,k=len(blocks));values.append(sum(a for a,b in chosen)/sum(b for a,b in chosen))
    values.sort()
    return dict(weeks=len(blocks),interval=[values[int(.025*len(values))],values[int(.975*len(values))]],
                method='descriptive paired week bootstrap; not multiplicity adjusted')


def metrics(rows):
    if not rows:return dict(n=0)
    economic=[r for r in rows if r['signed_move_after_assumed_cost_pips'] is not None]
    large=[r for r in economic if r['median_exceeds_cost']]
    directional=[r for r in rows if r['directional_nonflat']]
    return dict(n=len(rows),forecast_mae_pips=mean(r['forecast_mae_pips'] for r in rows),
        persistence_mae_pips=mean(r['persistence_mae_pips'] for r in rows),
        drift_mae_pips=mean(r['drift_mae_pips'] for r in rows),
        empirical_mae_pips=mean(r['empirical_mae_pips'] for r in rows),
        empirical_pinball_pips=mean(r['empirical_pinball_pips'] for r in rows),
        empirical_coverage=mean(r['empirical_coverage'] for r in rows),
        pinball_pips=mean(r['quantile_pinball_pips'] for r in rows),
        persistence_pinball_pips=mean(r['persistence_pinball_pips'] for r in rows),
        directional_accuracy=mean(r['directional_hit'] for r in rows),
        directional_nonflat_n=len(directional),
        directional_nonflat_accuracy=mean(r['directional_hit'] for r in directional) if directional else None,
        interval_coverage=mean(r['covered'] for r in rows),
        predicted_absolute_move_pips=mean(abs(r['predicted_change_pips']) for r in rows),
        actual_absolute_move_pips=mean(abs(r['actual_change_pips']) for r in rows),
        assumed_cost_pips=mean(r['cost_pips'] for r in economic) if economic else None,
        median_exceeds_cost_n=len(large),
        diagnostic_signed_move_net_pips=mean(r['signed_move_after_assumed_cost_pips'] for r in economic) if economic else None,
        above_cost_diagnostic_signed_move_net_pips=mean(r['signed_move_after_assumed_cost_pips'] for r in large) if large else None,
        paired_persistence_minus_model_mae=week_interval(rows),
        paired_empirical_minus_model_pinball=week_interval(rows,'empirical_pinball_pips','quantile_pinball_pips'),
        warning=SPEC['economic_scope'])
