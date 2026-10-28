"""Source-constrained advisory agents sharing one local model; no broker dependency."""
from datetime import datetime, timedelta, timezone
import json
import copy
import math
from .literature_model import completion

from .book_skills import digest

VERSION='book-council-v1.2'
MODEL_SPEC=dict(model='Qwen/Qwen3-4B-GGUF',revision='bc640142c66e1fdd12af0bd68f40445458f3869b',
                temperature=0,max_tokens=650,max_cards=6,prompt_version=VERSION)
PRICE_STAGES={'context','region','trigger','invalidation','exit'}


def market_case(snapshot, candles):
    """Freeze already closed observations. Derived context remains labelled as system output."""
    def timestamp(value):
        parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if parsed.tzinfo is None:raise ValueError('CASE_TIMEZONE_REQUIRED')
        return parsed.astimezone(timezone.utc)
    as_of=timestamp(snapshot['timestamp_utc'])
    facts={}
    def add(prefix,value):
        if isinstance(value,dict):
            for key,child in sorted(value.items()):add(prefix+'.'+str(key),child)
        elif isinstance(value,(list,tuple)):
            for index,child in enumerate(value[:4]):add(prefix+'.'+str(index),child)
        elif value is None or isinstance(value,(str,bool,int,float)):
            if isinstance(value,float) and not math.isfinite(value):raise ValueError('NONFINITE_MARKET_FACT')
            if value is not None and (not isinstance(value,str) or len(value)<=200):facts[prefix]=value
    for key in ('context_trend','macro_trend'):
        trend=snapshot.get(key) or {}
        add('system.'+key,{k:trend[k] for k in ('direction','state','timeframe','timestamp_utc') if k in trend})
    for key in ('regime','market_location','session','dominant_swing','current_leg_type',
                'impulse_state','correction_state','follow_through_status','volume_context','data_quality'):
        add('system.'+key,snapshot.get(key))
    structure=snapshot.get('market_structure') or {}
    add('system.market_structure',{k:structure[k] for k in ('direction','bos','last_close') if k in structure})
    for i,swing in enumerate(structure.get('swings',[])[-4:]):
        add(f'system.market_structure.recent_swings.{i}',{k:swing[k] for k in ('kind','price','timestamp','confirmed_at') if k in swing})
    for key in ('support_levels','resistance_levels'):
        for i,level in enumerate((snapshot.get(key) or [])[:2]):
            add(f'system.{key}.{i}',{k:level[k] for k in ('price','level','kind','role','distance','timestamp','confirmed_at') if k in level})
    recent=candles[-12:]
    for i,bar in enumerate(recent):
        at=timestamp(bar['timestamp'])
        if at+timedelta(minutes=5)>as_of:raise ValueError('FUTURE_OR_OPEN_CANDLE')
        if i and at<=timestamp(recent[i-1]['timestamp']):raise ValueError('CANDLES_NOT_ORDERED')
        for key in ('timestamp','open','high','low','close','volume','spread_pips'):
            if key in bar:add(f'M5.{i}.{key}',bar[key])
    if not recent:raise ValueError('CLOSED_CANDLES_REQUIRED')
    for key,value in facts.items():
        if key.endswith(('.timestamp','.timestamp_utc','.confirmed_at')) and timestamp(value)>as_of:
            raise ValueError('FUTURE_CONTEXT_FACT')
    h1=snapshot.get('context_trend') or {}
    direction=h1.get('direction');expected={'bullish':'BULL_CONFIRMED','bearish':'BEAR_CONFIRMED'}.get(direction)
    side=({'bullish':'long','bearish':'short'}.get(direction) if expected and h1.get('state')==expected else None)
    body=dict(schema_version=1,symbol=snapshot['symbol'],as_of=as_of.isoformat(),side=side,facts=facts,
              volume_scope='Forex tick volume; centralized traded volume unavailable',
              missing_inputs=['visual_chart_review','operator_behavior','trade_outcome_series'],
              selection_scope='12 closed M5 bars; recent 4 structural swings; up to 2 supplied levels per side; selected system context fields',
              context_scope='system-derived H1/H4; author rules require separate validation')
    return {**body,'case_id':digest(body)}


def validate_case(case):
    if not isinstance(case,dict) or not isinstance(case.get('facts'),dict) or not case['facts']:
        raise ValueError('INVALID_MARKET_CASE')
    unsigned={k:v for k,v in case.items() if k!='case_id'}
    if case.get('case_id')!=digest(unsigned):raise ValueError('CASE_CHANGED')
    if case.get('side') not in (None,'long','short'):raise ValueError('INVALID_CASE_SIDE')


def validate_analysis(output, skill, case):
    validate_case(case)
    if not isinstance(output,dict) or set(output)!={'findings'} or not isinstance(output['findings'],list) or len(output['findings'])>3:
        raise ValueError('INVALID_SPECIALIST_SCHEMA')
    known={c['card_id']:c for c in skill['cards']};findings=[]
    for finding in output['findings']:
        fields={'stage','assessment','explanation','card_ids','fact_ids','missing_conditions','invalidation'}
        if not isinstance(finding,dict) or set(finding)!=fields:raise ValueError('INVALID_FINDING_SCHEMA')
        if finding['stage'] not in skill['profile'].stages:raise ValueError('SPECIALIST_SCOPE_EXCEEDED')
        if finding['assessment'] not in ('supports','opposes','uncertain'):raise ValueError('INVALID_ASSESSMENT')
        for key in ('explanation','invalidation'):
            if not isinstance(finding[key],str) or not 1<=len(finding[key])<=1200:raise ValueError('INVALID_EXPLANATION')
        for key,registry in (('card_ids',known),('fact_ids',case['facts'])):
            refs=finding[key]
            if not isinstance(refs,list) or not refs or not all(isinstance(r,str) and r in registry for r in refs):
                raise ValueError('UNKNOWN_'+key.upper())
        missing=finding['missing_conditions']
        if not isinstance(missing,list) or not all(isinstance(x,str) and 0<len(x)<=400 for x in missing):
            raise ValueError('INVALID_MISSING_CONDITIONS')
        if missing and finding['assessment']=='supports':raise ValueError('MISSING_CONDITION_CANNOT_SUPPORT')
        findings.append(dict(**finding,sources=[{k:known[c][k] for k in ('card_id','source_document','source_sha256','pdf_page','page_text_sha256')} for c in finding['card_ids']],
                             observed_facts={k:case['facts'][k] for k in finding['fact_ids']},semantic_entailment_reviewed=False))
    return dict(specialist_id=skill['profile'].id,skill_version=skill['manifest']['skill_version'],case_id=case['case_id'],
                status='research_analysis',findings=findings,trading_authority=False,model_spec=MODEL_SPEC,
                available_cards=skill['available_card_count'],loaded_cards=skill['loaded_card_count'])


def local_model(messages, *, endpoint='http://127.0.0.1:8791/v1/chat/completions'):
    data=dict(messages=messages,temperature=MODEL_SPEC['temperature'],max_tokens=MODEL_SPEC['max_tokens'],response_format={'type':'json_object'},
              chat_template_kwargs={'enable_thinking':False})
    result=completion(data,endpoint=endpoint,timeout=600)
    choice=result['choices'][0]
    if choice.get('finish_reason')=='length':raise ValueError('SPECIALIST_RESPONSE_TRUNCATED')
    return json.loads(choice['message']['content'])


def analyze(skill, case, *, model=local_model):
    validate_case(case)
    base=dict(specialist_id=skill['profile'].id,case_id=case['case_id'],skill_version=skill['manifest']['skill_version'],
              findings=[],trading_authority=False)
    if case['side'] is None:return dict(base,status='unconfirmed_trend')
    if not skill['cards']:return dict(base,status='awaiting_source_cards')
    system=skill['instructions']+'''
Retorne apenas JSON {"findings": [...]}, no máximo 2 conclusões.
Cada conclusão tem EXATAMENTE stage,assessment,explanation,card_ids,fact_ids,
missing_conditions,invalidation. stage pertence ao escopo acima; assessment é
supports,opposes ou uncertain. card_ids e fact_ids são listas de IDs exatos do
conteúdo fornecido. missing_conditions é uma lista de condições não medidas.
Uma condição ausente impede assessment=supports. Sem conclusão sustentada,
retorne findings vazio. Não crie números de entrada, stop ou alvo. A direção
case.side é definida pelo operador; analise apenas essa direção. Fatos system.*
são cálculo do sistema, não citação do livro. Não infira causa institucional nem
volume real de volume de ticks. Atribua ausência de revisão visual às lacunas.
Citar um fato e uma ficha não comprova a interpretação: ela será revisada.'''
    card_fields=('card_id','name','kind','summary','quote','scope','conditions','invalidations','numeric_rules')
    source_packets=[{k:c[k] for k in card_fields if k in c} for c in skill['cards']]
    content=json.dumps(dict(case=case,cards=source_packets),ensure_ascii=False,separators=(',',':'))
    if len(system)+len(content)>20000:raise ValueError('SPECIALIST_CONTEXT_BUDGET_EXCEEDED')
    messages=[dict(role='system',content=system),dict(role='user',content=content)]
    output=model(messages)
    conservative=copy.deepcopy(output);adjustments=[]
    # Preserve an internally contradictory opinion as uncertain, never as support.
    # Other schema/source/scope errors still reject the entire response.
    if isinstance(conservative,dict) and isinstance(conservative.get('findings'),list):
        for index,finding in enumerate(conservative['findings']):
            if (isinstance(finding,dict) and finding.get('assessment')=='supports'
                    and isinstance(finding.get('missing_conditions'),list) and finding['missing_conditions']
                    and all(isinstance(x,str) and 0<len(x)<=400 for x in finding['missing_conditions'])):
                finding['assessment']='uncertain'
                adjustments.append(dict(finding_index=index,model_assessment='supports',effective_assessment='uncertain',
                                        reason='MISSING_CONDITION_CANNOT_SUPPORT'))
    result=validate_analysis(conservative,skill,case)
    result['consistency_adjustments']=adjustments
    result['raw_response_sha256']=digest(output)
    result['inference_input_sha256']=digest(messages)
    return result


def coordinate(case, analyses):
    """Keep disagreements and gaps; multiple authors do not constitute independent votes."""
    validate_case(case)
    if len({a['specialist_id'] for a in analyses})!=len(analyses):raise ValueError('DUPLICATE_SPECIALIST')
    if any(a.get('case_id')!=case['case_id'] or a.get('trading_authority') is not False for a in analyses):
        raise ValueError('COUNCIL_CASE_OR_AUTHORITY_MISMATCH')
    claims=[dict(f,specialist_id=a['specialist_id']) for a in analyses for f in a.get('findings',[])]
    coverage={stage:[f for f in claims if f['stage']==stage and f['assessment']=='supports'] for stage in sorted(PRICE_STAGES)}
    conflicts=[stage for stage in coverage if coverage[stage] and any(f['stage']==stage and f['assessment']=='opposes' for f in claims)]
    gaps=[stage for stage,findings in coverage.items() if not findings]
    unavailable=[a['specialist_id'] for a in analyses if a['status'] not in ('research_analysis',)]
    complete=bool(analyses) and not (gaps or conflicts or unavailable) and case['side'] is not None
    result=dict(version=VERSION,case_id=case['case_id'],symbol=case['symbol'],as_of=case['as_of'],side=case['side'],
                action='RESEARCH_ONLY',status='candidate_for_semantic_review' if complete else 'incomplete_research',
                missing_stages=gaps,conflicting_stages=conflicts,unavailable_specialists=unavailable,
                claims=claims,analyses=analyses,requires_semantic_review=True,requires_replay_validation=True,
                trading_authority=False,orders_enabled=False)
    result['analysis_id']=digest(result)
    return result
