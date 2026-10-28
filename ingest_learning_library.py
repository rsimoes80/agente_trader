"""Read every local PDF page into a private, page-cited corpus; OCR is resumable."""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
from datetime import datetime,timezone
import hashlib,json,os
from pathlib import Path
import sqlite3,subprocess,tempfile

ROOT=Path(__file__).resolve().parent


def extract_page(task):
    import pymupdf
    path,index,out,ocr,dpi=task
    dest=Path(out)/f'{index+1:04d}.json'
    if dest.exists():return json.loads(dest.read_text())
    with pymupdf.open(path) as doc:
        page=doc[index];text=page.get_text();method='native'
        if len(text.strip())<100 and ocr:
            prefix=ROOT/'.tools/tesseract'
            env={**os.environ,'LD_LIBRARY_PATH':str(prefix/'usr/lib/x86_64-linux-gnu'),
                 'TESSDATA_PREFIX':str(prefix/'usr/share/tesseract-ocr/5/tessdata'),'OMP_THREAD_LIMIT':'1'}
            with tempfile.TemporaryDirectory() as tmp:
                image=Path(tmp)/'page.png';page.get_pixmap(dpi=dpi).save(image)
                result=subprocess.run([str(prefix/'usr/bin/tesseract'),str(image),'stdout','-l','por+eng','--psm','3'],
                                      env=env,capture_output=True,text=True,timeout=120,check=True)
                text=result.stdout;method='ocr'
        result=dict(page=index+1,text=text,method=method,characters=len(text.strip()),
                    text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    semantic_review='not_reviewed',visual_figures_reviewed=False)
        dest.write_text(json.dumps(result,ensure_ascii=False)+'\n');dest.chmod(0o600)
        return result


def main():
    import pymupdf
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ocr',action='store_true');parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--dpi',type=int,default=170)
    args=parser.parse_args()
    if not 1<=args.workers<=8:parser.error('Use 1..8 workers')
    cache=ROOT/'data/references_cache/learning-library';cache.mkdir(parents=True,exist_ok=True);cache.chmod(0o700)
    inventory=[];tasks=[]
    for path in sorted((ROOT/'Aprendizado').iterdir()):
        if path.suffix.lower()!='.pdf':continue
        digest=hashlib.sha256(path.read_bytes()).hexdigest();folder=cache/digest;folder.mkdir(exist_ok=True)
        with pymupdf.open(path) as doc:count=len(doc)
        inventory.append(dict(document=path.name,sha256=digest,pages=count,cache=str(folder.relative_to(ROOT)),
                              semantic_status='not_reviewed',full_book_semantically_reviewed=False))
        tasks.extend((str(path),i,str(folder),args.ocr,args.dpi) for i in range(count))
    (cache/'inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n')
    completed=0;errors=[]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(extract_page,t):t for t in tasks}
        for future in as_completed(futures):
            task=futures[future]
            try:future.result()
            except Exception as exc:errors.append(dict(document=Path(task[0]).name,page=task[1]+1,error=type(exc).__name__))
            completed+=1
            if completed%50==0:print(json.dumps(dict(processed=completed,total=len(tasks),errors=len(errors))),flush=True)
    db=sqlite3.connect(cache/'search.sqlite3')
    db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS pages USING fts5(document UNINDEXED, source_hash UNINDEXED, page UNINDEXED, text, tokenize="unicode61 remove_diacritics 2")')
    db.execute('DELETE FROM pages')
    for source in inventory:
        files=sorted((ROOT/source['cache']).glob('*.json'));source['extracted_pages']=len(files)
        source['ocr_pages']=0;source['sparse_pages']=[]
        for p in files:
            r=json.loads(p.read_text());source['ocr_pages']+=r['method']=='ocr'
            if r['characters']<100:source['sparse_pages'].append(r['page'])
            db.execute('INSERT INTO pages VALUES(?,?,?,?)',(source['document'],source['sha256'],r['page'],r['text']))
    db.commit();db.close()
    result=dict(completed_at=datetime.now(timezone.utc).isoformat(),sources=inventory,errors=errors,
                extraction_complete=not errors,semantic_review_complete=False,
                warning='Extraction and indexing do not establish comprehension, chart interpretation or trading validation.')
    (cache/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(stage='indexed',pages=completed,errors=len(errors))),flush=True)


if __name__=='__main__':main()
