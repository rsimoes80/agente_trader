"""Isolated closed-M1 context research. Never sends broker orders.

Capture is separate from outcomes; --resume reuses the archived protocol/data.
No imports from the native execution gateway and no production configuration writes.
"""
import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
UTC = timezone.utc
PROFILES = {
    'M15_M10_M1': ('M15', 'M10', 'M1'),
    'M10_M5_M1': ('M10', 'M5', 'M1'),
    'H4_H1_M1_control': ('H4', 'H1', 'M1'),
    'H4_H1_M5_control': ('H4', 'H1', 'M5'),
}
FAMILIES = ('trend_pullback', 'breakout_retest')


def read(memory, kind, key):
    with memory.pool.connection() as conn:
        row = conn.execute('SELECT payload_json,payload_sha256 FROM project_records '
                           'WHERE record_type=%s AND record_key=%s ORDER BY recorded_at LIMIT 1',
                           (kind, key)).fetchone()
    if row is None:
        raise ValueError('Missing immutable record: ' + kind)
    value = json.loads(row['payload_json'])
    if memory._encode(value)[1] != row['payload_sha256']:
        raise ValueError('Record integrity mismatch: ' + kind)
    return value


def aggregator():
    from aurelia_fx.calendar_aggregation import CalendarBarAggregator
    from aurelia_fx.trend import HierarchyConfig
    from aurelia_fx.broker_calendar import slot_tradable
    return CalendarBarAggregator(HierarchyConfig('H4', 'H1', 'M15', 'M1'),
        market_calendar=lambda t: slot_tradable(t, 60), extra_periods={'M10': 600, 'M5': 300})


def proposals(histories, profile, bias_cache=None):
    """Original geometry expressed on real execution bars, with two-context alignment."""
    from aurelia_fx.literature_strategies import bias, atr, ema, candidate
    from aurelia_fx.trend import timeframe_seconds
    from aurelia_fx.broker_calendar import unexpected_broker_gap
    context, confirm, execution = PROFILES[profile]
    periods = (context, confirm, execution)
    bars = list(histories.get(execution, ()))
    if not bars:
        return {}
    seconds = timeframe_seconds(execution)
    known = bars[-1].timestamp + timedelta(seconds=seconds)
    for tf in periods:
        if any(b.timestamp + timedelta(seconds=timeframe_seconds(tf)) > known
               for b in histories.get(tf, ())):
            raise ValueError('Unfinished/future context')
    cache = bias_cache if bias_cache is not None else {}
    def direction(tf):
        values = histories.get(tf, ())
        key = (tf, values[-1].timestamp if values else None, len(values))
        if key not in cache:
            cache[key] = bias(list(values))
        return cache[key]
    first, second = direction(context), direction(confirm)
    if first == 0 or first != second or len(bars) < 64:
        return {}
    if any(unexpected_broker_gap(a, b, seconds) for a, b in zip(bars[-64:-1], bars[-63:])):
        return {}
    current, previous = bars[-1], bars[-2]
    if current.spread_pips is None or not 0 <= current.spread_pips <= 2:
        return {}
    scale = atr(bars[:-1])
    if not scale or scale <= 0:
        return {}
    sign = first
    extreme = previous.high if sign == 1 else previous.low
    output = {}
    def add(family, stop, event):
        c = candidate(current, sign, stop, scale, seconds=seconds)
        if c is None:
            return
        if (c.side == 'long') != (first == 1):
            raise ValueError('Counter-context candidate')
        output[family] = dict(candidate=c, event=event,
            known_at=known.isoformat(), context_timeframe=context,
            confirmation_timeframe=confirm, execution_timeframe=execution,
            context_bias=first, confirmation_bias=second,
            context_last=histories[context][-1].timestamp.isoformat(),
            confirmation_last=histories[confirm][-1].timestamp.isoformat())
    fast = ema([b.close for b in bars[-100:-1]], 20)
    current_fast = fast+2/21*(current.close-fast)
    correction = any(sign*(b.close-b.open) < 0 for b in bars[-4:-1])
    touched = min(b.low for b in bars[-4:-1]) <= fast if sign == 1 else max(b.high for b in bars[-4:-1]) >= fast
    if (correction or touched) and sign*(current.close-extreme) > 0 and sign*(current.close-current_fast) > 0 and sign*(current.close-current.open) > 0:
        stop = min(b.low for b in bars[-5:])-.2*scale if sign == 1 else max(b.high for b in bars[-5:])+.2*scale
        add('trend_pullback', stop, previous.timestamp.isoformat())
    for j in range(len(bars)-2, len(bars)-8, -1):
        anchor = bars[j-20:j]
        level = max(b.high for b in anchor) if sign == 1 else min(b.low for b in anchor)
        crossing = sign*(bars[j].close-level) > 0 and sign*(bars[j-1].close-level) <= 0
        tail = bars[j+1:]
        valid = all(sign*(b.close-level) >= -.25*scale for b in tail)
        touch = current.low <= level+.25*scale if sign == 1 else current.high >= level-.25*scale
        if crossing and valid and touch and sign*(current.close-level) > 0 and sign*(current.close-current.open) > 0 and sign*(current.close-extreme) > 0:
            stop = min(b.low for b in tail)-.2*scale if sign == 1 else max(b.high for b in tail)+.2*scale
            add('breakout_retest', stop, bars[j].timestamp.isoformat())
            break
    return output


def generate(candles, first_label, emit=lambda _: None):
    from aurelia_fx.agent_research import SESSIONS
    from aurelia_fx.broker_calendar import unexpected_broker_gap, slot_tradable
    from aurelia_fx.sessions import SessionEngine
    from aurelia_fx.trend import timeframe_seconds
    agg = aggregator()
    sessions = SessionEngine(SESSIONS)
    pools = {p+':'+f: [] for p in PROFILES for f in FAMILIES}
    previous, seen, cache = None, set(), {}
    gaps = 0
    for i, bar in enumerate(candles):
        if i % 25000 == 0:
            emit(dict(stage='generating', processed=i))
        if previous and unexpected_broker_gap(previous, bar, 60):
            agg.reset(); cache.clear(); gaps += 1
        h = agg.add(bar); previous = bar
        known = bar.timestamp+timedelta(minutes=1)
        active = sessions.identify(known).active_sessions
        if known < first_label or not active or not slot_tradable(known, 60):
            continue
        if len(cache) > 1000:
            cache.clear()
        for profile, (_, _, execution) in PROFILES.items():
            if not h[execution] or h[execution][-1].timestamp+timedelta(seconds=timeframe_seconds(execution)) != known:
                continue
            for family, item in proposals(h, profile, cache).items():
                c = item.pop('candidate')
                event = (profile, family, item['event'], c.side)
                if event in seen:
                    continue
                seen.add(event)
                sid = profile+':'+family+':'+known.isoformat()
                pools[profile+':'+family].append(dict(sample_id=sid, signal_at=known.isoformat(),
                    entry_at=known.isoformat(), snapshot=dict(snapshot_id=sid,
                        session=list(active), regime='CONTEXT_ALIGNED', research_context=item),
                    candidate=dict(side=c.side, entry=c.entry, stop=c.stop, target=c.target,
                                   expires_at=c.expires_at.isoformat(), evidence=list(c.evidence))))
    return pools, gaps


def simulate(samples, candles, *, start, end, stress=False, fee=35.):
    from aurelia_fx.agent_research import simulator, request_for, SESSIONS
    from aurelia_fx.broker_calendar import unexpected_broker_gap, slot_tradable
    from aurelia_fx.sessions import SessionEngine
    from aurelia_fx.domain import Candidate
    from aurelia_fx.historical.core import utc
    engine = simulator(1000)
    engine.config = replace(engine.config, bar_seconds=60, max_holding_bars=60,
        commission_per_million_side=fee, slippage_pips=.4 if stress else .2)
    sessions = SessionEngine(SESSIONS)
    selected = [s for s in samples if start <= utc(s['entry_at']) < end-timedelta(hours=1)]
    signals = {utc(s['entry_at']): s for s in selected}
    if len(signals) != len(selected):
        raise ValueError('Duplicate entry timestamps')
    previous = None
    overlaps = skips = 0
    for original in candles:
        if not start <= original.timestamp < end:
            continue
        bar = replace(original, spread_pips=original.spread_pips*1.5) if stress and original.spread_pips is not None else original
        gap = previous is not None and unexpected_broker_gap(previous, bar, 60)
        active = sessions.identify(bar.timestamp).active_sessions
        sample = signals.get(bar.timestamp)
        if sample and not sessions.identify(bar.timestamp+timedelta(minutes=5)).active_sessions:
            skips += 1; sample = None
        if sample and not gap:
            if engine.busy:
                overlaps += 1
            elif not engine.account_locked:
                c = sample['candidate']
                candidate = Candidate(c['side'], c['entry'], c['stop'], c['target'], utc(c['expires_at']), tuple(c['evidence']))
                engine.submit(request_for(dict(candidate=candidate, snapshot=sample['snapshot'],
                    signal_at=sample['signal_at']), sample['sample_id']))
        close = bar.timestamp+timedelta(minutes=1)
        ending = not slot_tradable(close, 60) or not sessions.identify(close+timedelta(minutes=5)).active_sessions
        engine.advance(bar, data_valid=not gap, active_sessions=active,
            force_close_reason='KNOWN_SESSION_END' if ending else None)
        previous = bar
    result = engine.summary()
    trades = [e for e in engine.events if e['status'] == 'closed']
    pnls = [e['financial_result']['net_pnl'] for e in trades]
    losses = -sum(min(p, 0) for p in pnls)
    result.update(signals=len(selected), overlap_skips=overlaps, session_buffer_skips=skips,
        expectancy_usd=sum(pnls)/len(pnls) if pnls else None,
        profit_factor=sum(max(p, 0) for p in pnls)/losses if losses else None,
        win_rate_pct=100*sum(p > 0 for p in pnls)/len(pnls) if pnls else None,
        unresolved_position=engine.busy,
        risk_reasons=dict(Counter(r for e in engine.events if e['status']=='rejected' for r in e.get('risk', {}).get('reasons', []))),
        trades=[{k: e[k] for k in ('decision_id', 'side', 'entry_at', 'observed_at', 'reason', 'financial_result')} for e in trades])
    return result


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import utc, closed_rows, summarize
    from aurelia_fx.regime_study import candles_from
    from run_h1_extended_validation import qualified, uncertainty
    import numpy as np
    import psutil
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume')
    parser.add_argument('--capture-only', action='store_true')
    args = parser.parse_args()
    try:
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform=='win32' else 10)
    except (psutil.Error, AttributeError):
        pass
    memory = open_memory()
    emit = lambda x: print(json.dumps(x, ensure_ascii=True), flush=True)
    output = ROOT/'data/reports'; output.mkdir(exist_ok=True, parents=True)
    files = sorted((ROOT/'src').rglob('*.py'))+[ROOT/'run_m1_context_experiment.py', ROOT/'mt5_provider.py']
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    try:
        if args.resume:
            protocol = read(memory, 'agent_m1_context_protocol', args.resume)
            if protocol['code_hashes'] != hashes:
                raise ValueError('Implementation changed; resume refused')
        else:
            protocol = dict(version='m1-two-contexts-v1', registered_at=datetime.now(UTC).isoformat(),
                profiles=PROFILES, families=FAMILIES, code_hashes=hashes,
                sources=json.loads((ROOT/'data/knowledge/literature_families.json').read_text(encoding='utf-8')),
                hypotheses='Both closed contexts must share EMA20/50/slope3 direction; existing pullback and breakout-retest geometry, ATR14,1ATR minimum stop,quote-aware3R. No H4/H1 gate on short profiles.',
                execution='Original native M1 OHLC next-open,stop-first when ambiguous; common60minute maxhold for all profiles,5minsessionbuffer,1hperiodendpurge. M5control signals on derivedclosedM5 but executes on sameM1.',
                costs='Historical observed spread,.2pipmarketfill slippage,USD35/million/side;stress spread1.5 andslippage.4. Fee0 pairedsensitivityonly,not selection.',
                risk='lot.01,equity10k,.5percent/trade,2percent/day,5percentDD,max5/day,maxspread2pips,minNET_RR2;unchanged',
                capture='Up to499999closedM1 from sameMT5broker; date-specific archived verified NY-close profile;historicalonlynotliveclockverification',
                windows='Warmupfirst7days;developmentbefore2026-01-01;check2026JanJun;final2026Jul through lastcompletecapture. Require >=60calendar days perwindow; report coverage and gaps.',
                selection='Developmentonly >=50closed,net>0,PF>=1.1,stressnet>0,clean;rankexpectancy,freeze beforecheck/final.Noeligible meansnone;reportallarms.',
                validation='Selected arm separately >=20closed,net>0,PF>=1.1,stressnet>0,clean incheckandfinal. Comparecontrols withoutrequiring themtofail.',
                caveat='Historical source dates already studied atcoarserresolution;unseenM1rule outcomes but not genuinelyindependentprospectiveOOS. Noautoactivation or Timestralweightupdate.',
                automatic_promotion=False, orders_sent=0)
            protocol['protocol_id'] = fingerprint(protocol)
            memory.record_project_data('agent_m1_context_protocol', protocol['protocol_id'], protocol)
        key = protocol['protocol_id']; emit(dict(stage='protocol_registered', protocol_id=key))
        try:
            capture = read(memory, 'agent_m1_context_capture', key)
        except ValueError:
            import mt5_provider as provider
            with memory.pool.connection() as conn:
                r = conn.execute("SELECT payload_json FROM project_records WHERE record_type='agent_h1_extended_capture' ORDER BY recorded_at DESC LIMIT 1").fetchone()
            old = json.loads(r['payload_json']); metadata = old['metadata']; clock = metadata['source_clock']
            if clock.get('status') != 'verified' or clock.get('profile') != 'thinkmarkets-ny-close-v1':
                raise ValueError('Historical clock profile unavailable')
            chunks = []
            with provider._LOCK:
                try:
                    terminal = provider._open_terminal()
                    if any(terminal[k] != metadata[k] for k in ('broker', 'server')):
                        raise ValueError('Broker identity changed')
                    symbol = provider._resolve_symbol('EURUSD'); info = provider.mt5.symbol_info(symbol)
                    if info.digits != 5 or info.point != .00001:
                        raise ValueError('Unexpected EURUSD point convention')
                    position, remaining = 1, 499999
                    while remaining:
                        size = min(remaining, 50000)
                        values = provider.mt5.copy_rates_from_pos(symbol, provider.mt5.TIMEFRAME_M1, position, size)
                        if values is None or not len(values):
                            raise RuntimeError('MT5 M1 capture unavailable at '+str(position))
                        chunks.append(values); position += len(values); remaining -= len(values)
                        emit(dict(stage='capture', bars=position-1))
                        if len(values) < size:
                            break
                finally:
                    provider.mt5.shutdown()
            rates = np.concatenate(list(reversed(chunks)))
            if len(rates) < 1000 or np.any(np.diff(rates['time']) <= 0):
                raise ValueError('Invalid/disordered M1 capture')
            path = output/('m1-context-raw-'+key[:12]+'.npy'); np.save(path, rates, allow_pickle=False)
            capture = dict(raw_path=path.name, raw_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                count=len(rates), captured_at=datetime.now(UTC).isoformat(), clock=clock,
                timestamp_semantics='UTC normalized using date-specific archived historical profile;not a current live quote validation',
                broker=metadata['broker'], server=metadata['server'])
            memory.record_project_data('agent_m1_context_capture', key, capture)
        if args.capture_only:
            emit(dict(stage='capture_complete', protocol_id=key, bars=capture['count'])); return
        path = output/capture['raw_path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != capture['raw_sha256']:
            raise ValueError('Raw capture hash mismatch')
        rates = np.load(path, allow_pickle=False, mmap_mode='r')
        import mt5_provider as provider
        repo = HistoricalRepository(memory)
        try:
            archive = read(memory, 'agent_m1_context_history', key)
        except ValueError:
            # Bound working memory and batch inserts; the raw snapshot is also retained.
            first = last = None; row_hash = hashlib.sha256(); count = 0
            end = utc(capture['captured_at']).replace(second=0, microsecond=0)
            for offset in range(0, len(rates), 5000):
                values = rates[offset:offset+5000]
                normalized = provider._CLOCK.normalize_bars(values, capture['clock'])
                rows = [dict(timestamp=stamp, source_time_epoch=epoch, source_utc_offset_seconds=shift,
                    open=float(r['open']), high=float(r['high']), low=float(r['low']), close=float(r['close']),
                    volume=float(r['tick_volume']), spread_pips=float(r['spread'])/10)
                    for r, (stamp, epoch, shift) in zip(values, normalized)]
                rows = closed_rows(rows, 'M1', start=utc(rows[0]['timestamp']), as_of=end)
                if not rows:
                    continue
                repo.ingest(rows, clock=capture['clock'], timeframe='M1')
                for row in rows:
                    row_hash.update((json.dumps(row, sort_keys=True)+'\n').encode())
                first = first or rows[0]['timestamp']; last = rows[-1]['timestamp']; count += len(rows)
                if offset % 50000 == 0: emit(dict(stage='archiving', bars=count))
            archive = dict(protocol_id=key, clock_id=capture['clock']['clock_id'], start=first,
                as_of=(utc(last)+timedelta(minutes=1)).isoformat(), rows=count, normalized_sha256=row_hash.hexdigest(),
                archived_at=datetime.now(UTC).isoformat())
            memory.record_project_data('agent_m1_context_history', key, archive)
        rows = repo.candles(clock_id=archive['clock_id'], timeframe='M1', start=archive['start'],
                            as_of=archive['as_of'], known_by=archive['archived_at'])
        # Select exactly this source capture; exclude older overlapping archive rows.
        raw_stamps = {s for s, _, _ in provider._CLOCK.normalize_bars(rates, capture['clock'])}
        rows = [{k: r[k] for k in ('timestamp', 'source_time_epoch', 'source_utc_offset_seconds',
                'open', 'high', 'low', 'close', 'volume', 'spread_pips')} for r in rows if r['timestamp'] in raw_stamps]
        digest = hashlib.sha256()
        for row in rows: digest.update((json.dumps(row, sort_keys=True)+'\n').encode())
        if len(rows) != archive['rows'] or digest.hexdigest() != archive['normalized_sha256']:
            raise ValueError('Frozen normalized M1 archive mismatch')
        del raw_stamps
        candles = candles_from(rows); del rows
        start = utc(archive['start'])+timedelta(days=7); end = utc(archive['as_of'])
        boundaries = dict(development=(start, datetime(2026, 1, 1, tzinfo=UTC)),
            check=(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)),
            final=(datetime(2026, 7, 1, tzinfo=UTC), end))
        if any((b-a).days < 60 for a, b in boundaries.values()):
            raise ValueError('Insufficient calendar coverage for preregistered windows; do not silently change split')
        coverage = summarize([c.as_dict() for c in candles], 'M1', start=archive['start'], as_of=end, days=(end-utc(archive['start'])).days)
        pools, gaps = generate(candles, start, emit)
        memory.record_project_data('agent_m1_context_signals', key, dict(samples=pools, unexpected_gap_resets=gaps))
        emit(dict(stage='signals_sealed', counts={k: len(v) for k, v in pools.items()}, gaps=gaps))
        results = {}; selected = None
        for period, (a, b) in boundaries.items():
            results[period] = {}
            for arm, samples in pools.items():
                pair = {label: simulate(samples, candles, start=a, end=b, stress=stress, fee=fee)
                        for label, stress, fee in (('normal', False, 35.), ('stress', True, 35.),
                            ('zero_fee_normal', False, 0.), ('zero_fee_stress', True, 0.))}
                results[period][arm] = pair
                emit(dict(stage='portfolio', period=period, arm=arm, closed=pair['normal']['closed_trades'],
                          net=pair['normal']['net_pnl'], stress_net=pair['stress']['net_pnl']))
            if period == 'development':
                eligible = [(arm, r) for arm, r in results[period].items()
                    if not arm.split(':')[0].endswith('_control') and qualified(r['normal'], r['stress'], 50)]
                selected = max(eligible, key=lambda item: (item[1]['normal']['expectancy_usd'], item[0]))[0] if eligible else None
                memory.record_project_data('agent_m1_context_selection', key, dict(selected=selected, scope='development_only'))
                emit(dict(stage='selection_frozen', selected=selected))
        checks = {p: bool(selected and qualified(results[p][selected]['normal'], results[p][selected]['stress'], 20))
                  for p in ('check', 'final')}
        report = dict(protocol=protocol, archive=archive, coverage=coverage, unexpected_gap_resets=gaps,
            counts={k: len(v) for k, v in pools.items()}, results=results, selected=selected, checks=checks,
            historical_checks_passed=bool(selected and all(checks.values())),
            uncertainty={p: uncertainty(results[p][selected]['normal']['trades']) for p in results} if selected else {},
            independent_prospective_validation=False, orders_sent=0, live_policy_changed=False,
            completed_at=datetime.now(UTC).isoformat())
        report['report_id'] = fingerprint(report)
        memory.record_project_data('agent_m1_context_experiment', report['report_id'], report)
        (output/('m1-context-'+report['report_id'][:12]+'.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
        emit(dict(stage='complete', report_id=report['report_id'], selected=selected, checks=checks))
    finally:
        memory.close()


if __name__ == '__main__':
    main()
