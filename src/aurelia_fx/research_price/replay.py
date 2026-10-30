"""Deterministic retrospective runner for one sealed price-only protocol."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
import math
from pathlib import Path

from ..offline_integrity import canonical, checked_files, decode, safe_file, sha256
from .context import PriceContext, candidate, closed_at, utc
from .execution import advance, censored, fill

BRANCH = 'PRICE_ONLY_EXPERIMENTAL_NOT_LITERAL_VOLUME_RULE'


def validate_protocol(p):
    if (p.get('schema_version') != 1 or p.get('branch') != BRANCH or p.get('direction') != 'long_only'
            or p.get('trading_authority') is not False or p.get('model_inference') is not False
            or p.get('bar_seconds') != 300):
        raise ValueError('UNSUPPORTED_RESEARCH_PROTOCOL')
    for key in ['pivot_window','entry_ttl_bars','max_holding_bars','warmup_contiguous_m5','units']:
        if type(p.get(key)) is not int or p[key] < 1:
            raise ValueError('INVALID_PROTOCOL_INTEGER: '+key)
    if p['warmup_contiguous_m5'] < max(22,2*p['pivot_window']+1):
        raise ValueError('WARMUP_TOO_SHORT')
    for value in [p['pip_size'],p['tick_size']]:
        if not isinstance(value,(int,float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('INVALID_PRICE_UNIT')
    for key in ['slippage_pips_per_market_side','commission_usd_per_million_per_side','swap_financing_usd']:
        value=p['costs'][key]
        if not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0:
            raise ValueError('INVALID_COST')
    if p['costs']['swap_financing_usd'] != 0:
        raise ValueError('ONLY_INTRADAY_ZERO_FINANCING_SCENARIO_SUPPORTED')
    s=p['session']
    if not 0 <= s['start_hour_utc'] < s['end_hour_utc'] <= 24 or s['force_flat_at_end'] is not True:
        raise ValueError('INVALID_INTRADAY_SESSION')
    if not s['weekdays'] or any(type(d) is not int or not 0<=d<=6 for d in s['weekdays']):
        raise ValueError('INVALID_WEEKDAYS')
    previous=None
    for window in p['partitions']:
        start,end=utc(window['start']),utc(window['end'])
        if start>=end or (previous is not None and start<previous):
            raise ValueError('OVERLAPPING_OR_INVALID_PARTITIONS')
        previous=end


def load_rows(p):
    root=Path(p['source']['bundle'])
    index_raw=safe_file(root,'artifact_hashes.json').read_bytes()
    if sha256(index_raw)!=p['source']['index_sha256']:
        raise ValueError('INPUT_INDEX_CHANGED')
    index=decode(index_raw);snapshot=checked_files(root,index)
    result=[]
    for name,expected in p['source']['files'].items():
        if index.get(name)!=expected or name not in snapshot:
            raise ValueError('SOURCE_NOT_SEALED')
        for line in snapshot[name].splitlines():
            if not line.strip():
                continue
            row=decode(line)
            if row.get('timeframe')!='M5' or any(row.get(k)!=p['source'][k]
                    for k in ('source','clock_id','symbol','time_contract')):
                raise ValueError('MIXED_SOURCE_CLOCK_OR_CONTRACT')
            if 'expected_close_utc' in row and utc(row['expected_close_utc'])!=closed_at(row):
                raise ValueError('CLOSE_TIME_CONFLICT')
            if int(utc(row['timestamp']).timestamp())%300:
                raise ValueError('UNALIGNED_M5')
            values=[row[k] for k in ('open','high','low','close')]
            if (any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in values)
                    or not row['low']<=min(row['open'],row['close'])<=max(row['open'],row['close'])<=row['high']):
                raise ValueError('INVALID_OHLC')
            spread=row.get('spread_pips')
            if spread is not None and (not isinstance(spread,(int,float)) or not math.isfinite(spread) or spread<0):
                raise ValueError('INVALID_SPREAD')
            if result and utc(row['timestamp'])<=utc(result[-1]['timestamp']):
                raise ValueError('DUPLICATE_OR_UNORDERED_SOURCE')
            result.append(row)
    return result,dict(verified_index_sha256=sha256(index_raw),verified_files=len(snapshot),
        rows=len(result),first_open=result[0]['timestamp'] if result else None,
        last_close=closed_at(result[-1]).isoformat() if result else None,
        rows_sha256=sha256(canonical(result)))


def in_session(at,p):
    t=utc(at);s=p['session']
    return t.weekday() in s['weekdays'] and s['start_hour_utc']<=t.hour<s['end_hour_utc']


def run_window(rows,p,window,*,proposer=candidate):
    selected=[r for r in rows if utc(window['start'])<=utc(r['timestamp'])
              and closed_at(r)<=utc(window['end'])]
    context=PriceContext(p['pivot_window'])
    pending=position=None
    consumed=set();quarantine_until=None
    events=[];trades=[];decisions=[];rejects=Counter()

    def event(kind,at,**kw):
        events.append(dict(kind=kind,at=utc(at).isoformat(),observed_at=utc(at).isoformat(),**kw))

    for i,raw in enumerate(selected):
        bar={**raw,'closed_at':closed_at(raw).isoformat()}
        at,closed=utc(bar['timestamp']),closed_at(bar)
        if i and at-utc(selected[i-1]['timestamp'])!=timedelta(minutes=5):
            event('DATA_GAP',at,previous_open=selected[i-1]['timestamp'])
            if position:
                trades.append(censored(position,'DATA_GAP',bar,p));position=None
            if pending:
                event('CANCEL_PENDING',at,reason='DATA_GAP',signal_at=pending['signal_at']);pending=None
            context=PriceContext(p['pivot_window'])
        # Context here contains only bars closed at/before this opening.
        if pending:
            reason=None
            if at<utc(pending['signal_at']):
                raise ValueError('FILL_BEFORE_SIGNAL')
            if at>=utc(pending['expires_at']):
                reason='EXPIRED'
            elif not in_session(at,p):
                reason='OUTSIDE_SESSION'
            elif not context.h1_bullish:
                reason='H1_NO_LONGER_BULLISH'
            if reason:
                event('CANCEL_PENDING',at,reason=reason,signal_at=pending['signal_at']);pending=None
            else:
                new_position,error=fill(pending,bar,p)
                if error=='WAITING_BREAKOUT':
                    if bar['low']<=pending['stop'] or bar['low']<=pending['protected_low']:
                        event('CANCEL_PENDING',closed,reason='STOP_OR_STRUCTURE_BEFORE_BREAKOUT',signal_at=pending['signal_at'])
                        pending=None
                elif new_position is None:
                    event('CANCEL_PENDING',closed,reason=error,signal_at=pending['signal_at'],
                          bar_open_at=at.isoformat(),event_time_semantics='rejection inferred from OHLC; exact intrabar time unknown');pending=None
                else:
                    position=new_position;consumed.add(position['leg_id']);pending=None
                    event('SCENARIO_ENTRY',closed,signal_at=position['signal_at'],entry=position['entry'],
                          bar_open_at=at.isoformat(),entry_at=at.isoformat() if bar['open']>=position['trigger'] else None,
                          event_time_semantics='open fill only under constant-bar-spread assumption; otherwise intrabar time unknown')
                    if error=='AMBIGUOUS_ENTRY_ORDER':
                        trades.append(censored(position,error,bar,p,bounds=True,uncertain_entry=True))
                        quarantine_until=at+timedelta(seconds=300*p['max_holding_bars'])
                        position=None
        if position:
            force=None
            if not in_session(closed,p):
                force='SESSION_END'
            elif i==len(selected)-1:
                force='PARTITION_END'
            result=advance(position,bar,p,force_reason=force)
            if result:
                trades.append(result);event(result['status'],closed,reason=result['reason'],leg_id=position['leg_id']);position=None
        context.add(bar)
        proposal=None;reason=None
        if position:
            reason='POSITION_OPEN'
        elif pending:
            reason='PENDING_BREAKOUT'
        elif quarantine_until is not None and closed<quarantine_until:
            reason='AMBIGUOUS_ENTRY_QUARANTINE'
        elif not in_session(closed,p):
            reason='OUTSIDE_SESSION'
        elif i==len(selected)-1:
            reason='END_OF_PARTITION'
        else:
            proposal,reason=proposer(context,p)
            if proposal and proposal['leg_id'] in consumed:
                proposal=None;reason='IMPULSE_ALREADY_USED'
        if proposal:
            pending=proposal
            event('CANDIDATE',closed,**proposal)
        else:
            rejects[reason]+=1
        decisions.append(dict(at=closed.isoformat(),h1_bullish=context.h1_bullish,
            contiguous_m5=len(context.bars),decision='CANDIDATE' if proposal else reason,
            leg_id=proposal['leg_id'] if proposal else None))
    if pending:
        event('CANCEL_PENDING',closed_at(selected[-1]),reason='PARTITION_END',signal_at=pending['signal_at'])
    if position:
        raise AssertionError('UNTERMINATED_RESEARCH_EXPOSURE')
    known=[t for t in trades if t['status']=='CLOSED'];unknown=[t for t in trades if t['status']=='CENSORED']
    net=sum(t['net_pnl_usd'] for t in known)
    stats=dict(name=window['name'],bars=len(selected),trades=len(trades),closed=len(known),censored=len(unknown),
        known_outcome_partial_net_usd=net,
        complete_net_usd=net if not unknown else None,
        complete_mean_r=sum(t['result_in_r'] for t in known)/len(known) if known and not unknown else None,
        closed_subset_mean_r=sum(t['result_in_r'] for t in known)/len(known) if known else None,
        profitable_known_trades=sum(t['net_pnl_usd']>0 for t in known),
        negative_known_trades=sum(t['net_pnl_usd']<0 for t in known),
        reason_counts=dict(sorted(rejects.items())),
        interpretation='fixed-size intraday scenario; partial sum is not total portfolio profit if censored; no fresh holdout')
    return dict(summary=stats,trades=trades,events=events,decisions=decisions)


def run(rows,p):
    validate_protocol(p)
    return dict(experiment_id=p['experiment_id'],branch=p['branch'],
        audit_case_id=p['audit_case_id'],audit_as_of=p['audit_as_of'],
        protocol_sha256=sha256(canonical(p)),
        partitions=[run_window(rows,p,w) for w in p['partitions']],
        conclusions=['No parameter tuning, models, production configuration or broker calls.',
                     'Retrospective price-only adaptation; tick volume does not satisfy the original volume rule.',
                     'Costs and bid/ask reconstruction are fixed unverified research assumptions.',
                     'Ambiguous and censored outcomes are retained; no statistical or operational approval.'])
