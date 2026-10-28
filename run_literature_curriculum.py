"""Continuously read extracted pages with a local text model; no order/model tools."""
from datetime import datetime,timezone
import argparse,json,re
from pathlib import Path
import sys,time

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))


def main():
    from aurelia_fx.literature_learning import read_page,validate_techniques
    from aurelia_fx.storage import open_memory
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--limit',type=int)
    args=parser.parse_args();cache=ROOT/'data/references_cache/learning-library'
    m=open_memory();count=0
    priority={'EBOOK-MANUAL-DO-PULLBACK.pdf':[6,7,8,9,10,11,12,13,14,15,16,17,20,21,24,25,26],
              'analise-tecnica-explicadapdf-pdf-free.pdf':[16,17,20,24,25,26,68,69,70,71,72],
              'wyckoff-20-portugues-pr.pdf':[32,33,69,70,71,74,75,287,292],
              'operando-price-action-tendencias-al-brooks-5-pdf-free.pdf':[103,107,127,135,233,341],
              'Trading_in_the_Zone.PDF':[130,133,134,136]}
    try:
        while True:
            if not (cache/'inventory.json').exists():time.sleep(10);continue
            sources=json.loads((cache/'inventory.json').read_text())
            with m.pool.connection() as c:
                reviewed={r['record_key'] for r in c.execute("SELECT record_key FROM project_records WHERE record_type='literature_semantic_page'").fetchall()}
            queue=[]
            for source in sources:
                for p in sorted((ROOT/source['cache']).glob('*.json')):
                    page=json.loads(p.read_text());key=f"{source['sha256']}:{page['page']}:{page['text_sha256']}:qwen3-4b-v1"
                    if key in reviewed:continue
                    preferred=priority.get(source['document'],[])
                    rank=preferred.index(page['page']) if page['page'] in preferred else 1000+page['page']
                    queue.append((rank,source['document'],source,page,key))
            queue.sort(key=lambda x:(x[0],x[1]));processed=0
            for _,_,source,page,key in queue:
                if args.limit and count>=args.limit:return
                at=datetime.now(timezone.utc).isoformat()
                try:
                    if page['characters']<60:cards=[];status='sparse_page_not_semantically_reviewed'
                    else:
                        output=read_page(source,page);cards=validate_techniques(output,source,page)
                        status='read_requires_review' if cards else 'read_no_techniques_extracted'
                    for card in cards:m.record_project_data('literature_technique_card',card['card_id'],card)
                    m.record_project_data('literature_semantic_page',key,dict(document=source['document'],page=page['page'],
                        source_sha256=source['sha256'],text_sha256=page['text_sha256'],status=status,cards=[x['card_id'] for x in cards],
                        reader='Qwen/Qwen3-4B-GGUF',reader_revision='bc640142c66e1fdd12af0bd68f40445458f3869b',read_at=at,
                        visual_figures_reviewed=False,trading_authority=False))
                    processed+=1;count+=1
                    progress=dict(at=at,pages_read_this_process=count,last_document=source['document'],last_page=page['page'],last_status=status,
                                  technique_cards_this_page=len(cards),trading_authority=False)
                    m.record_project_data('literature_curriculum_status','current',progress)
                    (cache/'reader-status.json').write_text(json.dumps(progress,ensure_ascii=False,indent=2)+'\n')
                    print(json.dumps(progress,ensure_ascii=False),flush=True)
                except Exception as exc:
                    code=str(exc) if isinstance(exc,ValueError) and re.fullmatch('[A-Z_]+',str(exc)) else type(exc).__name__
                    m.record_project_data('literature_reader_failure',key,dict(document=source['document'],page=page['page'],
                        source_sha256=source['sha256'],text_sha256=page['text_sha256'],code=code,at=at,trading_authority=False))
                    print(json.dumps(dict(status='READER_RETRY',document=source['document'],page=page['page'],error_type=code)),flush=True)
                    time.sleep(10)
            if not processed:time.sleep(30)
    finally:m.close()


if __name__=='__main__':main()
