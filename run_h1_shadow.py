"""Prospective paper observer for the frozen H1 research candidate; no order API.

Records immutable first-seen candles and evaluates only signals observed on time.
Use --watch for continuous collection; restarts retain protocol, seed and tape.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
UTC = timezone.utc
PARENT = '4865501c4118d37fbd53f9872e3040565a637c1e3c9d978f3a3be7016fb12f53'


def implementation_hashes():
    files = sorted((ROOT/'src').rglob('*.py'))+[ROOT/p for p in ('run_h1_shadow.py','run_h1_extended_validation.py','run_literature_experiment.py','mt5_provider.py')]
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def pending_rows(candles,seed,tape):
    """Preserve the still-forming startup candle once it actually closes."""
    from aurelia_fx.historical.core import utc
    if not seed:
        raise ValueError('Initial context is empty')
    last=utc(tape[-1]['timestamp']) if tape else utc(seed[-1]['timestamp'])
    return [r for r in candles if utc(r['timestamp'])>last]


def on_time(signals, tape, tolerance_seconds=90):
    from aurelia_fx.historical.core import utc
    first_seen = {utc(row['timestamp'])+timedelta(minutes=5):utc(row['first_seen_at']) for row in tape}
    accepted, late = [], []
    for signal in signals:
        stamp = utc(signal['signal_at'])
        observed = first_seen.get(stamp)
        if observed is not None and 0 <= (observed-stamp).total_seconds() <= tolerance_seconds:
            accepted.append(signal)
        else:
            late.append(signal)
    return accepted, late


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.core import utc
    from aurelia_fx.regime_study import candles_from
    from aurelia_fx.source_clock import validate_source_clock
    from run_h1_extended_validation import generate
    from run_literature_experiment import simulate
    from mt5_provider import fetch_history
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch',action='store_true')
    args = parser.parse_args()
    memory = open_memory()
    emit = lambda d:print(json.dumps(d,ensure_ascii=True),flush=True)
    def read(kind,key):
        with memory.pool.connection() as connection:
            row = connection.execute('SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s AND record_key=%s ORDER BY recorded_at LIMIT 1',(kind,key)).fetchone()
        if not row:
            return None
        value = json.loads(row['payload_json'])
        if memory._encode(value)[1] != row['payload_sha256']:
            raise ValueError('Immutable record integrity mismatch')
        return value
    hashes = implementation_hashes()
    try:
        with memory.pool.connection() as lock:
            acquired = lock.execute("SELECT pg_try_advisory_lock(hashtext('agente-trader-h1-shadow-v1')) AS ok").fetchone()['ok']
            lock.commit()
            if not acquired:
                raise RuntimeError('H1 observer already running')
            try:
                parent = read('agent_h1_extended_protocol',PARENT)
                if parent is None:
                    raise ValueError('Parent frozen protocol missing')
                identity = fingerprint(dict(parent=PARENT,code_hashes=hashes))
                protocol = read('agent_h1_shadow_protocol',identity)
                if protocol is None:
                    now = datetime.now(UTC)
                    start = datetime.fromtimestamp(((int(now.timestamp())//300)+1)*300,UTC)
                    protocol = dict(protocol_id=identity,parent=PARENT,code_hashes=hashes,
                        version='h1-shadow-contiguous-startup-v2',
                        registered_at=now.isoformat(),start=start.isoformat(),mode='paper_only',
                        rules=parent,live_policy_changed=False,orders_sent=0,
                        timely_signal='First capture of its closed signal M5 candle must be within90sec of signal close. Late backfills never count as forward entries.',
                        paper_fill='Next M5 open with historical spread and modelled costs, not broker-confirmed fills',
                        missing_data='Replay censors/locks open paper positions on unexpected source gaps; no reset to hide losses',
                        promotion='No automatic broker activation; minimum50closed,net>0,PF>=1.1,positive stress,clean tape; not a profitability guarantee')
                    memory.record_project_data('agent_h1_shadow_protocol',identity,protocol)
                emit(dict(stage='shadow_started',protocol_id=identity,start=protocol['start'],mode='paper_only'))
                while True:
                    try:
                        seed = read('agent_h1_shadow_seed',identity)
                        data = fetch_history('EURUSD','M5',10000 if seed is None else 1000)
                        now = datetime.now(UTC)
                        clock = validate_source_clock(data,now=now)
                        if seed is None:
                            seed = dict(candles=[r for r in data['candles'] if utc(r['timestamp']) < utc(protocol['start'])],
                                source_clock=clock,created_at=now.isoformat())
                            memory.record_project_data('agent_h1_shadow_seed',identity,seed)
                        if clock['clock_id'] != seed['source_clock']['clock_id']:
                            raise ValueError('Source clock identity changed; observation blocked')
                        prefix = identity+':'
                        with memory.pool.connection() as connection:
                            records = connection.execute("SELECT DISTINCT ON(record_key) payload_json,payload_sha256 FROM project_records WHERE record_type='agent_h1_shadow_bar' AND record_key LIKE %s ORDER BY record_key,recorded_at ASC",(prefix+'%',)).fetchall()
                        tape = []
                        for record in records:
                            value = json.loads(record['payload_json'])
                            if memory._encode(value)[1] != record['payload_sha256']:
                                raise ValueError('Paper tape integrity mismatch')
                            tape.append(value)
                        latest = utc(tape[-1]['timestamp']) if tape else None
                        appended = 0
                        for row in pending_rows(data['candles'],seed['candles'],tape):
                            stamp = utc(row['timestamp'])
                            value = dict(**row,first_seen_at=now.isoformat())
                            memory.record_project_data('agent_h1_shadow_bar',prefix+row['timestamp'],value)
                            tape.append(value)
                            latest = stamp
                            appended += 1
                        if appended:
                            cutoff = latest+timedelta(minutes=5)
                            rows = seed['candles']+tape
                            candles = candles_from(rows)
                            signals = generate(candles,utc(protocol['start'])-timedelta(minutes=5))
                            timely, late = on_time(signals,tape)
                            kwargs = dict(start=utc(protocol['start']),end=cutoff,holding_bars=288,purge_hours=0,session_buffer_minutes=5)
                            normal = simulate(timely,candles,**kwargs)
                            stress = simulate(timely,candles,stress=True,**kwargs)
                            cycle = dict(protocol_id=identity,as_of=cutoff.isoformat(),recorded_at=now.isoformat(),
                                bars=len(tape),timely_signals=len(timely),late_signals_not_traded=len(late),
                                signals=timely,results=normal,stress=stress,orders_sent=0,
                                live_policy_changed=False,mode='paper_only',
                                note='An unresolved paper position is expected until exit; censored/locked exposure blocks validation')
                            memory.record_project_data('agent_h1_shadow_cycle',prefix+cutoff.isoformat(),cycle)
                            emit(dict(stage='shadow_cycle',as_of=cutoff.isoformat(),bars=len(tape),
                                timely_signals=len(timely),late_signals=len(late),closed=normal['closed_trades'],net=normal['net_pnl'],
                                censored=normal['censored_trades'],pending=normal['unresolved_position']))
                        else:
                            emit(dict(stage='waiting_for_new_closed_bar',last_bar=latest.isoformat() if latest else None))
                    except Exception as exc:
                        emit(dict(stage='retry',error_type=type(exc).__name__,message=str(exc)[:300]))
                        if not args.watch:
                            raise
                    if not args.watch:
                        break
                    time.sleep(30)
            finally:
                lock.execute("SELECT pg_advisory_unlock(hashtext('agente-trader-h1-shadow-v1'))")
    finally:
        memory.close()


if __name__ == '__main__':
    main()
