const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const element=()=>({textContent:'',dataset:{},children:[],disabled:false,hidden:false,replaceChildren(){this.children=[];},append(child){this.children.push(child);}});
async function scenario(application,updated=false){
 const elements=new Map();
 const document={getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},querySelectorAll(){return [];},createElement:element};
 const selected={model:'mistralai/Timestral-209M',revision:'base',configuration:'cfg'};
 const confirmed=application==='IN_USE';
 const model={selected,status:confirmed?'CONFIRMED_RESULT':'CONFIGURED',note:'Nota de confirmação',last_result:confirmed?{model:selected.model,used_at:'2026-10-27T12:00:00Z',artifact_sha256:'a'.repeat(64),source:'cache'}:null};
 const state={symbol:'XAUUSD',run_id:'fixture',status:application==='PENDING_EVALUATION'?'WAITING_RESOURCES':'PROMOTED',stage:'features',evolution:{
  model,weights:{status:updated?'SAVED_UPDATE':'NOT_RECORDED',update:updated?{last_gradient_at:'2026-10-27T10:00:00Z'}:null,selected_epoch:updated?0:null,message:updated?'Época zero: candidato original.':'Ainda sem ajuste salvo.'},
  comparisons:updated?[{label:'Erro',source:4,candidate:3,delta:-1,unit:'0,01',change:'IMPROVED'}]:[],
  comparison_basis:'Comparação no teste separado',reasons:[{phase:'execution',message:'Aguardando retomada.'}],
  decision:{title:'Estado da avaliação',application,message:'Mensagem',prospective:null},trace:{symbol:'XAUUSD',run_id:'fixture'},history:[]}};
 let requests=0;
 const context=vm.createContext({document,location:{search:'?symbol=XAUUSD'},URLSearchParams,AbortSignal,setTimeout(){},fetch:async url=>{
  assert.match(url,/symbol=XAUUSD/);requests++;return {ok:true,json:async()=>({ok:true,csrf:'fixture',state,assets:['EURUSD','XAUUSD'],queue:[{symbol:'XAUUSD',status:state.status,model}]})};
 }});
 vm.runInContext(fs.readFileSync('static/training.js','utf8'),context);await new Promise(r=>setImmediate(r));
 assert.equal(requests,1);assert.equal(elements.get('error').hidden,true);
 assert.equal(elements.get('evidence-model').textContent,selected.model);
 assert.equal(elements.get('asset-models').children.length,1);
 assert.equal(elements.get('evidence-applied').textContent,confirmed?'Uso confirmado':application==='PENDING_EVALUATION'?'Em avaliação; não aplicado':'Aprovado; aplicação ainda não confirmada');
 if(updated){assert.match(elements.get('evidence-weights').textContent,/Época escolhida: 0/);assert.match(elements.get('evidence-change').textContent,/1 melhoraram/);}
 else{assert.match(elements.get('evidence-adjusted').textContent,/Nenhum ajuste salvo/);assert.match(elements.get('evidence-comparisons').children[0].children[0].textContent,/não são resultado zero/);}
 if(confirmed)assert.match(elements.get('evidence-model-note').textContent,/não é uma nova inferência/);
}
(async()=>{await scenario('PENDING_EVALUATION');await scenario('APPROVED_PENDING_USE',true);await scenario('IN_USE',true);console.log('PASS: per-asset model identity, pending approval/application, saved adjustment, epoch zero, comparisons, missing data and cached use. No commands sent.');})().catch(e=>{console.error(e);process.exitCode=1;});
