const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const el=()=>({textContent:'',hidden:true,disabled:false,replaceChildren(){},append(){}});
async function check(fail=false,resources=false){
 const elements=new Map(),posts=[];
 const document={getElementById(id){if(!elements.has(id))elements.set(id,el());return elements.get(id);},querySelectorAll(){return [];},createElement:el};
 const state={status:'FAILED',message:'RESOURCE_LIMIT: old run',run_id:'old',updated_at:'2026-10-23T17:28:33Z'};
 if(resources)Object.assign(state,{status:'WAITING_RESOURCES',message:'Aguardando memória',runtime:{at:'2026-10-26T16:00:00Z',available_mb:290,minimum_start_mb:384,maximum_worker_mb:768,minimum_free_mb:128,shortage_mb:94,received_age_seconds:1,matches_run:true,worker_rss_mb:null},saved_checkpoint:{stage:'features',partition:'train',completed:160,total:800},retry_not_before:'2026-10-26T16:15:00Z'});
 const context=vm.createContext({document,crypto:{getRandomValues:require('node:crypto').webcrypto.getRandomValues.bind(require('node:crypto').webcrypto)},Uint8Array,AbortSignal,setTimeout(){},fetch:async(url,options)=>{
  if(options?.method==='POST'){posts.push(options);return {ok:!fail,json:async()=>fail?{ok:false,error:'Connection rejected'}:{ok:true,state:{status:'QUEUED',message:'Treino solicitado',run_id:'new'}}};}
  return {ok:true,json:async()=>({ok:true,csrf:'fixture',state})};
 }});
 vm.runInContext(fs.readFileSync('static/training.js','utf8'),context);
 await new Promise(r=>setImmediate(r));
 if(resources){assert.match(elements.get('resource-free').textContent,/290/);assert.match(elements.get('resource-status').textContent,/Faltam 94/);assert.match(elements.get('resume-status').textContent,/160\/800/);assert.match(elements.get('progress-status').textContent,/não está treinando/);assert.equal(elements.get('start').disabled,true);assert.equal(posts.length,0);return;}
 assert.match(elements.get('message').textContent,/interrompido por limite/);
 await Promise.all([elements.get('start').onclick(),elements.get('start').onclick()]);
 assert.equal(posts.length,1);assert.match(posts[0].headers['Idempotency-Key'],/^[0-9a-f]{32}$/);
 if(fail){assert.match(elements.get('error').textContent,/Connection rejected/);assert.equal(elements.get('error').hidden,false);}
 else{assert.equal(elements.get('status').textContent,'Na fila do computador Windows');assert.equal(elements.get('start').disabled,true);}
}
(async()=>{await check();await check(true);await check(false,true);console.log('PASS: HTTP fallback, duplicate click guard, visible failure, confirmed queue, resource shortage and saved progress; no real training started.');})().catch(e=>{console.error(e);process.exitCode=1;});
