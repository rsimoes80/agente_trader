"""Build/load private book skills with source-checked cards and lazy topic files."""
import hashlib
import json
from pathlib import Path

from .book_profiles import PROFILES
from .literature_learning import validate_techniques

ROOT = Path(__file__).resolve().parents[2]
ITEM_FIELDS = ('name','kind','summary','quote','scope','conditions','invalidations','numeric_rules')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def private_write(path, text):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.parent.chmod(0o700)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(text,encoding='utf-8');temporary.chmod(0o600);temporary.replace(path)


def build_skills(cards, *, root=ROOT):
    root=Path(root);cache=root/'data/references_cache/learning-library'
    inventory=json.loads((cache/'inventory.json').read_text())
    sources={s['document']:s for s in inventory}
    results=[]
    for profile in PROFILES:
        checked=[];documents=[]
        for name in profile.documents:
            source=sources[name]
            actual=hashlib.sha256((root/'Aprendizado'/name).read_bytes()).hexdigest()
            if actual!=source['sha256']:raise ValueError('BOOK_SOURCE_CHANGED')
            documents.append({k:source[k] for k in ('document','sha256','pages')})
        for card in cards:
            if card.get('source_document') not in profile.documents:continue
            source=sources[card['source_document']]
            if card.get('source_sha256')!=source['sha256']:raise ValueError('CARD_SOURCE_CHANGED')
            page=json.loads((root/source['cache']/f"{card['pdf_page']:04d}.json").read_text())
            if hashlib.sha256(page['text'].encode()).hexdigest()!=page['text_sha256'] or card.get('page_text_sha256')!=page['text_sha256']:
                raise ValueError('CARD_PAGE_CHANGED')
            item={k:card[k] for k in ITEM_FIELDS if k in card}
            rebuilt=validate_techniques({'techniques':[item]},source,page)[0]
            if rebuilt['card_id']!=card.get('card_id'):raise ValueError('CARD_CONTENT_CHANGED')
            checked.append(rebuilt)
        checked=sorted({c['card_id']:c for c in checked}.values(),key=lambda c:(c['source_document'],c['pdf_page'],c['card_id']))
        folder=root/'data/references_cache/book-skills'/profile.id
        template=(root/'knowledge_skills'/profile.id/'SKILL.md').read_text()
        topics={}
        for kind in sorted({c['kind'] for c in checked}):
            selected=[c for c in checked if c['kind']==kind]
            relative=f'references/{kind}.json'
            private_write(folder/relative,json.dumps(selected,ensure_ascii=False,indent=2)+'\n')
            topics[kind]=dict(path=relative,sha256=hashlib.sha256((folder/relative).read_bytes()).hexdigest(),cards=len(selected))
        manifest=dict(schema_version=1,specialist_id=profile.id,documents=documents,topics=topics,
                      source_cards=len(checked),pages_with_cards=len({(c['source_document'],c['pdf_page']) for c in checked}),
                      semantic_review_complete=False,visual_review_complete=False,
                      status='partial_research_skill' if checked else 'awaiting_source_cards',trading_authority=False)
        manifest['skill_version']=digest(dict(manifest=manifest,instructions=template))
        private_write(folder/'SKILL.md',template)
        private_write(folder/'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        results.append(manifest)
    return results


def load_skill(profile, *, root=ROOT, max_cards=6):
    folder=Path(root)/'data/references_cache/book-skills'/profile.id
    if not (folder/'manifest.json').exists():raise ValueError('SKILL_NOT_BUILT')
    manifest=json.loads((folder/'manifest.json').read_text());instructions=(folder/'SKILL.md').read_text()
    unsigned={k:v for k,v in manifest.items() if k!='skill_version'}
    if digest(dict(manifest=unsigned,instructions=instructions))!=manifest.get('skill_version'):
        raise ValueError('SKILL_VERSION_MISMATCH')
    cards=[]
    for kind in profile.kinds:
        topic=manifest['topics'].get(kind)
        if not topic:continue
        path=folder/topic['path']
        if path.resolve().parent!=(folder/'references').resolve():raise ValueError('SKILL_REFERENCE_PATH_INVALID')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=topic['sha256']:raise ValueError('SKILL_REFERENCE_CHANGED')
        cards.extend(json.loads(path.read_text()))
    # Round-robin kinds avoids allowing a long context chapter to crowd out triggers/exits.
    grouped={kind:[c for c in cards if c['kind']==kind] for kind in profile.kinds}
    selected=[]
    while len(selected)<max_cards and any(grouped.values()):
        for kind in profile.kinds:
            if grouped[kind] and len(selected)<max_cards:selected.append(grouped[kind].pop(0))
    return dict(profile=profile,instructions=instructions,manifest=manifest,cards=selected,
                loaded_card_count=len(selected),available_card_count=len(cards))
