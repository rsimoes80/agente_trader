"""Offline evidence audit: no orders, fills, P&L, models or operational imports."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path

from .offline_integrity import canonical, checked_files, decode, safe_file, sha256, validate_case

SECONDS = {'M5': 300, 'H1': 3600, 'H4': 14400, 'D1': 86400}
STATES = {'ATENDIDA', 'CONTRARIADA', 'NÃO_MENSURÁVEL', 'NÃO_COMPROVADA'}


def utc(value):
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(dt, datetime) or dt.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return dt.astimezone(timezone.utc)


def iso(value):
    return utc(value).isoformat()


def identity(row):
    # Source and time contract remain distinct even if clock labels coincide.
    return (row.get('source') or 'UNSPECIFIED', row.get('clock_id') or 'UNSPECIFIED',
            row['timeframe'], row.get('symbol') or 'UNSPECIFIED', row.get('time_contract') or 'UNSPECIFIED')


def group_name(key):
    return dict(zip(('source', 'clock_id', 'timeframe', 'symbol', 'time_contract'), key))


def close_at(row):
    result = utc(row['timestamp']) + timedelta(seconds=SECONDS[row['timeframe']])
    if 'expected_close_utc' in row and utc(row['expected_close_utc']) != result:
        raise ValueError('CLOSE_TIME_CONFLICT')
    return result


def prefix(rows, cutoff, *, archive=False):
    """Filter before analysis. Future bars are never used to backfill a prefix."""
    cutoff = utc(cutoff)
    groups = defaultdict(dict)
    for row in rows:
        closed = close_at(row)
        if closed > cutoff:
            continue
        recorded = utc(row['recorded_at_utc']) if row.get('recorded_at_utc') else None
        if archive and (recorded is None or recorded > cutoff):
            continue
        prices = [row[n] for n in ('open', 'high', 'low', 'close')]
        if (any(not isinstance(v, (int, float)) or isinstance(v, bool)
                or not math.isfinite(v) or v <= 0 for v in prices)
                or not row['low'] <= min(row['open'], row['close'])
                <= max(row['open'], row['close']) <= row['high']):
            raise ValueError('INVALID_OHLC')
        key, stamp = identity(row), iso(row['timestamp'])
        if stamp in groups[key]:
            # Exports freeze revisions; no implicit revision selection here.
            raise ValueError('DUPLICATE_PREFIX_BAR')
        groups[key][stamp] = dict(row)
    return {key: [values[t] for t in sorted(values)] for key, values in sorted(groups.items())}


def confirmed_pivots(pivots, cutoff):
    cutoff = utc(cutoff)
    result = []
    for item in pivots:
        if not item.get('confirmed_at'):
            continue
        if utc(item['confirmed_at']) < utc(item['timestamp']):
            raise ValueError('CONFIRMATION_PRECEDES_EXTREME')
        if utc(item['confirmed_at']) <= cutoff:
            result.append(item)
    return sorted(result, key=lambda p: (utc(p['confirmed_at']), utc(p['timestamp']), p['kind']))


def aggregate_utc_m5(rows, cutoff, *, seconds=14400):
    """Complete epoch-anchored buckets per source/clock; never shift native bars.

    This is the complete-bucket rule documented in the frozen trend aggregator.
    Short/session buckets remain incomplete, not repaired with prices or a calendar.
    """
    if seconds < 300 or seconds % 300:
        raise ValueError('INVALID_BUCKET_DURATION')
    grouped = prefix(rows, cutoff)
    result = []
    for key, bars in grouped.items():
        if key[2] != 'M5':
            raise ValueError('M5_REQUIRED')
        if key[1] == 'UNSPECIFIED' or key[4] == 'UNSPECIFIED':
            continue  # An unlabelled clock is not evidence of a common aggregation origin.
        buckets = defaultdict(list)
        for row in bars:
            stamp = utc(row['timestamp'])
            if stamp.timestamp() % 300:
                raise ValueError('UNALIGNED_M5')
            start = int(stamp.timestamp()) // seconds * seconds
            buckets[start].append(row)
        for start, members in sorted(buckets.items()):
            if start + seconds > utc(cutoff).timestamp():
                continue
            expected = list(range(start, start + seconds, 300))
            if [int(utc(b['timestamp']).timestamp()) for b in members] != expected:
                continue
            persisted = [b.get('recorded_at_utc') for b in members]
            result.append(dict(origin=group_name(key),
                timestamp=datetime.fromtimestamp(start, timezone.utc).isoformat(),
                closed_at=datetime.fromtimestamp(start + seconds, timezone.utc).isoformat(),
                open=members[0]['open'], high=max(b['high'] for b in members),
                low=min(b['low'] for b in members), close=members[-1]['close'],
                constituent_count=len(members),
                constituent_sha256=sha256(canonical(members)),
                latest_constituent_persisted_at=max(map(utc, persisted)).isoformat()
                    if all(persisted) else None,
                semantics='posterior reconstruction; not proof of original production path'))
    return result


def _case_rows(case):
    facts = case['facts']
    indices = sorted({int(n.split('.')[1]) for n in facts if n.startswith('M5.')})
    return [dict(timeframe='M5', symbol=case['symbol'],
                 **{n: facts[f'M5.{i}.{n}'] for n in ('timestamp', 'open', 'high', 'low', 'close')},
                 **{n: facts[f'M5.{i}.{n}'] for n in ('volume', 'spread_pips') if f'M5.{i}.{n}' in facts})
            for i in indices]


def _case_pivots(case):
    stem = 'system.market_structure.recent_swings.'
    facts = case['facts']
    indices = sorted({int(n[len(stem):].split('.')[0]) for n in facts if n.startswith(stem)})
    return [{n: facts[stem + str(i) + '.' + n] for n in ('timestamp', 'confirmed_at', 'kind', 'price')
             if stem + str(i) + '.' + n in facts} for i in indices]


def _summary(groups):
    return [dict(identity=group_name(k), bars=len(v), first_open=iso(v[0]['timestamp']),
                 last_open=iso(v[-1]['timestamp']), last_close=iso(close_at(v[-1])))
            for k, v in groups.items()]


def investigate_h4(market_groups, archive_groups, case):
    findings = []
    context_close = case['facts'].get('system.macro_trend.timestamp_utc')
    for key, native in market_groups.items():
        if key[2] != 'H4':
            continue
        m5key = (key[0], key[1], 'M5', key[3], key[4])
        bases = market_groups.get(m5key, [])
        rebuilt = aggregate_utc_m5(bases, case['as_of'])
        expected = utc(context_close) if context_close else None
        matching = [b for b in rebuilt if expected and utc(b['closed_at']) == expected]
        latest = native[-1]
        raw_contract = []
        for row in native:
            if 'source_time_epoch' in row and 'source_utc_offset_seconds' in row:
                # Check the declared normalization; never apply it to timestamp again.
                raw_contract.append(int(row['source_time_epoch']) - int(row['source_utc_offset_seconds'])
                                    == int(utc(row['timestamp']).timestamp()))
        native_closes = {iso(close_at(b)) for b in native}
        archive_rebuilt = aggregate_utc_m5(archive_groups.get(m5key, []), case['as_of'])
        findings.append(dict(identity=group_name(key),
            case_context_timestamp=context_close,
            context_semantics='closure under frozen code; historical path not proved',
            native_latest_open=iso(latest['timestamp']), native_latest_close=iso(close_at(latest)),
            native_latest_persisted_at=latest.get('recorded_at_utc'),
            native_latest_source_time_epoch=latest.get('source_time_epoch'),
            native_latest_source_utc_offset_seconds=latest.get('source_utc_offset_seconds'),
            native_utc_phase_seconds=sorted({int(utc(b['timestamp']).timestamp()) % 14400 for b in native}),
            raw_epoch_offset_checks=dict(checked=len(raw_contract), matching=sum(raw_contract)),
            native_bar_with_context_close=bool(expected and iso(expected) in native_closes),
            utc_epoch_bucket_phase_seconds=0,
            utc_complete_buckets=len(rebuilt),
            utc_latest_bucket=rebuilt[-1] if rebuilt else None,
            utc_bucket_with_context_close=matching,
            archive_inputs_reconstruct_context_bucket=any(expected and utc(b['closed_at']) == expected
                                                          for b in archive_rebuilt),
            inference=('Different native broker-wall and UTC bucket origins are consistent with the timestamps; '
                       'matching a closure does not prove origin, original aggregation, trend state or agent availability.'),
            status='NÃO_COMPROVADA'))
    return findings


def diagnose(case, archive_rows, market_rows, *, case_records=()):
    """Pure cutoff result; input seals and execution metadata belong outside this projection."""
    validate_case(case)
    cut = utc(case['as_of'])
    archived = prefix(archive_rows, cut, archive=True)
    market = prefix(market_rows, cut)
    case_bars = _case_rows(case)
    if any(close_at(b) > cut for b in case_bars):
        raise ValueError('CASE_CONTAINS_OPEN_OR_FUTURE_BAR')
    pivots = _case_pivots(case)
    usable = confirmed_pivots(pivots, cut)
    facts = case['facts']
    records = sorted({iso(r['recorded_at_utc']) for r in case_records
                      if r.get('equals_frozen') is True and r.get('hash_verified') is True})
    comparisons = []
    timeline = []

    def event(at, kind, evidence, **extra):
        timeline.append(dict(at=iso(at), kind=kind, evidence=evidence, **extra))

    for row in case_bars:
        event(close_at(row), 'CANDLE_CLOSED', f"case:M5:{iso(row['timestamp'])}",
              open_at=iso(row['timestamp']), meaning='nominal closure, not received_at')
    for item in pivots:
        event(item['timestamp'], 'PIVOT_EXTREME', 'case:market_structure.recent_swings',
              price=item['price'], kind_of_pivot=item['kind'], usable_as_confirmed=False)
        if item.get('confirmed_at'):
            event(item['confirmed_at'], 'PIVOT_CONFIRMED', 'case:market_structure.recent_swings',
                  extreme_at=iso(item['timestamp']), logical_confirmation_by_cut=utc(item['confirmed_at']) <= cut,
                  agent_available_at=None, meaning='declared confirmation, not proof of actual reception')
    for record in records:
        event(record, 'CASE_PERSISTED', 'observador/case_db_identity.json',
              at_or_before_cut=utc(record) <= cut)
    event(cut, 'CASE_AS_OF', 'case.json', meaning='fixed reference; never moved to match persistence')

    fields = ('open', 'high', 'low', 'close', 'volume', 'spread_pips')
    for key, rows in market.items():
        if key[2] != 'M5':
            continue
        lookup = {iso(b['timestamp']): b for b in rows}
        known = {iso(b['timestamp']): b for b in archived.get(key, [])}
        for bar in case_bars:
            stamp = iso(bar['timestamp'])
            match = lookup.get(stamp)
            comparison = dict(identity=group_name(key), timestamp=stamp,
                represented_in_case=True, archive_known_by_cut=stamp in known,
                present_in_market_prefix=match is not None,
                different_fields=[n for n in fields if n in bar and match and bar[n] != match.get(n)],
                archive_persisted_at=iso(match['recorded_at_utc']) if match and match.get('recorded_at_utc') else None,
                case_persisted_at=records, agent_availability='NÃO_COMPROVADA',
                warning='Later archive persistence does not prove late arrival at the agent; no received_at evidence.')
            comparisons.append(comparison)
            if match and match.get('recorded_at_utc'):
                event(match['recorded_at_utc'], 'ARCHIVE_PERSISTED', str(group_name(key)),
                      candle_open_at=stamp, at_or_before_cut=utc(match['recorded_at_utc']) <= cut,
                      meaning='archive persistence only')
    for role in ('context_trend', 'macro_trend'):
        stamp = facts.get(f'system.{role}.timestamp_utc')
        if stamp:
            event(stamp, 'CONTEXT_DECLARED_CLOSE', f'case:system.{role}',
                  meaning='closure semantics in frozen code; original provenance not proved')
    h4 = investigate_h4(market, archived, case)
    for finding in h4:
        origin = str(finding['identity'])
        event(finding['native_latest_close'], 'NATIVE_H4_CLOSED', origin,
              open_at=finding['native_latest_open'], meaning='native archive nominal close')
        if finding['native_latest_persisted_at']:
            event(finding['native_latest_persisted_at'], 'NATIVE_H4_PERSISTED', origin,
                  meaning='archive persistence; not agent reception')
        for bucket in finding['utc_bucket_with_context_close']:
            event(bucket['closed_at'], 'RECONSTRUCTED_UTC_H4_CLOSE', origin,
                  open_at=bucket['timestamp'], constituent_count=bucket['constituent_count'],
                  meaning='posterior complete-bucket reconstruction, not original context provenance')
            if bucket['latest_constituent_persisted_at']:
                event(bucket['latest_constituent_persisted_at'], 'UTC_H4_INPUTS_ALL_ARCHIVED', origin,
                      meaning='latest constituent archive persistence, not original calculation time')
    conditions = []

    def condition(key, state, scope, detail, evidence):
        assert state in STATES
        conditions.append(dict(id=key, classification=state, scope=scope, detail=detail, evidence=evidence))

    condition('h1_long_represented', 'ATENDIDA' if facts.get('system.context_trend.state') == 'BULL_CONFIRMED'
              and facts.get('system.context_trend.direction') == 'bullish' and case.get('side') == 'long'
              else 'NÃO_COMPROVADA', 'case representation',
              'H1 and side are case declarations, not independent trend validation.', ['case:system.context_trend', 'case:side'])
    condition('h1_original_availability', 'NÃO_COMPROVADA', 'historical agent',
              'No original calculation/received_at lineage proves the context was available by the exact cutoff.',
              ['case:context_scope'])
    highs = [p['price'] for p in usable if p['kind'] == 'high']
    lows = [p['price'] for p in usable if p['kind'] == 'low']
    state = 'NÃO_MENSURÁVEL'
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
            state = 'CONTRARIADA'
        elif highs[-1] > highs[-2] and lows[-1] > lows[-2]:
            state = 'ATENDIDA'
        else:
            state = 'NÃO_COMPROVADA'
    condition('ascending_structure_in_supplied_sequence', state, 'case pivots confirmed nominally by cutoff',
              'Comparison only in the supplied sequence; no assumed equivalence to H1 scale.',
              ['case:system.market_structure.recent_swings'])
    condition('structural_scale_and_protected_low', 'NÃO_COMPROVADA', 'bibliographic method',
              'Scale, protected low and causal link to the impulse are not established.', ['replay_spec.md:4-5'])
    condition('pivots_declared_confirmation_by_cut', 'ATENDIDA' if usable and len(usable) == len(pivots)
              else 'NÃO_COMPROVADA', 'case declared times',
              'A pivot is usable as nominally confirmed only when confirmed_at <= cutoff; reception is separate.',
              ['case:system.market_structure.recent_swings'])
    for key, detail in [('depth_and_speed', 'No frozen impulse/correction detector and boundaries.'),
                        ('region_and_confirmation_trigger', 'Region algorithm and complete later-breakout contract absent.'),
                        ('economic_replay_specification', 'Costs, execution, cancellation, holding period and evaluation windows unresolved.')]:
        condition(key, 'NÃO_MENSURÁVEL', 'bibliographic research', detail, ['decisions.md'])
    condition('centralized_volume', 'NÃO_MENSURÁVEL', 'source semantics',
              'Forex tick volume is not centralized traded volume.', ['case:volume_scope'])
    condition('correction_and_continuation_established', 'NÃO_COMPROVADA', 'case representation',
              f"correction={facts.get('system.correction_state')}; follow_through={facts.get('system.follow_through_status')}",
              ['case:system.correction_state', 'case:system.follow_through_status'])
    condition('h4_native_equals_context_close', 'CONTRARIADA' if any(
              h['case_context_timestamp'] and not h['native_bar_with_context_close'] for h in h4)
              else 'NÃO_COMPROVADA', 'native archive versus case timestamp, not strategy eligibility',
              'Native alignment differs from the UTC aggregate candidate; no timestamps shifted.', ['h4_investigation'])
    condition('h4_original_aggregation_path', 'NÃO_COMPROVADA', 'historical provenance',
              'A reconstructed bucket with matching close time does not prove the original source or trend state.',
              ['h4_investigation'])
    condition('last_case_bar_agent_available_by_cut', 'NÃO_COMPROVADA', 'historical agent',
              'Neither later archive persistence nor later case persistence proves or disproves receipt at the cutoff.',
              ['observador/case_db_identity.json', 'case_archive_comparison'])
    condition('historical_policy_and_research_mode', 'NÃO_COMPROVADA', 'historical process',
              'Current configuration and a literal paper heartbeat do not prove historical function arguments.',
              ['observador/configuration.json', 'observador/state_details.json'])
    timeline.sort(key=lambda e: (utc(e['at']), e['kind'], e['evidence']))
    return dict(schema_version=1, diagnostic_version='causal-offline-v1', case_id=case['case_id'],
        as_of=case['as_of'], symbol=case['symbol'], side=case.get('side'),
        views=dict(archive_known_by_cut=_summary(archived),
                   represented_in_case=dict(bars=len(case_bars), clock_id=None,
                       persistence=records, provenance='case representation; not merged into archive'),
                   posterior_market_prefix=_summary(market)),
        case_archive_comparison=comparisons, pivots_nominally_confirmed_by_cut=usable,
        h4_investigation=h4, timeline=timeline, conditions=conditions,
        conclusion='Compra elegível não demonstrada; disponibilidade do agente não comprovada.',
        limitations=['No fills, P&L, inference, model imports, database, broker or operational state access.',
                     'Timeline includes later persistence as audit evidence, never as prefix input.',
                     'Hash integrity is not independent proof of source correctness or historical deployment.',
                     'Unknown agent reception is not interpreted as late reception.',
                     'No entry, risk, cost or return-based parameters selected.'])


def load_and_diagnose(bundle, expected_index_sha256):
    root = Path(bundle)
    index_raw = safe_file(root, 'artifact_hashes.json').read_bytes()
    if sha256(index_raw) != expected_index_sha256:
        raise ValueError('FROZEN_INDEX_HASH_MISMATCH')
    index = decode(index_raw)
    snapshot = checked_files(root, index)
    required = {'observador/case.json', 'observador/case_db_identity.json',
                'observador/coverage.json', 'observador/configuration.json',
                'observador/state_details.json', 'replay_spec.md', 'decisions.md',
                'revisor/numbered_evidence.txt'}
    if not required <= set(snapshot):
        raise ValueError('DIAGNOSTIC_INPUT_MISSING')
    case = decode(snapshot['observador/case.json'])
    archive, market = [], []
    used = set()
    for descriptor in decode(snapshot['observador/coverage.json']):
        name = 'observador/' + descriptor['file']
        if name not in snapshot or name in used:
            raise ValueError('EXPORT_NOT_SEALED_OR_DUPLICATED')
        used.add(name)
        rows = [decode(line) for line in snapshot[name].splitlines() if line.strip()]
        if len(rows) != descriptor['bars']:
            raise ValueError('COVERAGE_COUNT_MISMATCH')
        for row in rows:
            if (row['timeframe'] != descriptor['timeframe']
                    or row.get('clock_id', 'UNSPECIFIED') != descriptor['clock_id']):
                raise ValueError('EXPORT_IDENTITY_CONFLICT')
        if descriptor['scope'] == 'known_at_case':
            if any(close_at(row) > utc(case['as_of']) or utc(row['recorded_at_utc']) > utc(case['as_of']) for row in rows):
                raise ValueError('ARCHIVE_EXPORT_CUTOFF_VIOLATION')
            archive.extend(rows)
        elif descriptor['scope'] == 'market_prefix_collected_later':
            if any(close_at(row) > utc(case['as_of']) for row in rows):
                raise ValueError('MARKET_EXPORT_CUTOFF_VIOLATION')
            market.extend(rows)
        elif descriptor['scope'] != 'post_case_evaluation':
            raise ValueError('UNKNOWN_EXPORT_SCOPE')
        # Post-case values are integrity checked but never passed to diagnose.
    report = diagnose(case, archive, market,
                      case_records=decode(snapshot['observador/case_db_identity.json']))
    provenance = dict(input_index_sha256=sha256(index_raw), verified_files=len(index),
                      input_hashes=index, source_bundle=str(root.resolve()),
                      report_sha256=sha256(canonical(report)),
                      module_sha256=sha256(Path(__file__).read_bytes()),
                      integrity_module_sha256=sha256(Path(__file__).with_name('offline_integrity.py').read_bytes()))
    return report, provenance


def markdown(report):
    lines = ['# Diagnóstico causal offline', '', f"Caso: `{report['case_id']}`.",
             f"As_of: `{report['as_of']}`.", '', report['conclusion'], '',
             'As três trilhas permanecem separadas. Arquivamento posterior não comprova chegada tardia ao agente.', '',
             '| Condição | Classificação | Escopo / evidência |', '|---|---|---|']
    for c in report['conditions']:
        lines.append(f"| {c['id']} | {c['classification']} | {c['scope']}: {c['detail']} |")
    lines += ['', '## Investigação H4', '']
    for h in report['h4_investigation']:
        lines += [f"- Origem: `{h['identity']}`.",
                  f"- Última H4 nativa: {h['native_latest_open']} → {h['native_latest_close']}.",
                  f"- Contexto declarado: {h['case_context_timestamp']}; fase UTC nativa: {h['native_utc_phase_seconds']} segundos.",
                  f"- Buckets UTC completos com fechamento do contexto: {len(h['utc_bucket_with_context_close'])}; origem histórica: {h['status']}.",
                  '- Não houve deslocamento de timestamps ou recomputação do estado da tendência.']
    lines += ['', '## Linha do tempo', '', '| Horário UTC | Evento | Evidência |', '|---|---|---|']
    lines.extend(f"| {e['at']} | {e['kind']} | {e['evidence']} |" for e in report['timeline'])
    lines += ['', '## Pendências para replay econômico', '',
              'Origem/clock e agregação H4; disponibilidade histórica e política/modo; escala/pernas/região/gatilho; '
              'execução, stop, alvo, cancelamento e prazo; custos e ambiguidade intrabar; janelas separadas e critérios de avaliação. '
              'Detalhes nas decisões congeladas. Nenhuma escolha foi feita pelo lucro.', '']
    return '\n'.join(lines)
