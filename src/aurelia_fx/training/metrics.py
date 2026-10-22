"""Descriptive paired forecast metrics; targets never enter model inputs."""
from datetime import datetime,timezone


def forecast_metrics(prediction,target,reference,levels):
    import numpy as np
    q=np.asarray(levels);p=np.asarray(prediction,dtype=np.float64);y=np.asarray(target,dtype=np.float64)
    if p.shape!=(*y.shape,len(q)) or not np.isfinite(p).all() or not np.isfinite(y).all() or len(y)==0 or (np.diff(p,axis=-1)<0).any():raise ValueError('Invalid forecast evaluation arrays')
    median=int(np.flatnonzero(q==.5)[0]);lo=int(np.flatnonzero(q==.1)[0]);hi=int(np.flatnonzero(q==.9)[0])
    error=y[...,None]-p
    losses=np.maximum(q*error,(q-1)*error).mean(axis=(1,2))
    result=dict(windows=len(y),mean_pinball_pips=float(losses.mean()*10000),horizons={})
    for h in (3,6,12):
        pred=p[:,h-1,median];truth=y[:,h-1]
        actual_direction=np.sign(np.where(abs(truth-reference)<1e-10,0,truth-reference))
        pred_direction=np.sign(np.where(abs(pred-reference)<1e-10,0,pred-reference))
        result['horizons'][str(h)]=dict(mae_pips=float(abs(pred-truth).mean()*10000),
            bias_pips=float((pred-truth).mean()*10000),direction_accuracy_pct=float((actual_direction==pred_direction).mean()*100),
            coverage_10_90_pct=float(((truth>=p[:,h-1,lo])&(truth<=p[:,h-1,hi])).mean()*100),
            interval_width_pips=float((p[:,h-1,hi]-p[:,h-1,lo]).mean()*10000))
    return result,losses


def paired_day_interval(original,candidate,timestamps,draws=1000):
    import numpy as np
    a=np.asarray(original);b=np.asarray(candidate);dates=np.asarray(timestamps,dtype=np.int64)//86400
    days=np.unique(dates)
    if len(days)<20:return dict(days=len(days),improvement_ci95_pct=None)
    sums=np.array([[a[dates==d].sum(),b[dates==d].sum(),(dates==d).sum()] for d in days])
    rng=np.random.default_rng(31);sample=sums[rng.integers(0,len(days),size=(draws,len(days)))].sum(axis=1)
    if (sample[:,0]<=0).any():return dict(days=len(days),improvement_ci95_pct=None)
    improvement=100*(sample[:,0]-sample[:,1])/sample[:,0]
    return dict(days=len(days),improvement_ci95_pct=np.percentile(improvement,[2.5,97.5]).tolist())


def forecast_gate(source,candidate,interval):
    reasons=[]
    if candidate['windows']<200:reasons.append('FORECAST_SAMPLE_INSUFFICIENT')
    denominator=source['mean_pinball_pips']
    improvement=100*(denominator-candidate['mean_pinball_pips'])/denominator if denominator>0 else 0.
    if improvement<2:reasons.append('PINBALL_IMPROVEMENT_BELOW_2_PERCENT')
    ci=interval.get('improvement_ci95_pct')
    if not ci or ci[0]<=0:reasons.append('PAIRED_DAY_EVIDENCE_INCONCLUSIVE')
    for h in ('3','6','12'):
        a,b=source['horizons'][h],candidate['horizons'][h]
        if b['mae_pips']>a['mae_pips']*1.02:reasons.append('MAE_DEGRADED_'+h)
        if b['direction_accuracy_pct']<a['direction_accuracy_pct']-3:reasons.append('DIRECTION_DEGRADED_'+h)
        if not 70<=b['coverage_10_90_pct']<=90:reasons.append('INTERVAL_COVERAGE_OUTSIDE_GATE_'+h)
    return dict(passed=not reasons,reasons=reasons,pinball_improvement_pct=improvement)
