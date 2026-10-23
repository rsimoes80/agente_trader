"""Reproduce fixed research hypotheses on a newly captured calendar-year MT5 archive.

Research only: no orders, training, promotion or live baseline replacement.
The immutable protocol and candle baseline allow interrupted runs to resume.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))


def windows(year, end):
    from aurelia_fx.historical.core import utc
    end = utc(end)
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    if end <= start or end > datetime(year + 1, 1, 1, tzinfo=timezone.utc):
        raise ValueError('Cutoff must fall within the requested year')
    result = {'all': (start, end)}
    for month in range(1, 13):
        a = datetime(year, month, 1, tzinfo=timezone.utc)
        b = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)
        if a < end:
            result[f'{year}-{month:02d}'] = (a, min(b, end))
    return result


def main():
    import psutil
    try:
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == 'win32' else 10)
    except (psutil.Error, AttributeError):
        pass
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import closed_rows, summarize, utc
    from aurelia_fx.source_clock import validate_source_clock
    from aurelia_fx.correction_experiment import generate, PROTOCOL as CORRECTION
    from aurelia_fx.context_experiment import features, passes, ARMS as CONTEXT_ARMS
    from aurelia_fx.trigger_exit_experiment import feature_rows, replay, ARMS as TRIGGER_ARMS
    from aurelia_fx.regime_study import candles_from
    from aurelia_fx.agent_research import intelligence_session
    from aurelia_fx.broker_calendar import unexpected_broker_gap
    from run_context_review import leg

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int, default=2026)
    parser.add_argument('--resume', help='Protocol ID of an interrupted immutable run')
    args = parser.parse_args()
    memory = open_memory()
    repo = HistoricalRepository(memory)
    output = ROOT / 'data/reports'
    output.mkdir(parents=True, exist_ok=True)
    emit = lambda d: print(json.dumps(d, ensure_ascii=True), flush=True)

    def read(kind, key):
        with memory.pool.connection() as c:
            row = c.execute('SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s AND record_key=%s ORDER BY recorded_at LIMIT 1', (kind, key)).fetchone()
        if not row:
            return None
        value = json.loads(row['payload_json'])
        if memory._encode(value)[1] != row['payload_sha256']:
            raise ValueError('Immutable record integrity mismatch')
        return value

    files = ['run_year_validation.py', 'run_context_review.py'] + [
        'src/aurelia_fx/' + f + '.py' for f in
        ('correction_experiment', 'context_experiment', 'trigger_exit_experiment',
         'research_levels', 'agent_strategy', 'agent_research', 'entry_trend')]
    implementation = fingerprint({p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files})
    try:
        if args.resume:
            protocol = read('agent_year_protocol', args.resume)
            if not protocol or protocol['implementation_sha256'] != implementation:
                raise ValueError('Missing protocol or implementation changed; refuse resume')
            baseline = read('agent_year_history', protocol['baseline_id'])
        else:
            from mt5_provider import fetch_history
            now = datetime.now(timezone.utc)
            start = datetime(args.year, 1, 1, tzinfo=timezone.utc)
            if now < start:
                raise ValueError('Requested year has not started')
            end = min(now, datetime(args.year + 1, 1, 1, tzinfo=timezone.utc))
            warmup = start - timedelta(days=30)
            # 100k M5 bars span more than a full FX calendar year, with warmup.
            data = fetch_history('EURUSD', 'M5', 100000, include_current=False)
            clock = validate_source_clock(data, now=datetime.now(timezone.utc))
            if data.get('timeframe') != 'M5' or data.get('symbol') not in {'EURUSD', 'EUR/USD'}:
                raise ValueError('Unexpected source instrument/timeframe')
            rows = closed_rows(data['candles'], 'M5', start=warmup, as_of=end)
            if not rows or utc(rows[0]['timestamp']) > warmup + timedelta(days=4):
                raise ValueError('MT5 did not supply the complete warmup/year; load more history')
            imported = repo.ingest(rows, clock=clock, timeframe='M5')
            frozen = repo.candles(clock_id=clock['clock_id'], timeframe='M5', start=warmup, as_of=end)
            measured = summarize(frozen, 'M5', start=warmup, as_of=end, days=(end - warmup).total_seconds() / 86400)
            if not measured['ready']:
                raise ValueError('Historical coverage insufficient; no performance calculation')
            # Require the frozen archive to match the new terminal response, not an older revision.
            fields = ('timestamp', 'open', 'high', 'low', 'close', 'volume', 'spread_pips')
            canonical = lambda seq: [{k: r.get(k) for k in fields} for r in seq]
            if canonical(frozen) != canonical(rows):
                raise ValueError('New terminal capture differs from frozen PostgreSQL archive')
            baseline = dict(version='calendar-year-research-v1', year=args.year,
                start=warmup.isoformat(), first_label_at=start.isoformat(), as_of=end.isoformat(),
                days=(end - warmup).total_seconds() / 86400, clock_id=clock['clock_id'],
                source_clock=clock, contract=data['symbol_contract'], timeframes={'M5': measured},
                imports=imported, monthly_baseline_replaced=False)
            baseline['baseline_id'] = fingerprint(baseline)
            memory.record_project_data('agent_year_history', baseline['baseline_id'], baseline)
            protocol = dict(version='calendar-year-fixed-hypotheses-v1', baseline_id=baseline['baseline_id'],
                year=args.year, implementation_sha256=implementation,
                registered_at=datetime.now(timezone.utc).isoformat(), lot=.01,
                hypotheses=['strict_current', *TRIGGER_ARMS, *[a for a in CONTEXT_ARMS if a != 'reference'], 'confirmed_pivot_leg'],
                correction_definition=CORRECTION,
                partitions='calendar year to cutoff plus independent monthly accounts; common 120min entry purge',
                comparison='same thresholds, costs and risk; no tuning or automatic promotion',
                scope='fixed technical hypotheses; not full adaptive robot or Timestral weight training',
                data_status='Jan-Oct20 largely previously seen; latest days overlap ongoing prospective study and are NOT an untouched holdout',
                reserved_study='existing Oct22-29 study unchanged, but reused prices cannot be called unseen',
                monthly_accounts='independent balances; sum of monthly outcomes need not equal continuous account',
                live_policy_changed=False, orders_sent=0)
            protocol['protocol_id'] = fingerprint(protocol)
            memory.record_project_data('agent_year_protocol', protocol['protocol_id'], protocol)
        key = protocol['protocol_id']
        emit(dict(stage='registered', protocol_id=key, baseline_id=baseline['baseline_id']))
        _, rows = repo.frozen_candles(baseline, record_type='agent_year_history')
        emit(dict(stage='archive_verified', candles=len(rows), first=rows[0]['timestamp'], last=rows[-1]['timestamp'], coverage=baseline['timeframes']['M5']['coverage']))
        checkpoint = read('agent_year_signals', key)
        if checkpoint:
            samples, diagnostics = checkpoint['samples'], checkpoint['diagnostics']
        else:
            samples, diagnostics = generate(rows, start=baseline['first_label_at'], progress=emit)
            memory.record_project_data('agent_year_signals', key, dict(samples=samples, diagnostics=diagnostics, baseline_id=baseline['baseline_id']))
        emit(dict(stage='signals_sealed', count=len(samples), diagnostics=diagnostics))
        candles = candles_from(rows)
        context = features(samples, candles, progress=emit)
        triggers = feature_rows(samples, candles)
        targets = {utc(s['signal_at']): s for s in samples}
        aggregator = intelligence_session().aggregator
        previous = None
        pivots = {}
        for bar in candles:
            if previous and unexpected_broker_gap(previous, bar, 300):
                aggregator.reset()
            histories = aggregator.add(bar)
            previous = bar
            signal = bar.timestamp + timedelta(minutes=5)
            sample = targets.get(signal)
            if not sample:
                continue
            bars = list(histories['M5'])
            correction = bars[-4:-1]
            adverse = min(b.low for b in correction) if sample['candidate']['side'] == 'long' else max(b.high for b in correction)
            pivots[sample['sample_id']] = leg(bars, sample['candidate']['side'], signal, correction[0].timestamp, 300, adverse)
        if len(pivots) != len(samples):
            raise ValueError('Missing pivot contexts')
        masks = {'strict_current': [s for s in samples if 'strict_current' in s['arms']]}
        masks.update({a: samples for a in TRIGGER_ARMS})
        masks.update({a: [s for s in samples if passes(context[s['sample_id']], a)] for a in CONTEXT_ARMS if a != 'reference'})
        masks['confirmed_pivot_leg'] = [s for s in samples if (v := pivots[s['sample_id']]) is not None and v['amplitude_atr'] is not None and v['amplitude_atr'] >= 1 and 0 < v['retracement'] <= .5]
        results = {}
        for period, (a, b) in windows(protocol['year'], baseline['as_of']).items():
            results[period] = {}
            for arm, selected in masks.items():
                emit(dict(stage='portfolio', period=period, arm=arm))
                r = replay(selected, candles, triggers, arm=arm if arm in TRIGGER_ARMS else 'reference', start=a, end=b, units=protocol['lot'] * baseline['contract']['contract_size'])
                r['arm'] = arm
                r['filled_sides'] = dict(Counter(t['side'] for t in r['trades']))
                results[period][arm] = r
        report = dict(protocol=protocol, baseline=baseline, diagnostics=diagnostics,
            source_signals=len(samples), eligible_samples=samples, context_features=context,
            pivot_contexts=pivots, results=results, completed_at=datetime.now(timezone.utc).isoformat(),
            live_policy_changed=False, orders_sent=0)
        report['report_id'] = fingerprint(report)
        memory.record_project_data('agent_year_experiment', report['report_id'], report)
        path = output / ('year-' + report['report_id'][:12] + '.json')
        path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        emit(dict(stage='complete', report_id=report['report_id'], path=str(path), results={a: {k: v.get(k) for k in ('candidate_signals', 'closed_trades', 'wins', 'losses', 'net_pnl', 'win_rate_pct', 'expectancy_usd', 'account_locked', 'unresolved_position', 'filled_sides')} for a, v in results['all'].items()}))
    finally:
        memory.close()


if __name__ == '__main__':
    main()
