"""Only reviewed source cards and an approved complete plan grant entry authority."""
import hashlib,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
STAGES={'context','region','trigger','invalidation','exit'}


def references_hash(references):
    return hashlib.sha256(json.dumps(sorted(references,key=lambda x:(x['stage'],x['card_id'])),
        sort_keys=True,separators=(',',':')).encode()).hexdigest()


def basis_blocker(basis,approved=None):
    if not isinstance(basis,dict) or not basis.get('plan_id') or not isinstance(basis.get('references'),list):
        return 'LITERATURE_BASIS_REQUIRED'
    refs=basis['references']
    if not refs or any(not isinstance(r,dict) for r in refs):return 'LITERATURE_BASIS_INVALID'
    if any(not isinstance(r.get('card_id'),str) or not isinstance(r.get('stage'),str) or r['stage'] not in STAGES for r in refs):
        return 'LITERATURE_BASIS_INVALID'
    if {r['stage'] for r in refs}!=STAGES:return 'LITERATURE_STAGE_MISSING'
    if approved is None:
        p=ROOT/'data/references_cache/learning-library/approved_execution_cards.json'
        if not p.exists():return 'LITERATURE_RULE_NOT_APPROVED'
        try:approved=json.loads(p.read_text())
        except (OSError,ValueError):return 'LITERATURE_APPROVAL_INVALID'
    if not isinstance(approved,dict) or not isinstance(approved.get('plans'),dict) or not isinstance(approved.get('cards'),dict):
        return 'LITERATURE_APPROVAL_INVALID'
    if not isinstance(basis['plan_id'],str):return 'LITERATURE_BASIS_INVALID'
    plan=approved['plans'].get(basis['plan_id'])
    if not isinstance(plan,dict) or plan.get('status')!='approved_for_demo' or not plan.get('validation_report_id'):
        return 'LITERATURE_PLAN_NOT_APPROVED'
    for ref in refs:
        card=approved['cards'].get(ref['card_id'])
        if not isinstance(card,dict) or card.get('status')!='approved_for_demo' or card.get('semantic_entailment_reviewed') is not True:
            return 'LITERATURE_RULE_NOT_APPROVED'
        if ref['stage'] not in card.get('allowed_stages',[]):return 'LITERATURE_STAGE_NOT_SUPPORTED'
        if type(ref.get('pdf_page')) is not int or ref['pdf_page']<1:return 'LITERATURE_BASIS_INVALID'
        if any(not isinstance(ref.get(k),str) or not re.fullmatch('[a-f0-9]{64}',ref[k]) for k in ('source_sha256','page_text_sha256')):
            return 'LITERATURE_BASIS_INVALID'
        if any(ref.get(k)!=card.get(k) for k in ('source_sha256','pdf_page','page_text_sha256')):
            return 'LITERATURE_SOURCE_MISMATCH'
    if references_hash(refs)!=plan.get('reference_sha256'):return 'LITERATURE_PLAN_SOURCE_MISMATCH'
    return None
