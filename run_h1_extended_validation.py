"""Frozen H1 candidate on additional 2021-2025 MT5 data, without broker orders.

Run once to capture/preregister; --resume PROTOCOL_ID reuses the immutable archive.
No parameter search, production promotion or weight update occurs here.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
UTC = timezone.utc
SOURCE = '2f6f3f7dc7391f62d9422a56885c7543392917ff40b448947c3c825c3f6f1d9c'
PROFILE = dict(execution='H1', context='H4', confirmation='H4', macro='D1')


def generate(candles, start, emit=lambda _: None):
    from aurelia_fx.agent_research import intelligence_session, SESSIONS
    from aurelia_fx.broker_calendar import unexpected_broker_gap, slot_tradable
    from aurelia_fx.sessions import SessionEngine
    from aurelia_fx.literature_strategies import setups
    agg = intelligence_session().aggregator
    sessions = SessionEngine(SESSIONS)
    previous, signals, events = None, [], set()
    for i, bar in enumerate(candles):
        if i % 20000 == 0:
            emit(dict(stage='generating', processed=i, total=len(candles)))
        if previous and unexpected_broker_gap(previous, bar, 300):
            agg.reset()
        histories = agg.add(bar)
        previous = bar
        known = bar.timestamp + timedelta(minutes=5)
        active = sessions.identify(known).active_sessions
        execution = histories['H1']
        if (bar.timestamp < start or not active or not slot_tradable(known)
                or not execution or execution[-1].timestamp + timedelta(hours=1) != known):
            continue
        setup = setups(histories, **PROFILE).get('breakout_retest')
        if setup is None:
            continue
        candidate = setup.pop('candidate')
        event = ('H1', 'breakout_retest', setup['event'], candidate.side)
        if event in events:
            continue
        events.add(event)
        sid = 'H1:breakout_retest:' + known.isoformat()
        signals.append(dict(sample_id=sid, signal_at=known.isoformat(), entry_at=known.isoformat(),
            snapshot=dict(snapshot_id=sid, session=list(active), regime='FAMILY_BREAKOUT_RETEST', research_context=setup),
            candidate=dict(side=candidate.side, entry=candidate.entry, stop=candidate.stop,
                target=candidate.target, expires_at=candidate.expires_at.isoformat(), evidence=list(candidate.evidence))))
    return signals


def clean(result):
    return (not result['account_locked'] and not result['unresolved_position']
            and not result['censored_trades'] and result['net_pnl'] is not None)


def qualified(normal, stress, minimum):
    return (clean(normal) and clean(stress) and normal['closed_trades'] >= minimum
            and normal['net_pnl'] > 0 and (normal['profit_factor'] or 0) >= 1.1
            and stress['net_pnl'] > 0)


def uncertainty(trades, draws=5000):
    """Descriptive trading-day block bootstrap, not a significance/promotion gate."""
    from aurelia_fx.historical.core import utc
    blocks = defaultdict(float)
    for trade in trades:
        blocks[utc(trade['entry_at']).date().isoformat()] += trade['financial_result']['net_pnl']
    values = list(blocks.values())
    if len(values) < 2:
        return dict(trading_days=len(values), net_interval_95=None)
    rng = random.Random(20261023)
    totals = sorted(sum(rng.choices(values, k=len(values))) for _ in range(draws))
    pnls = sorted((t['financial_result']['net_pnl'] for t in trades), reverse=True)
    return dict(trading_days=len(values), draws=draws, seed=20261023,
        net_interval_95=[totals[int(draws*.025)], totals[min(draws-1, int(draws*.975))]],
        net_without_best_trade=sum(pnls[1:]), net_without_best_three=sum(pnls[3:]),
        caveat='Conditional on observed trading days; sparse and serially dependent samples, strategy selection and model error are not eliminated')


def main():
    import psutil
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import utc, closed_rows, summarize
    from aurelia_fx.regime_study import candles_from
    from run_literature_experiment import simulate
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume')
    parser.add_argument('--capture-from', help='Reuse an immutable raw snapshot; no outcome reuse')
    args = parser.parse_args()
    try:
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == 'win32' else 10)
    except (psutil.Error, AttributeError):
        pass
    memory = open_memory()
    repo = HistoricalRepository(memory)
    output = ROOT / 'data/reports'
    output.mkdir(parents=True, exist_ok=True)
    emit = lambda d: print(json.dumps(d, ensure_ascii=True), flush=True)
    def read(kind, key):
        with memory.pool.connection() as connection:
            row = connection.execute('SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s AND record_key=%s ORDER BY recorded_at LIMIT 1', (kind, key)).fetchone()
        if not row:
            raise ValueError('Missing immutable record: '+kind)
        value = json.loads(row['payload_json'])
        if memory._encode(value)[1] != row['payload_sha256']:
            raise ValueError('Record integrity mismatch')
        return value
    files = sorted((ROOT/'src').rglob('*.py')) + [ROOT/p for p in
        ('run_h1_extended_validation.py', 'run_literature_experiment.py', 'mt5_provider.py')]
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    try:
        if args.resume:
            protocol = read('agent_h1_extended_protocol', args.resume)
            if hashes != protocol['code_hashes']:
                raise ValueError('Implementation changed; refuse resume')
        else:
            source = read('agent_timeframe_session_experiment', SOURCE)
            protocol = dict(version='h1-additional-history-v1', source=SOURCE,
                registered_at=datetime.now(UTC).isoformat(), profile=PROFILE, capture_from=args.capture_from,
                rules=source['protocol'], code_hashes=hashes,
                capture='MT5 closed M5, bounded499999 bars, years2021..2025 with30day warmup, date-specific broker UTC normalization',
                candidate='H1 breakout_retest ONLY; same 3R/ATR/EMA/fees/risks/lot.01/session buffer5min and288M5 holding; no new parameter selection',
                qualification='2021..2023 pooled >=50 trades,net>0,PF>=1.1,positive stress; 2024 >=20 same; 2025 >=20 same; every portfolio clean',
                data_caveat='Additional historical corroboration, not prospective validation. 2026 already used for selection; late2025 may overlap previous research. Report every year including losses.',
                prospective_start=datetime.now(UTC).isoformat(), automatic_promotion=False, orders_sent=0)
            protocol['protocol_id'] = fingerprint(protocol)
            memory.record_project_data('agent_h1_extended_protocol', protocol['protocol_id'], protocol)
        key = protocol['protocol_id']
        emit(dict(stage='protocol_registered', protocol_id=key))
        capture = None
        try:
            capture = read('agent_h1_extended_capture', key)
        except ValueError:
            if protocol.get('capture_from'):
                capture = read('agent_h1_extended_capture', protocol['capture_from'])
                memory.record_project_data('agent_h1_extended_capture', key, capture)
        if capture is None:
            import numpy as np
            import mt5_provider as provider
            from aurelia_fx.source_clock import validate_source_clock
            metadata = provider.fetch_history('EURUSD', 'M5', 100)
            clock = validate_source_clock(metadata, now=datetime.now(UTC))
            chunks = []
            with provider._LOCK:
                try:
                    provider._open_terminal()
                    position, remaining = 1, 499999
                    while remaining:
                        size = min(remaining, 65535)
                        chunk = provider.mt5.copy_rates_from_pos(metadata['symbol'], provider.mt5.TIMEFRAME_M5, position, size)
                        if chunk is None or not len(chunk):
                            raise RuntimeError('MT5 historical capture failed at position '+str(position))
                        chunks.append(chunk)
                        position += len(chunk)
                        remaining -= len(chunk)
                        if len(chunk) < size:
                            break
                finally:
                    provider.mt5.shutdown()
            rates = np.concatenate(list(reversed(chunks)))
            if len(rates) < 2 or np.any(np.diff(rates['time']) <= 0):
                raise ValueError('Duplicate or disordered capture; refuse partial archive')
            rawpath = output / ('h1-raw-'+key[:12]+'.npy')
            np.save(rawpath, rates, allow_pickle=False)
            capture = dict(protocol_id=key, raw_path=rawpath.name,
                raw_sha256=hashlib.sha256(rawpath.read_bytes()).hexdigest(), count=len(rates),
                metadata={k:v for k,v in metadata.items() if k not in ('candles','quote')},
                captured_at=datetime.now(UTC).isoformat())
            memory.record_project_data('agent_h1_extended_capture', key, capture)
        import numpy as np
        rawpath = output / capture['raw_path']
        if hashlib.sha256(rawpath.read_bytes()).hexdigest() != capture['raw_sha256']:
            raise ValueError('Raw snapshot hash mismatch')
        rates = np.load(rawpath, allow_pickle=False, mmap_mode='r')
        clock = capture['metadata']['source_clock']
        import mt5_provider as provider
        baselines = {}
        for year in range(2021, 2026):
            archive_key = key+':'+str(year)
            try:
                baseline = read('agent_h1_extended_history', archive_key)
            except ValueError:
                start = datetime(year, 1, 1, tzinfo=UTC)-timedelta(days=30)
                end = datetime(year+1, 1, 1, tzinfo=UTC)
                # Coarse source-wall selection is deliberately wider than UTC bounds.
                selected = rates[(rates['time'] >= int((start-timedelta(days=1)).timestamp())) & (rates['time'] < int((end+timedelta(days=1)).timestamp()))]
                normalized = provider._CLOCK.normalize_bars(selected, clock)
                rows = [dict(timestamp=stamp, source_time_epoch=epoch, source_utc_offset_seconds=offset,
                    open=float(rate['open']), high=float(rate['high']), low=float(rate['low']), close=float(rate['close']),
                    volume=float(rate['tick_volume']), spread_pips=float(rate['spread'])/10)
                    for rate,(stamp,epoch,offset) in zip(selected,normalized)]
                if capture['metadata']['pip_size'] != .0001 or capture['metadata']['digits'] != 5:
                    raise ValueError('Unexpected EURUSD pip/point convention')
                rows = closed_rows(rows, 'M5', start=start, as_of=end)
                if not rows:
                    raise ValueError('Missing requested year '+str(year))
                for offset in range(0,len(rows),5000):
                    repo.ingest(rows[offset:offset+5000], clock=clock, timeframe='M5')
                frozen = repo.candles(clock_id=clock['clock_id'],timeframe='M5',start=start,as_of=end)
                fields = ('timestamp','source_time_epoch','source_utc_offset_seconds','open','high','low','close','volume','spread_pips')
                canonical = lambda seq:[{field:row.get(field) for field in fields} for row in seq]
                if canonical(frozen) != canonical(rows):
                    raise ValueError('Archive revisions differ from immutable MT5 capture')
                measured = summarize(frozen, 'M5', start=start, as_of=end, days=(end-start).days)
                baseline = dict(version='h1-extended-history-v1', baseline_id=archive_key, year=year,
                    start=start.isoformat(), first_label_at=datetime(year,1,1,tzinfo=UTC).isoformat(), as_of=end.isoformat(),
                    days=(end-start).days, clock_id=clock['clock_id'], source_clock=clock,
                    timeframes={'M5':measured}, source_capture=key)
                memory.record_project_data('agent_h1_extended_history', archive_key, baseline)
            baselines[str(year)] = baseline
            emit(dict(stage='year_frozen', year=year, bars=baseline['timeframes']['M5']['statistics']['bars'], coverage=baseline['timeframes']['M5']['coverage']))
        # Freeze all years and source integrity before any outcome calculation.
        memory.record_project_data('agent_h1_extended_manifest', key, dict(baselines=baselines))
        results, stresses, all_signals, all_candles = {}, {}, [], []
        for year, baseline in baselines.items():
            _, rows = repo.frozen_candles(baseline, record_type='agent_h1_extended_history')
            candles = candles_from(rows)
            start, end = utc(baseline['first_label_at']), utc(baseline['as_of'])
            signals = generate(candles, start, emit)
            memory.record_project_data('agent_h1_extended_signals', key+':'+year, dict(signals=signals))
            kwargs = dict(start=start,end=end,holding_bars=288,purge_hours=24,session_buffer_minutes=5)
            results[year] = simulate(signals,candles,**kwargs)
            stresses[year] = simulate(signals,candles,stress=True,**kwargs)
            emit(dict(stage='year_complete',year=year,closed=results[year]['closed_trades'],net=results[year]['net_pnl'],clean=clean(results[year])))
            all_signals.extend(signals)
            # Disjoint UTC years plus the first warmup only; no duplicate overlapping December bars.
            all_candles.extend(c for c in candles if c.timestamp >= start or not all_candles)
        # A fresh pooled replay preserves daily/account limits and positions across year boundaries.
        for name,start,end in [('qualification_2021_2023',datetime(2021,1,1,tzinfo=UTC),datetime(2024,1,1,tzinfo=UTC)),
                               ('all_additional',datetime(2021,1,1,tzinfo=UTC),datetime(2026,1,1,tzinfo=UTC))]:
            kwargs = dict(start=start,end=end,holding_bars=288,purge_hours=24,session_buffer_minutes=5)
            results[name] = simulate(all_signals,all_candles,**kwargs)
            stresses[name] = simulate(all_signals,all_candles,stress=True,**kwargs)
        gates = {name:qualified(results[name],stresses[name],minimum) for name,minimum in
                 [('qualification_2021_2023',50),('2024',20),('2025',20)]}
        report = dict(protocol=protocol, baselines=baselines, results=results, stress=stresses,
            gates=gates, historical_criteria_passed=all(gates.values()),
            uncertainty=uncertainty(results['all_additional']['trades']), independent_prospective_validation=False,
            data_ready=all(b['timeframes']['M5']['ready'] for b in baselines.values()),
            orders_sent=0,live_policy_changed=False,completed_at=datetime.now(UTC).isoformat())
        report['report_id'] = fingerprint(report)
        memory.record_project_data('agent_h1_extended_experiment', report['report_id'], report)
        path = output / ('h1-extended-'+report['report_id'][:12]+'.json')
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        emit(dict(stage='complete',report_id=report['report_id'],gates=gates,data_ready=report['data_ready'],
            results={k:{f:v[f] for f in ('closed_trades','wins','losses','net_pnl','profit_factor','censored_trades','account_locked','unresolved_position')} for k,v in results.items()}))
    finally:
        memory.close()


if __name__ == '__main__':
    main()
