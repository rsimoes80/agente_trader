"""Book-derived strategy plans are research artifacts, never executable code."""
import hashlib,json

FAMILIES={'pullback_in_trend','breakout_retest_continuation','trend_channel_reaction','congestion_continuation'}
STAGES=('context','region','trigger','invalidation','exit')


def validate_blueprint(plan,cards):
    if not isinstance(plan,dict) or plan.get('family') not in FAMILIES:
        raise ValueError('UNKNOWN_LITERATURE_FAMILY')
    if plan.get('direction_policy')!='confirmed_h1_only':raise ValueError('COUNTERTREND_PLAN_REJECTED')
    known={c['card_id']:c for c in cards if c.get('source_quote_verified')}
    for stage in STAGES:
        facts=plan.get(stage)
        if not isinstance(facts,list) or not facts:raise ValueError('UNSOURCED_STAGE_'+stage)
        for fact in facts:
            if (not isinstance(fact,dict) or not isinstance(fact.get('description'),str) or not fact['description'].strip()
                or not isinstance(fact.get('card_ids'),list) or not fact['card_ids']
                or not all(isinstance(k,str) for k in fact['card_ids'])):
                raise ValueError('UNSOURCED_CLAIM')
            if any(k not in known for k in fact['card_ids']):raise ValueError('UNKNOWN_SOURCE_CARD')
    if not isinstance(plan.get('numeric_parameters',[]),list):raise ValueError('INVALID_NUMERIC_PARAMETERS')
    for parameter in plan.get('numeric_parameters',[]):
        if not isinstance(parameter,dict):raise ValueError('INVALID_NUMERIC_PARAMETER')
        card=known.get(parameter.get('card_id'))
        if not card or not any(str(parameter.get('value'))==str(rule.get('value')) for rule in card.get('numeric_rules',[])):
            raise ValueError('UNSOURCED_NUMERIC_PARAMETER')
    result={**plan,'status':'source_linked_research_plan_requires_validation','trading_authority':False,
            'semantic_entailment_reviewed':False,'code_generation_allowed':False}
    result['plan_id']=hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return result
