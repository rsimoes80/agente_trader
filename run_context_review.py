"""Descriptive pivot audit and pre-entry charts; never changes trading rules."""
import hashlib
import json
import os
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
REPORT='fb8d9cd051243e66b9ad356f245ff50dd61627763b128d5ae3c6237732934af2'


def leg(bars,side,signal,correction_start,seconds,adverse):
    from aurelia_fx.structure import analyze_structure
    from aurelia_fx.historical.core import utc
    from aurelia_fx.context_experiment import atr
    swings=[s for s in analyze_structure(bars,2,bar_seconds=seconds).swings if utc(s.confirmed_at)<=signal]
    endpoints=[s for s in swings if s.kind==('high' if side=='long' else 'low') and utc(s.timestamp)+timedelta(seconds=seconds)<=correction_start]
    if not endpoints:return None
    end=endpoints[-1];origins=[s for s in swings if s.kind!=end.kind and utc(s.timestamp)<utc(end.timestamp)]
    if not origins:return None
    start=origins[-1];sign=1 if side=='long' else -1;amplitude=sign*(end.price-start.price)
    if amplitude<=0:return None
    scale=atr(bars[max(0,start.index-15):start.index])
    return dict(start=start.timestamp,end=end.timestamp,start_confirmed=start.confirmed_at,end_confirmed=end.confirmed_at,
        start_price=start.price,end_price=end.price,retracement=sign*(end.price-adverse)/amplitude,
        amplitude_atr=amplitude/scale if scale and scale>0 else None)


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.regime_study import candles_from
    from aurelia_fx.agent_research import intelligence_session
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.core import utc
    from aurelia_fx.broker_calendar import unexpected_broker_gap
    memory=open_memory()
    def decode(row):
        if not row:raise ValueError('Missing source record')
        value=json.loads(row['payload_json'])
        if memory._encode(value)[1]!=row['payload_sha256']:raise ValueError('Source integrity failure')
        return value
    try:
        with memory.pool.connection() as c:
            report=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_context_experiment' AND record_key=%s LIMIT 1",(REPORT,)).fetchone())
            source=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_correction_experiment' AND record_key=%s LIMIT 1",(report['source_report'],)).fetchone())
            baseline=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_history' AND record_key=%s LIMIT 1",(report['baseline_id'],)).fetchone())
        _,rows=HistoricalRepository(memory).frozen_candles(baseline,record_type='agent_training_history')
        candles=candles_from(rows);samples={s['sample_id']:s for s in source['eligible_samples']}
        trades=report['results']['all']['reference']['trades'];targets={utc(t['entry_at']):t for t in trades}
        selected=[next(t for t in trades if t['financial_result']['net_pnl']>0),next(t for t in trades if t['financial_result']['net_pnl']<0)]
        selected_ids={t['sample_id'] for t in selected};views={};audit={};previous=None;agg=intelligence_session().aggregator
        for bar in candles:
            if previous and unexpected_broker_gap(previous,bar,300):agg.reset()
            histories=agg.add(bar);previous=bar;signal=bar.timestamp+timedelta(minutes=5)
            trade=targets.get(signal)
            if not trade:continue
            key=trade['sample_id'];s=samples[key];m5=list(histories['M5']);h1=list(histories['H1'])
            correction=m5[-4:-1];start=correction[0].timestamp
            adverse=min(b.low for b in correction) if trade['side']=='long' else max(b.high for b in correction)
            audit[key]=dict(entry_at=signal.isoformat(),net_pnl=trade['financial_result']['net_pnl'],
                m5_known_pivot_leg=leg(m5,trade['side'],signal,start,300,adverse),
                h1_known_pivot_leg=leg(h1,trade['side'],signal,start,3600,adverse))
            if key in selected_ids:views[key]=(m5,h1)
        if len(audit)!=len(trades):raise ValueError('Incomplete review contexts')
        os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'data/reports/.mpl-cache'))
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        from matplotlib.ticker import FormatStrFormatter
        fig,axes=plt.subplots(2,2,figsize=(15,8),layout='constrained')
        for row,t in enumerate(selected):
            key=t['sample_id'];s=samples[key];feature=report['features'][key]
            for column,tf,limit in [(0,'H1',40),(1,'M5',60)]:
                ax=axes[row,column];bars=views[key][1 if tf=='H1' else 0][-limit:]
                for i,b in enumerate(bars):
                    color='#168568' if b.close>=b.open else '#bf4051'
                    ax.vlines(i,b.low,b.high,color=color,lw=.8)
                    ax.add_patch(Rectangle((i-.3,min(b.open,b.close)),.6,max(abs(b.close-b.open),.000002),color=color))
                if tf=='M5':
                    n=len(bars);ax.axvspan(n-10-.5,n-4-.5,color='#6695ed',alpha=.2,label='6-bar prior window')
                    ax.axvspan(n-4-.5,n-1-.5,color='#e7b64a',alpha=.3,label='3-bar correction')
                    for field,color in [('stop','#bf4051'),('target','#168568')]:ax.axhline(s['candidate'][field],color=color,ls='--',lw=.8,label=field)
                    ax.legend(fontsize=7,loc='best')
                ax.axvline(len(bars)-.5,color='#315b9d',ls=':',lw=1)
                step=8 if tf=='H1' else 12
                ax.set_xticks(range(0,len(bars),step),[b.timestamp.strftime('%d/%m %H:%M') for b in bars[::step]],fontsize=7)
                ax.yaxis.set_major_formatter(FormatStrFormatter('%.5f'));ax.grid(alpha=.15)
                outcome='first net gain' if t['financial_result']['net_pnl']>0 else 'first net loss'
                ax.set_title(f"{tf} | {t['entry_at'][:16]} UTC | SELL | {outcome}",fontsize=9)
                ax.set_ylabel('EURUSD bid')
                if tf=='H1':ax.text(.02,.96,f"H4/H1: BEAR_CONFIRMED\nprior H1 leg: {feature['h1_impulse_atr']:.2f} ATR",transform=ax.transAxes,va='top',fontsize=8)
        fig.suptitle('Pre-entry context only - descriptive examples, selected by outcome class; not a validation sample',fontsize=11)
        target=ROOT/'docs/audits/context-before-entry.png';target.parent.mkdir(parents=True,exist_ok=True)
        fig.savefig(target,dpi=150);plt.close(fig)
        summary={}
        for tf in ('m5','h1'):
            values=[r[tf+'_known_pivot_leg'] for r in audit.values() if r[tf+'_known_pivot_leg'] is not None]
            summary[tf]=dict(available=len(values),shallow=sum(0<v['retracement']<=.5 for v in values),
                strong_shallow=sum(v['amplitude_atr'] is not None and v['amplitude_atr']>=1 and 0<v['retracement']<=.5 for v in values),
                beyond_origin=sum(v['retracement']>1 for v in values))
        result=dict(source_report=REPORT,created_at=datetime.now(timezone.utc).isoformat(),
            scope='post-result descriptive pivot audit, no new filters or financial backtest',audit=audit,summary=summary,
            examples=[t['sample_id'] for t in selected],selection='chronologically first reference net gain and first net loss',
            figure='docs/audits/context-before-entry.png',figure_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),orders_sent=0)
        result['review_id']=fingerprint(result)
        memory.record_project_data('agent_context_review',result['review_id'],result)
        (ROOT/'data/reports/context-review.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(dict(review_id=result['review_id'],summary=summary,figure=str(target))))
    finally:memory.close()


if __name__=='__main__':main()
