"""Small research-only model of costed trade reward, not price direction."""
import math

from .agent_model import fingerprint
from .agent_strategy import FEATURES
from .historical.core import utc

SPEC=dict(version='expected-net-reward-v2',features=list(FEATURES),ridge_penalty=10.,
          feature_clip=8.,unclipped_reward=True,minimum_fit=100,entry_threshold=0.,
          target='Realised costed R of an isolated candidate, including known-session exit',
          authority='research_only; predicted R is neither a calibrated probability nor an order authorization')


def fit(samples, *, known_before):
    import numpy as np
    cutoff=utc(known_before)
    if any(utc(s['exit_at'])>=cutoff or utc(s['signal_at'])>=cutoff for s in samples):
        raise ValueError('Unresolved or future label in reward training')
    if len(samples)<SPEC['minimum_fit']:raise ValueError('Insufficient reward training samples')
    x=np.asarray([[s['features'][f] for f in FEATURES] for s in samples],dtype=float)
    y=np.asarray([s['result_in_r'] for s in samples],dtype=float)
    if not np.isfinite(x).all() or not np.isfinite(y).all():raise ValueError('Nonfinite reward training data')
    center=x.mean(axis=0);scale=x.std(axis=0)
    scale[scale<1e-8]=1.
    z=np.clip((x-center)/scale,-SPEC['feature_clip'],SPEC['feature_clip'])
    design=np.column_stack((np.ones(len(z)),z))
    penalty=np.eye(len(FEATURES)+1)*SPEC['ridge_penalty'];penalty[0,0]=0.
    coefficients=np.linalg.solve(design.T@design+penalty,design.T@y)
    if not np.isfinite(coefficients).all():raise ValueError('Invalid reward model coefficients')
    model=dict(spec=SPEC,known_before=cutoff.isoformat(),samples=len(samples),
        training_hash=fingerprint(samples),max_label_time=max(s['exit_at'] for s in samples),
        center=center.tolist(),scale=scale.tolist(),weights=coefficients[1:].tolist(),
        intercept=float(coefficients[0]),constant_prediction=float(y.mean()))
    model['observed_reward_range']=[float(y.min()),float(y.max())]
    model['id']=fingerprint(model)
    return model


def predict(model, features):
    if model['spec']!=SPEC:raise ValueError('Incompatible reward model')
    value=model['intercept']
    for key,center,scale,weight in zip(FEATURES,model['center'],model['scale'],model['weights']):
        x=features[key]
        if not math.isfinite(x):raise ValueError('Nonfinite reward feature')
        value+=weight*max(-SPEC['feature_clip'],min(SPEC['feature_clip'],(x-center)/scale))
    if not math.isfinite(value):raise ValueError('Nonfinite reward prediction')
    return value
