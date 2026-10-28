"""Register source-checked editorial notes, never execution approval or full-book review."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))


def curate(spec, source, pages):
    from aurelia_fx.literature_learning import normalize,validate_techniques,redact
    if spec['source_sha256']!=source['sha256']:raise ValueError('CURATION_SOURCE_CHANGED')
    cards=[]
    for technique in spec['techniques']:
        page=pages[technique['page']];text=normalize(redact(page['text']))
        start=text.find(technique['anchor'])
        if start<0:raise ValueError('CURATION_ANCHOR_MISSING')
        quote=text[start:start+480]
        # No extra implementation parameters are attributed to the author.
        item={k:technique[k] for k in ('name','kind','summary','conditions','invalidations')}
        item.update(quote=quote,scope=spec['scope'],numeric_rules=[{'value':value,'quote':quote} for value in technique.get('numeric_values',[])])
        cards.extend(validate_techniques({'techniques':[item]},source,page))
    return cards


def main():
    from aurelia_fx.storage import open_memory
    spec=json.loads((ROOT/'config/book_skill_curations.json').read_text())
    inventory=json.loads((ROOT/'data/references_cache/learning-library/inventory.json').read_text())
    source=next(s for s in inventory if s['document']==spec['source_document'])
    pages={n:json.loads((ROOT/source['cache']/f'{n:04d}.json').read_text()) for n in {t['page'] for t in spec['techniques']}}
    cards=curate(spec,source,pages);memory=open_memory()
    try:
        for card in cards:memory.record_project_data('literature_technique_card',card['card_id'],card)
        print(json.dumps(dict(editorial_cards=len(cards),semantic_review_complete=False,visual_review_complete=False,trading_authority=False)))
    finally:memory.close()


if __name__=='__main__':main()
