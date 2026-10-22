"""Causal, costed held-out portfolio comparison. Never imports a broker gateway."""
from collections import Counter
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path

def confirms(forecaster,context,side,reference):
    values=forecaster.forecast(context,prediction_length=12).quantiles[0,0].numpy()
    median=list(forecaster.model.config.quantile_knots).index(.5)
    return all(side*(float(values[h-1,median])-reference)>0 for h in (3,6))

def simulate(root,folder,output,progress,check):
    import numpy as np
    import torch
    from timestral import TimestralForecaster
    from huggingface_hub import snapshot_download
    from .proof import SOURCE_MODEL,SOURCE_REVISION,file_hash
    from aurelia_fx.agent_research import intelligence_session,simulator,request_for,SESSIONS
    from aurelia_fx.agent_strategy import propose_pullback
    from aurelia_fx.domain import Candle
    from aurelia_fx.sessions import SessionEngine
    from aurelia_fx.broker_calendar import unexpected_broker_gap
    from aurelia_fx.forecasting.core import prepare
    from aurelia_fx.forecasting.config import TimestralConfig
    torch.set_num_threads(1)
    root,folder,output=Path(root),Path(folder),Path(output)
    from .dataset import validate_dataset
    manifest,data=validate_dataset(folder)
    start=datetime.fromisoformat(manifest['boundaries'][1]);end=datetime.fromisoformat(manifest['source_as_of'])
    source=snapshot_download(SOURCE_MODEL,revision=SOURCE_REVISION,local_files_only=True,token=False,cache_dir=str(root/'data/training/cache'),allow_patterns=['config.json','model.safetensors','LICENSE'])
    f=TimestralForecaster.from_pretrained(source,device='cpu',max_context=256)
    original={k:t.detach().clone() for k,t in f.model.head.state_dict().items()}
    from safetensors.torch import load_file
    candidate=load_file(output/'best-head.safetensors')
    sealed=json.loads((output/'selection.json').read_text())
    if file_hash(output/'candidate/model.safetensors')!=sealed['candidate_sha256']:raise ValueError('Sealed candidate changed')
    saved=load_file(output/'candidate/model.safetensors')
    if any(not torch.equal(t,saved['head.'+k]) for k,t in candidate.items()):raise ValueError('Candidate head disagrees with exported checkpoint')
    del saved
    arms={name:simulator(1000.) for name in ('source','candidate')}
    session=intelligence_session();sessions=SessionEngine(SESSIONS);cfg=TimestralConfig()
    blocked=Counter();signals=0;predictions=0;previous=None
    rows=data[(data[:,0]>=(start-timedelta(days=60)).timestamp())&(data[:,0]+300<=end.timestamp())]
    for i,row in enumerate(rows):
        if i%200==0:check()
        at=datetime.fromtimestamp(float(row[0]),timezone.utc)
        spread=None if np.isnan(row[6]) else float(row[6])
        bar=Candle(at,*map(float,row[1:5]),float(row[5]),spread)
        valid=previous is None or not unexpected_broker_gap(previous,bar,300)
        if at>=start:
            for simulation in arms.values():simulation.advance(bar,data_valid=valid,active_sessions=sessions.identify(at).active_sessions)
        snapshot=session.update([bar.as_dict()],spread_pips=spread,observed_at=at+timedelta(seconds=300))
        previous=bar
        if i%800==0:progress(status='SIMULATING',stage='simulation',message='Replay causal completo com regras e custos atuais',completed=i,total=len(rows),simulation_signals=signals)
        if at<start or at+timedelta(seconds=3900)>end:continue
        setup,reason=propose_pullback(snapshot,session.history,daily_history=session.aggregator.history.get('D1',[]))
        if not setup:blocked[reason]+=1;continue
        signals+=1
        try:context=prepare(session.history,at+timedelta(seconds=300),cfg)
        except ValueError:blocked['FORECAST_CONTEXT_INSUFFICIENT']+=1;continue
        x=np.asarray([c.close for c in context],dtype=np.float32)
        for name,head in (('source',original),('candidate',candidate)):
            simulation=arms[name]
            if simulation.busy or simulation.account_locked:continue
            f.model.head.load_state_dict(head)
            sign=setup['features']['side'];ref=setup['reference_close']
            predictions+=1
            if not confirms(f,x,sign,ref):
                blocked[name+':FORECAST_DISAGREES']+=1;continue
            simulation.submit(request_for(setup,name+':'+setup['signal_at']))
    for simulation in arms.values():simulation.finish(end)
    result=dict(period_start=start.isoformat(),period_end=end.isoformat(),warmup_days=60,
        bars_replayed=len(rows),technical_signals=signals,forecast_calls=predictions,
        blockers=dict(blocked),arms={name:sim.summary() for name,sim in arms.items()},
        scope='fixed forecast_pullback portfolio; not adaptive full robot',lot=.01,
        costs='spread + 0.2 pip market slippage + USD35/million/side commission',orders_sent=0)
    a,b=result['arms']['source'],result['arms']['candidate'];reasons=[]
    if min(a['closed_trades'],b['closed_trades'])<20:reasons.append('FINANCIAL_SAMPLE_INSUFFICIENT')
    if b['net_pnl'] is None or b['net_pnl']<=0:reasons.append('NET_PROFIT_NOT_POSITIVE')
    if a['net_pnl'] is None or b['net_pnl'] is None or b['net_pnl']<a['net_pnl']:reasons.append('NET_PROFIT_BELOW_SOURCE_OR_UNRESOLVED')
    if b['max_close_equity_drawdown_pct']>a['max_close_equity_drawdown_pct']:reasons.append('DRAWDOWN_ABOVE_SOURCE')
    if any(s.busy or s.account_locked for s in arms.values()):reasons.append('EXPOSURE_UNRESOLVED')
    result['gate']=dict(passed=not reasons,reasons=reasons)
    (output/'simulation-report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    (output/'simulation-events.json').write_text(json.dumps({name:s.events for name,s in arms.items()},indent=2),encoding='utf-8')
    return result
