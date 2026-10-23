"""Corroborate M1 hypotheses with closed native MT5 context bars, not filled M1 gaps."""
from collections import deque
from datetime import datetime, timedelta, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys
from functools import lru_cache

from run_m1_context_experiment import ROOT, PROFILES, FAMILIES, read, proposals, simulate

UTC = timezone.utc
SOURCE = '4b39756aa50c48dde15f7a1cf8b9798885f2851e14ee999e0d6182060ea1d0fe'
PERIODS = {'M1': 60, 'M5': 300, 'M10': 600, 'M15': 900, 'H1': 3600, 'H4': 14400}


@lru_cache(maxsize=16384)
def native_gap(before, after, seconds):
    """A broker H4 phase shift over a closed DST weekend is not a data hole."""
    from aurelia_fx.broker_calendar import slot_tradable, unexpected_broker_gap
    from types import SimpleNamespace
    delta = (after-before).total_seconds()
    if delta <= 0 or delta % 60:
        return True
    if delta % seconds == 0:
        return unexpected_broker_gap(SimpleNamespace(timestamp=before), SimpleNamespace(timestamp=after), seconds)
    if delta < seconds:
        return True
    stamp = before+timedelta(seconds=seconds)
    while stamp < after:
        if slot_tradable(stamp, 60):
            return True
        stamp += timedelta(minutes=1)
    return False


def generate(candles, contexts, start, emit=lambda _: None):
    """Independent closed contexts; entry M1 gaps still invalidate execution patterns.

    Missing whole native context bars invalidate that context for 60 bars.
    A native OHLC bar with no quotes in one of its minutes is not synthesized.
    It is the broker's observed OHLC, not proof of complete intrabar quotes.
    """
    from aurelia_fx.agent_research import SESSIONS
    from aurelia_fx.broker_calendar import unexpected_broker_gap, slot_tradable
    from aurelia_fx.sessions import SessionEngine
    sessions = SessionEngine(SESSIONS)
    history = {tf: deque(maxlen=300) for tf in PERIODS}
    position = {tf: 0 for tf in contexts}
    valid = {tf: False for tf in contexts}
    cache, seen = {}, set()
    pools = {p+':'+f: [] for p in PROFILES for f in FAMILIES}
    previous = None
    for i, bar in enumerate(candles):
        if i % 25000 == 0: emit(dict(stage='native_generating', processed=i))
        if previous and unexpected_broker_gap(previous, bar, 60):
            history['M1'].clear()
        history['M1'].append(bar); previous = bar
        known = bar.timestamp+timedelta(minutes=1)
        for tf, source in contexts.items():
            seconds = PERIODS[tf]; index = position[tf]
            changed = False
            while index < len(source) and source[index].timestamp+timedelta(seconds=seconds) <= known:
                history[tf].append(source[index]); index += 1; changed = True
            position[tf] = index
            if changed:
                recent = list(history[tf])[-60:]
                valid[tf] = len(recent) >= 60 and not any(native_gap(a.timestamp, b.timestamp, seconds)
                    for a, b in zip(recent, recent[1:]))
        if known < start or not slot_tradable(known, 60): continue
        active = sessions.identify(known).active_sessions
        if not active: continue
        h = {tf: tuple(values) for tf, values in history.items()}
        if len(cache) > 1000: cache.clear()
        for profile, (context, confirm, execution) in PROFILES.items():
            if not valid[context] or not valid[confirm]: continue
            if any(not h[tf] or not 0 <= (known-h[tf][-1].timestamp).total_seconds()-PERIODS[tf] < PERIODS[tf]
                   for tf in (context, confirm)):
                continue
            if not h[execution] or h[execution][-1].timestamp+timedelta(seconds=PERIODS[execution]) != known:
                continue
            for family, item in proposals(h, profile, cache).items():
                c = item.pop('candidate'); event = (profile, family, item['event'], c.side)
                if event in seen: continue
                seen.add(event); sid = 'native:'+profile+':'+family+':'+known.isoformat()
                pools[profile+':'+family].append(dict(sample_id=sid, signal_at=known.isoformat(), entry_at=known.isoformat(),
                    snapshot=dict(snapshot_id=sid, session=list(active), regime='NATIVE_CONTEXT_ALIGNED', research_context=item),
                    candidate=dict(side=c.side, entry=c.entry, stop=c.stop, target=c.target,
                        expires_at=c.expires_at.isoformat(), evidence=list(c.evidence))))
    return pools


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.core import utc
    from aurelia_fx.domain import Candle
    from run_h1_extended_validation import qualified, uncertainty
    import numpy as np
    import psutil
    import mt5_provider as provider
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume')
    parser.add_argument('--capture-only', action='store_true')
    parser.add_argument('--capture-from', help='Reuse a sealed native raw snapshot; no outcome reuse')
    args = parser.parse_args()
    try: psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform=='win32' else 10)
    except (psutil.Error, AttributeError): pass
    m = open_memory(); output = ROOT/'data/reports'
    emit = lambda x: print(json.dumps(x, ensure_ascii=True), flush=True)
    files = sorted((ROOT/'src').rglob('*.py'))+[ROOT/n for n in ('run_m1_native_context_experiment.py', 'run_m1_context_experiment.py', 'mt5_provider.py')]
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    try:
        parent = read(m, 'agent_m1_context_protocol', SOURCE)
        source = read(m, 'agent_m1_context_capture', SOURCE)
        quality = read(m, 'agent_m1_context_data_quality', SOURCE)
        if args.resume:
            protocol = read(m, 'agent_m1_native_protocol', args.resume)
            if protocol['code_hashes'] != hashes: raise ValueError('Implementation changed')
        else:
            protocol = dict(version='native-m1-contexts-v2', registered_at=datetime.now(UTC).isoformat(), capture_from=args.capture_from,
                source_m1_protocol=SOURCE, parent_rules=parent, code_hashes=hashes,
                reason='Data quality before financial results:232M1gap intervals,mostlyrollover/holidays;strictM1resets may suppress longcontrols. Use native contextbars without changingM1execution or repairingmissingquotes.',
                signal='Same2families/4profiles/alignment/geometry; nativeclosedM5/M10/M15/H1/H4;context60bars must have no missing tradable wholeTFbars;lastcontext close less than1TFold;executionlast64barscontiguous.',
                primary='Native-context comparison is primary for requested MT5timeframe hypothesis; strict complete-M1 aggregation remains conservative secondary,not suppressed. This amendment was motivated by dataquality not financialresults.',
                comparison='Exactly parent60minute exits,risk,fees,split,selection andchecks. NativeM1prices always execute everyprofile. No new numeric tuning.',
                native='NativecontextOHLC only observedbrokerquotes; missingminutes insideTF not filled and do not establish completeintrabarpath.',
                dst='Allow nativeH4 phase shifts only when the entire interval afterpreviousnominalclose to nextopen is closed under explicitbrokercalendar;no weekdayphasegap ignored.',
                orders_sent=0, automatic_promotion=False, live_policy_changed=False)
            protocol['protocol_id'] = fingerprint(protocol)
            m.record_project_data('agent_m1_native_protocol', protocol['protocol_id'], protocol)
        key = protocol['protocol_id']; emit(dict(stage='native_protocol_registered', protocol_id=key))
        raw_path = output/source['raw_path']
        if hashlib.sha256(raw_path.read_bytes()).hexdigest() != source['raw_sha256']: raise ValueError('M1hash mismatch')
        raw = np.load(raw_path, mmap_mode='r', allow_pickle=False)
        if args.capture_from and not args.resume:
            previous = read(m, 'agent_m1_native_capture', args.capture_from)
            m.record_project_data('agent_m1_native_capture', key,
                dict(previous, protocol_id=key, reused_from=args.capture_from))
        try:
            capture = read(m, 'agent_m1_native_capture', key)
        except ValueError:
            datasets = {}
            with provider._LOCK:
                try:
                    terminal = provider._open_terminal()
                    if any(terminal[k] != source[k] for k in ('broker', 'server')): raise ValueError('Broker changed')
                    a = datetime.fromtimestamp(int(raw[0]['time']), UTC)-timedelta(days=30)
                    b = datetime.fromtimestamp(int(raw[-1]['time']), UTC)+timedelta(days=1)
                    for tf in PERIODS:
                        if tf == 'M1': continue
                        values = provider.mt5.copy_rates_range('EURUSD', provider._TIMEFRAMES[tf], a, b)
                        if values is None or not len(values): raise ValueError('Nativehistory unavailable '+tf)
                        if np.any(np.diff(values['time']) <= 0): raise ValueError('Nativebars out of order')
                        path = output/('m1-native-'+key[:12]+'-'+tf+'.npy'); np.save(path, values, allow_pickle=False)
                        datasets[tf] = dict(path=path.name, raw_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), count=len(values))
                        emit(dict(stage='native_capture', timeframe=tf, bars=len(values)))
                finally: provider.mt5.shutdown()
            capture = dict(protocol_id=key, clock=source['clock'], datasets=datasets, captured_at=datetime.now(UTC).isoformat())
            m.record_project_data('agent_m1_native_capture', key, capture)
        if args.capture_only: emit(dict(stage='native_capture_complete', protocol_id=key)); return
        # Verify normalized M1 directly against the already frozen PostgreSQL archive.
        archive = read(m, 'agent_m1_context_history', SOURCE)
        end = utc(archive['as_of']); digest = hashlib.sha256(); candles = []
        for offset in range(0, len(raw), 5000):
            values = raw[offset:offset+5000]; normalized = provider._CLOCK.normalize_bars(values, source['clock'])
            for r, (stamp, epoch, shift) in zip(values, normalized):
                t = utc(stamp)
                if t+timedelta(minutes=1) > end: continue
                row = dict(timestamp=stamp, source_time_epoch=epoch, source_utc_offset_seconds=shift,
                    open=float(r['open']), high=float(r['high']), low=float(r['low']), close=float(r['close']),
                    volume=float(r['tick_volume']), spread_pips=float(r['spread'])/10)
                digest.update((json.dumps(row, sort_keys=True)+'\n').encode())
                candles.append(Candle(t, *(row[k] for k in ('open','high','low','close','volume','spread_pips'))))
        if len(candles) != archive['rows'] or digest.hexdigest() != archive['normalized_sha256']: raise ValueError('M1frozen archive mismatch')
        contexts = {}
        for tf, item in capture['datasets'].items():
            path = output/item['path']
            if hashlib.sha256(path.read_bytes()).hexdigest() != item['raw_sha256']: raise ValueError('Nativehash mismatch '+tf)
            values = np.load(path, allow_pickle=False); stamps = provider._CLOCK.normalize_bars(values, capture['clock'])
            contexts[tf] = [Candle(utc(stamp), *(float(r[k]) for k in ('open','high','low','close','tick_volume')), float(r['spread'])/10)
                            for r, (stamp, _, _) in zip(values, stamps) if utc(stamp)+timedelta(seconds=PERIODS[tf]) <= end]
            # Separate protocol-bound records preserve native bars in PostgreSQL,
            # without claiming they were synthesized from M1 or rewriting its archive.
            for offset in range(0, len(contexts[tf]), 5000):
                m.record_project_data('agent_m1_native_context_chunk', key+':'+tf+':'+str(offset),
                    dict(protocol_id=key, timeframe=tf, clock_id=capture['clock']['clock_id'],
                         candles=[c.as_dict() for c in contexts[tf][offset:offset+5000]]))
        start = utc(archive['start'])+timedelta(days=7)
        windows = dict(development=(start, datetime(2026,1,1,tzinfo=UTC)),
            check=(datetime(2026,1,1,tzinfo=UTC), datetime(2026,7,1,tzinfo=UTC)),
            final=(datetime(2026,7,1,tzinfo=UTC), end))
        if any((b-a).days < 60 for a,b in windows.values()): raise ValueError('Insufficient split coverage')
        pools = generate(candles, contexts, start, emit)
        m.record_project_data('agent_m1_native_signals', key, dict(samples=pools))
        emit(dict(stage='native_signals_sealed', counts={a:len(s) for a,s in pools.items()}))
        results = {}; selected = None
        for period, (a,b) in windows.items():
            results[period] = {}
            for arm, samples in pools.items():
                r = {label: simulate(samples, candles, start=a, end=b, fee=fee, stress=stress)
                    for label, fee, stress in (('normal',35.,False),('stress',35.,True),('zero_fee_normal',0.,False),('zero_fee_stress',0.,True))}
                results[period][arm] = r
                emit(dict(stage='native_portfolio', period=period, arm=arm, closed=r['normal']['closed_trades'], net=r['normal']['net_pnl'], stress_net=r['stress']['net_pnl']))
            if period == 'development':
                eligible = [(a,r) for a,r in results[period].items() if not a.split(':')[0].endswith('_control') and qualified(r['normal'],r['stress'],50)]
                selected = max(eligible, key=lambda item:(item[1]['normal']['expectancy_usd'],item[0]))[0] if eligible else None
                m.record_project_data('agent_m1_native_selection',key,dict(selected=selected,scope='development_only'))
                emit(dict(stage='native_selection_frozen',selected=selected))
        checks = {p: bool(selected and qualified(results[p][selected]['normal'], results[p][selected]['stress'],20)) for p in ('check','final')}
        report = dict(protocol=protocol, archive=archive, native_capture=capture, data_quality=quality,
            windows={p:[a.isoformat(),b.isoformat()] for p,(a,b) in windows.items()},
            counts={a:len(s) for a,s in pools.items()}, results=results, selected=selected, checks=checks,
            historical_checks_passed=bool(selected and all(checks.values())),
            uncertainty={p:uncertainty(results[p][selected]['normal']['trades']) for p in results} if selected else {},
            independent_prospective_validation=False, orders_sent=0, live_policy_changed=False,
            completed_at=datetime.now(UTC).isoformat())
        report['report_id'] = fingerprint(report)
        m.record_project_data('agent_m1_native_experiment', report['report_id'], report)
        (output/('m1-native-'+report['report_id'][:12]+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
        emit(dict(stage='native_complete', report_id=report['report_id'],selected=selected,checks=checks))
    finally: m.close()


if __name__ == '__main__': main()
