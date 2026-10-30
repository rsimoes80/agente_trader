"""Long-only scenario fills and costs. No broker, account or operational risk policy."""
from __future__ import annotations


def slip(protocol):
    return protocol['pip_size'] * protocol['costs']['slippage_pips_per_market_side']


def fill(signal, bar, protocol):
    """Caller checks activation, expiry and H1 using only information known at open."""
    spread = bar.get('spread_pips')
    if spread is None:
        return None, 'SPREAD_UNAVAILABLE'
    if bar['open'] <= signal['protected_low'] or bar['open'] <= signal['stop']:
        return None, 'OPEN_INVALIDATED'
    if bar['high'] < signal['trigger']:
        return None, 'WAITING_BREAKOUT'
    reference = max(bar['open'], signal['trigger'])
    price = reference + spread * protocol['pip_size'] + slip(protocol)
    if not signal['stop'] < price < signal['target'] or signal['target']-price < 2*(price-signal['stop']):
        return None, 'FILL_GEOMETRY_OR_RR'
    commission = 2 * protocol['units'] / 1_000_000 * protocol['costs']['commission_usd_per_million_per_side']
    position = dict(signal, entry=price, entry_bid_reference=reference,
                    entry_spread_price=spread*protocol['pip_size'], entry_slippage_price=slip(protocol),
                    entry_bar_open_at=bar['timestamp'], commission_roundtrip_usd=commission,
                    initial_risk_usd=(price-signal['stop']+slip(protocol))*protocol['units']+commission,
                    observed_holding_bars=0)
    if bar['open'] < signal['trigger'] and bar['low'] <= signal['stop']:
        return position, 'AMBIGUOUS_ENTRY_ORDER'
    return position, None


def outcome(position, exit_bid_reference, reason, bar, protocol, *, limit=False):
    out_slip = 0.0 if limit else slip(protocol)
    units = protocol['units']
    gross = (exit_bid_reference-position['entry_bid_reference'])*units
    spread_cost = position['entry_spread_price']*units
    slippage_cost = (position['entry_slippage_price']+out_slip)*units
    commission = position['commission_roundtrip_usd']
    net = gross-spread_cost-slippage_cost-commission
    return dict(status='CLOSED', reason=reason, side='long', signal_at=position['signal_at'],
        leg_id=position['leg_id'], entry_bar_open_at=position['entry_bar_open_at'],
        exit_bar_open_at=bar['timestamp'], observed_at=bar['closed_at'],
        entry_price=position['entry'], exit_price=exit_bid_reference-out_slip,
        stop=position['stop'], target=position['target'], units=units,
        gross_pnl_usd=gross, spread_cost_usd=spread_cost, slippage_cost_usd=slippage_cost,
        commission_usd=commission, net_pnl_usd=net, initial_risk_usd=position['initial_risk_usd'],
        result_in_r=net/position['initial_risk_usd'],
        entry_time_semantics='bar interval; exact intrabar time unknown unless gap/open fill',
        exit_time_semantics='bar interval; observed at close, not exact touch timestamp')


def censored(position, reason, bar, protocol, *, bounds=False, uncertain_entry=False):
    result = dict(status='CENSORED', reason=reason, side='long', signal_at=position['signal_at'],
        leg_id=position['leg_id'], entry_bar_open_at=position['entry_bar_open_at'],
        observed_at=bar['closed_at'], net_pnl_usd=None, result_in_r=None,
        initial_risk_usd=position['initial_risk_usd'], stop=position['stop'], target=position['target'],
        uncertain_entry=uncertain_entry, lower_net_usd=None, upper_net_usd=None)
    if bounds:
        low = outcome(position,position['stop'],'BOUND_STOP',bar,protocol)['net_pnl_usd']
        high = outcome(position,position['target'],'BOUND_TARGET',bar,protocol,limit=True)['net_pnl_usd']
        if uncertain_entry:
            result.update(local_stop_net_usd=low,local_target_net_usd=high,
                          local_scenarios_exhaustive=False,
                          bounds_semantics='Unknown horizon bounds; local stop/target scenarios exclude later gaps and are not bounds.')
        else:
            result.update(lower_net_usd=low,upper_net_usd=high,
                          bounds_semantics='same-bar stop-first/target-first scenario bounds, not realized P&L')
    return result


def advance(position, bar, protocol, *, force_reason=None):
    """Known-open gaps precede unordered high/low tests; stop/target precede time."""
    position['observed_holding_bars'] += 1
    if bar['open'] <= position['stop']:
        return outcome(position,bar['open'],'STOP_GAP',bar,protocol)
    if bar['open'] >= position['target']:
        return outcome(position,position['target'],'TARGET_GAP_LIMIT',bar,protocol,limit=True)
    stop_hit, target_hit = bar['low'] <= position['stop'], bar['high'] >= position['target']
    if stop_hit and target_hit:
        return censored(position,'AMBIGUOUS_EXIT_ORDER',bar,protocol,bounds=True)
    if stop_hit:
        return outcome(position,position['stop'],'STOP',bar,protocol)
    if target_hit:
        return outcome(position,position['target'],'TARGET',bar,protocol,limit=True)
    if position['observed_holding_bars'] >= protocol['max_holding_bars']:
        return outcome(position,bar['close'],'TIMEOUT',bar,protocol)
    if force_reason:
        return outcome(position,bar['close'],force_reason,bar,protocol)
    return None
