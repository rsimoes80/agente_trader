"""Independent live market/model observation; no broker execution or START commands."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import signal
import sys
import threading
from uuid import uuid4

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))


def main():
    from aurelia_fx.live_observation import ReadOnlyBridgeClient
    from aurelia_fx.agent_research import intelligence_session
    from aurelia_fx.agent_strategy import propose_pullback,attach_forecast
    from aurelia_fx.entry_trend import POLICY_ID
    from aurelia_fx.forecasting.config import load_config
    from aurelia_fx.forecasting.adapter import TimestralAdapter
    from aurelia_fx.forecasting.core import prepare,build_predictions
    from aurelia_fx.historical.core import closed_rows,utc
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.source_clock import validate_source_clock
    from aurelia_fx.storage import open_memory
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--interval',type=float,default=10)
    args=parser.parse_args()
    if args.interval<5:parser.error('Intervalo mínimo: 5 segundos')
    private=json.loads((ROOT/'config/new-environment.local.json').read_text())
    client=ReadOnlyBridgeClient(f"http://{private['windows_ip']}:{private['bridge_port']}",
                               (ROOT/'data/mt5_bridge.token').read_text().strip(),timeout=30)
    memory=open_memory();adapter=TimestralAdapter(load_config());session=intelligence_session()
    stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
    run_id='live-observation-'+str(uuid4());registered=datetime.now(timezone.utc)
    status=dict(run_id=run_id,symbol='EURUSD',mode='observation_only',entry_policy=POLICY_ID,
                registered_at=registered.isoformat(),orders_enabled=False,status='WARMUP',
                prospective_decisions=0,model_status='NOT_CHECKED')
    directory=ROOT/'data/reports'/run_id;directory.mkdir(parents=True);directory.chmod(0o700)
    def persist(kind,fields):
        record={**status,**fields,'at':datetime.now(timezone.utc).isoformat()}
        memory.record_project_data('live_observation_'+kind,'EURUSD' if kind=='status' else run_id+':'+record['at'],record)
        p=directory/'latest.json';p.write_text(json.dumps(record,indent=2)+'\n');p.chmod(0o600)
        print(json.dumps(record),flush=True)
    memory.record_project_data('live_observation_protocol',run_id,dict(**status,
        code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        forecasting=adapter.config.fingerprint,scope='prospective diagnostics, no orders, no training/promotion'))
    last_forecast=None;initialized=False;last_recorded=None;model_retry_at=None
    try:
        while not stop.is_set():
            try:
                data=client.call('fetch_history','EURUSD','M5',600,include_current=False)
                now=datetime.now(timezone.utc);clock=validate_source_clock(data,now)
                if data.get('trade_mode')!='demo':raise ValueError('DEMO_SOURCE_REQUIRED')
                if not initialized:
                    archived=HistoricalRepository(memory).candles(clock_id=clock['clock_id'],timeframe='M5',start=now-timedelta(days=60),as_of=now)
                    rows=closed_rows(archived,'M5',start=now-timedelta(days=60),as_of=now)
                    if not rows:raise ValueError('WARMUP_ARCHIVE_REQUIRED')
                    for i,row in enumerate(rows):
                        if stop.is_set():return
                        session.update([row],spread_pips=row.get('spread_pips'),observed_at=utc(row['timestamp'])+timedelta(minutes=5),warmup_only=True)
                    initialized=True
                    status['warmup_bars']=len(rows)
                fresh=closed_rows(data['candles'],'M5',start=utc(data['candles'][0]['timestamp']),as_of=now)
                if not fresh:raise ValueError('NO_CLOSED_CANDLES')
                latest=fresh[-1];at=utc(latest['timestamp'])+timedelta(minutes=5)
                if session.last is None or utc(latest['timestamp'])>=session.last.timestamp:
                    snapshot=session.update(fresh,spread_pips=latest.get('spread_pips'),observed_at=at)
                else:raise ValueError('SOURCE_BEHIND_ARCHIVE')
                status.update(status='OBSERVING',last_closed_candle=latest['timestamp'],clock_verified=True,
                              regime=snapshot.regime,
                              h1={k:snapshot.context_trend.get(k) for k in ('timeframe','timestamp_utc','direction','state')},
                              h4={k:snapshot.macro_trend.get(k) for k in ('timeframe','timestamp_utc','direction','state')},
                              last_source_ok=now.isoformat())
                status.pop('error_type',None)
                output=None
                if last_forecast!=latest['timestamp'] and (model_retry_at is None or now>=model_retry_at):
                    try:
                        context=prepare(session.history,at,adapter.config)
                        output=adapter.forecast([c.close for c in context])
                        predictions=build_predictions(context,output,adapter.config,scope='live_observation',source_id=run_id,regime=snapshot.regime,as_of=at)
                        status.update(model_status='AVAILABLE',model_error=None,last_forecast_candle=latest['timestamp'],
                                      model=output.get('model'),latency_ms=output.get('latency_ms'),
                                      forecast_horizons=list(adapter.config.horizons))
                        persist('forecast',dict(predictions=predictions,diagnostic_only=at<registered))
                        last_forecast=latest['timestamp'];model_retry_at=None
                    except (RuntimeError,ValueError,OSError) as exc:
                        status.update(model_status='UNAVAILABLE',model_error=getattr(exc,'code',type(exc).__name__))
                        model_retry_at=now+timedelta(seconds=60)
                if at>=registered and last_recorded!=latest['timestamp']:
                    setup,reason=propose_pullback(snapshot,session.history,daily_history=session.aggregator.history['D1'])
                    fields=dict(action='OBSERVE_PROPOSAL' if setup else 'OBSERVE_WAIT',reason=reason,
                                signal_at=at.isoformat(),forecast_available=output is not None)
                    if setup:
                        fields['side']=setup['candidate'].side
                        if output is not None:fields['features']=attach_forecast(setup,output)
                    status['prospective_decisions']+=1;persist('decision',fields);last_recorded=latest['timestamp']
                persist('status',dict(initial_context_only=at<registered))
            except Exception as exc:
                status.update(status='UNAVAILABLE',error_type=type(exc).__name__)
                try:persist('status',{})
                except Exception:print(json.dumps(dict(status='UNAVAILABLE',error_type=type(exc).__name__)),flush=True)
                if args.once:raise
            if args.once:return
            stop.wait(args.interval)
    finally:
        adapter.close();memory.close()


if __name__=='__main__':main()
