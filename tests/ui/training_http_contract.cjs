const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const el=()=>({textContent:'',hidden:true,disabled:false,replaceChildren(){},append(){}});
async function check(fail=false){
 const elements=new Map(),posts=[];
 const document={getElementById(id){if(!elements.has(id))elements.set(id,el());return elements.get(id);},querySelectorAll(){return [];},createElement:el};
 const state={status:'FAILED',message:'RESOURCE_LIMIT: old run',run_id:'old',updated_at:'2026-10-23T17:28:33Z'};
 const context=vm.createContext({document,crypto:{getRandomValues:require('node:crypto').webcrypto.getRandomValues.bind(require('node:crypto').webcrypto)},Uint8Array,AbortSignal,setTimeout(){},fetch:async(url,options)=>{
  if(options?.method==='POST'){posts.push(options);return {ok:!fail,json:async()=>fail?{ok:false,error:'Connection rejected'}:{ok:true,state:{status:'QUEUED',message:'Treino solicitado',run_id:'new'}}};}
  return {ok:true,json:async()=>({ok:true,csrf:'fixture',state})};
 }});
 vm.runInContext(fs.readFileSync('static/training.js','utf8'),context);
 await new Promise(r=>setImmediate(r));
 assert.match(elements.get('message').textContent,/interrompido por limite/);
 await Promise.all([elements.get('start').onclick(),elements.get('start').onclick()]);
 assert.equal(posts.length,1);assert.match(posts[0].headers['Idempotency-Key'],/^[0-9a-f]{32}$/);
 if(fail){assert.match(elements.get('error').textContent,/Connection rejected/);assert.equal(elements.get('error').hidden,false);}
 else{assert.equal(elements.get('status').textContent,'Na fila do computador Windows');assert.equal(elements.get('start').disabled,true);}
}
(async()=>{await check();await check(true);console.log('PASS: HTTP fallback, duplicate click guard, visible failure, confirmed queued state; no real training started.');})().catch(e=>{console.error(e);process.exitCode=1;});
