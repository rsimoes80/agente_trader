"""Exact instrument/profile identity across training data, jobs and releases."""
from aurelia_fx.instrument_research import InstrumentResearchProfile
from aurelia_fx.instruments import symbol_name


def identity(manifest):
    symbol=symbol_name(manifest.get('symbol','EURUSD'))
    raw=manifest.get('research_profile')
    profile=InstrumentResearchProfile.from_dict(raw) if raw else None
    profile_id=manifest.get('profile_id')
    if (symbol!='EURUSD' or profile_id is not None) and (not isinstance(profile_id,str) or len(profile_id)!=64 or any(c not in '0123456789abcdef' for c in profile_id)):
        raise ValueError('TRAINING_PROFILE_REQUIRED')
    if profile and (profile.symbol!=symbol or manifest.get('profile_id')!=profile.fingerprint):
        raise ValueError('TRAINING_PROFILE_MISMATCH')
    return dict(symbol=symbol,profile_id=profile.fingerprint if profile else profile_id)


def profile_for(state):
    identity(state)
    if state.get('symbol','EURUSD')!='EURUSD' and not state.get('research_profile'):raise ValueError('TRAINING_PROFILE_REQUIRED')
    profile=InstrumentResearchProfile.from_dict(state['research_profile']) if state.get('research_profile') else None
    if profile and state.get('price_unit',profile.price_unit)!=profile.price_unit:raise ValueError('TRAINING_PRICE_UNIT_MISMATCH')
    return profile


def agent_profile(memory,symbol):
    from aurelia_fx.operation_control import OperationControl
    state=OperationControl(memory,symbol).status()
    profile=profile_for(state)
    if not profile or state.get('mode')!='demo' or not state.get('demo_authorization'):
        raise ValueError('TRAINING_REQUIRES_PREPARED_DEMO_PROFILE')
    auth=state['demo_authorization']
    if auth.get('symbol')!=symbol or auth.get('profile_id')!=profile.fingerprint:
        raise ValueError('TRAINING_AUTHORIZATION_PROFILE_MISMATCH')
    return profile


def assert_same(*records):
    scopes=[identity(r) for r in records]
    if any(s!=scopes[0] for s in scopes):raise ValueError('TRAINING_INSTRUMENT_SCOPE_MISMATCH')
    return scopes[0]
