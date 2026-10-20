"use strict";
(() => {
  const $=id=>document.getElementById(id);
  const labels={STOPPED:"Agente parado",QUEUED:"Início solicitado",CONNECTING:"Conectando ao MT5",LOADING_HISTORY:"Preparando o histórico",PREPARING_EXPERIENCES:"Identificando hipóteses de pesquisa",FORECASTING:"Gerando previsões históricas",REPLAYING:"Simulando oportunidades históricas",TRAINING:"Treinamento em andamento",VALIDATING:"Validando a versão candidata",ANALYZING:"Analisando o mercado",POSITION_OPEN:"Operação simulada em andamento",PAUSE_REQUESTED:"Pausa solicitada",PAUSED:"Agente pausado",STOP_REQUESTED:"Parada solicitada",RECOVERY_REQUIRED:"Retomada exige revisão",ERROR:"Não foi possível iniciar",INSUFFICIENT_DATA:"Histórico insuficiente",TRAINING_UNAVAILABLE:"Histórico pronto · treinamento pendente",TRAINING_BLOCKED:"Treinamento concluído · operação bloqueada",AWAITING_APPROVAL:"Versão candidata aguarda aprovação"};
  let current=null, csrf="", authenticated=false, busy=false, pending=null, chartData=null, polling=false;
  labels.CHECKING_MODEL="Verificando Timestral";
  labels.LOADING_RESEARCH_HISTORY="Preparando dados para o treino";
  const date=value=>value?new Date(value).toLocaleString("pt-BR",{timeZone:"UTC",hour12:false}):"—";
  const number=value=>typeof value==="number"?value.toLocaleString("pt-BR",{maximumFractionDigits:5}):"—";
  async function api(path,payload,key){
    const response=await fetch(`/api/diagnostics/agent${path}`,{cache:"no-store",...(payload?{method:"POST",headers:{"Content-Type":"application/json","X-Diagnostics-CSRF":csrf,...(key?{"Idempotency-Key":key}:{})},body:JSON.stringify(payload)}:{})});
    const result=await response.json(); if(!response.ok || !result.ok)throw new Error(result.error || "Não foi possível consultar o agente."); return result;
  }
  function error(message){$("error").textContent=message;$("error").hidden=!message;}
  function render(data){
    current=data.state;authenticated=data.authenticated;csrf=data.csrf;
    $("access-toggle").textContent=authenticated?"Sair":"Entrar";
    $("state-title").textContent=labels[current.state] || current.state;
    $("state-message").textContent=current.message;
    $("worker-label").textContent=data.worker.available?"Serviço Windows disponível":"Serviço Windows sem comunicação recente";
    const terminal=["STOPPED","ERROR","INSUFFICIENT_DATA","TRAINING_UNAVAILABLE","TRAINING_BLOCKED"].includes(current.state);
    $("start").disabled=busy || !terminal;$("pause").disabled=busy || terminal || current.desired!=="running";
    $("stop").disabled=busy || terminal || current.desired==="stopped";
    $("resume").hidden=current.desired!=="paused";$("resume").disabled=busy;
    $("lot").disabled=!terminal || busy;
    if(!terminal && current.lot)$("lot").value=current.lot;
    if(current.symbol_contract){$("lot").min=current.symbol_contract.volume_min;$("lot").max=current.symbol_contract.volume_max;$("lot").step=current.symbol_contract.volume_step;}
    const stages=["connection","history","training","validation","analysis"],index=stages.indexOf(current.stage);
    for(const step of $("steps").children){const i=stages.indexOf(step.dataset.stage);step.classList.toggle("current",i===index);step.classList.toggle("done",index>=0 && i<index);}
    const history=current.history;
    $("history-info").textContent=history?`Histórico: ${date(history.start)} a ${date(history.end)} UTC · ${Object.values(history.bars).reduce((a,b)=>a+b,0).toLocaleString("pt-BR")} candles nos períodos exigidos.`:"O histórico será verificado ao iniciar.";
    const training=current.training;
    $("model-version").textContent=training?.active_version || "Nenhuma versão aprovada";
    $("samples").textContent=training?.samples===null || training?.samples===undefined?"Ainda não calculadas":training.samples.toLocaleString("pt-BR");
    $("training-state").textContent=({not_implemented:"Treinamento integrado em implementação",running:"Em treinamento",preparing_examples:"Identificando hipóteses",forecasting:"Gerando previsões Timestral",replaying:"Simulando oportunidades",validating:"Em validação",validated_pending_approval:"Versão candidata aguarda aprovação",approved:"Versão validada",rejected:"Versão reprovada",insufficient_samples:"Amostra insuficiente"})[training?.status] || "Aguardando preparação";
    const reasons={INSUFFICIENT_DEVELOPMENT_OR_VALIDATION_SAMPLES:"Ainda faltam experiências completas nos períodos de desenvolvimento ou validação.",INSUFFICIENT_DEVELOPMENT_SAMPLES_OR_CLASSES:"O treino exige mais operações encerradas e exemplos de ganhos e perdas.",INSUFFICIENT_CALIBRATION_CLASSES:"Faltam ganhos e perdas no período separado para calibrar o modelo.",INSUFFICIENT_WALK_FORWARD_SAMPLES:"A amostra ainda não permite repetir o ajuste e a avaliação em janelas posteriores.",INSUFFICIENT_OPERATIONAL_VALIDATION_SAMPLES:"O modelo foi pesquisado, mas faltam oportunidades operacionalmente elegíveis no período de validação.",NO_VALIDATED_INCREMENTAL_ADVANTAGE:"O modelo não demonstrou melhoria suficiente na validação após custos.",INSUFFICIENT_FINAL_SAMPLES:"Ainda faltam exemplos no período final reservado.",FINAL_EVALUATION_REJECTED:"A versão não cumpriu os critérios no teste final.",PAPER_VERSION_REQUIRES_EXPLICIT_APPROVAL:"A versão é candidata à simulação. Ela ainda não foi aprovada pelo operador."};
    $("training-detail").textContent=training?.message || reasons[training?.reason] || "A disponibilidade de histórico ou previsões isoladas não significa que o treinamento integrado foi concluído.";
    $("training-metrics").replaceChildren();
    if(training?.partitions){
      const counts=document.createElement("p");counts.textContent=`Experiências: ${training.partitions.development} em desenvolvimento, ${training.partitions.validation} em validação e ${training.partitions.final} no período final. ${training.partitions.purged} excluídas por cruzar os limites temporais.`;$("training-metrics").append(counts);
      const reserved=document.createElement("p");reserved.className="muted";reserved.textContent=training.final_accessed?"O teste final foi consultado para esta versão; novos ajustes precisam de uma nova avaliação independente.":"O resultado do teste final permanece reservado.";$("training-metrics").append(reserved);
    }
    const comparison=training?.final;
    if(comparison){
      const table=document.createElement("table"),head=document.createElement("tr");
      for(const title of ["Teste final","Operações","Resultado líquido (USD)","Maior queda (%)"]){const th=document.createElement("th");th.textContent=title;head.append(th);}const thead=document.createElement("thead");thead.append(head);table.append(thead);
      const body=document.createElement("tbody");for(const [key,label] of [["technical","Técnico"],["timestral","Filtro Timestral"],["combined","Modelo conjunto"]]){const result=comparison[key];if(!result)continue;const row=document.createElement("tr");for(const value of [label,result.closed_trades,number(result.net_pnl),number(result.max_close_equity_drawdown_pct)]){const td=document.createElement("td");td.textContent=value;row.append(td);}body.append(row);}table.append(body);$("training-metrics").append(table);
    }
    const decision=current.last_decision;
    $("decision-action").textContent=decision?({BUY:"Comprar",SELL:"Vender",WAIT:"Aguardar",NO_TRADE:"Aguardar"}[decision.action] || decision.action):"Nenhuma decisão operacional";
    $("decision-reason").textContent=decision?.reason || "O agente precisa concluir a preparação e ter uma versão validada.";
    for(const [id,key] of [["entry","entry"],["stop-price","stop"],["target","target"],["risk","risk"]])$(id).textContent=number(decision?.[key]);
    $("position").textContent=current.position?`${current.position.side} · lote ${current.position.lot} · entrada ${number(current.position.entry)}`:"Nenhuma posição simulada registrada nesta sessão.";
    $("updated").textContent=`Estado registrado: ${date(current.updated_at)} UTC`;
  }
  async function refresh(){if(polling)return;polling=true;try{render(await api(""));}catch(e){error(e.message);}finally{polling=false;}}
  async function command(action){
    if(busy)return;
    if(!authenticated){$("access-form").hidden=false;$("password").focus();$("access-message").textContent="Entre e depois clique novamente no comando desejado.";return;}
    busy=true;
    const payload={action,mode:"paper",...(action==="START"?{lot:$("lot").value}:{})},signature=JSON.stringify(payload);
    if(!pending || pending.signature!==signature)pending={signature,key:Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,"0")).join("")};
    for(const id of ["start","pause","resume","stop"])$(id).disabled=true;
    try{await api("/command",payload,pending.key);pending=null;error("");}catch(e){error(e.message);}finally{busy=false;await refresh();}
  }
  for(const [id,action] of [["start","START"],["pause","PAUSE"],["resume","RESUME"],["stop","STOP"]])$(id).onclick=()=>command(action);
  $("access-toggle").onclick=async()=>{if(authenticated){try{await api("/logout",{});await refresh();}catch(e){error(e.message);}return;}$("access-form").hidden=!$("access-form").hidden;if(!$("access-form").hidden)$("password").focus();};
  $("access-form").onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{await api("/login",{password:$("password").value});$("password").value="";$("access-form").hidden=true;error("");await refresh();}catch(e){$("access-message").textContent=e.message;}finally{button.disabled=false;}};
  async function quote(){try{const response=await fetch("/api/mt5/chart?timeframe=M5&count=120",{cache:"no-store"}),data=await response.json();if(!response.ok || !data.ok)throw new Error(data.error || "Cotação indisponível.");chartData=data;$("quote").textContent=`Compra (ask): ${number(data.quote?.ask)} · Venda (bid): ${number(data.quote?.bid)}`;$("chart-time").textContent=`${date(data.quote?.time)} UTC`;$("chart-message").textContent="Preço do MT5. O último candle ainda pode estar em formação.";draw();}catch(e){$("chart-message").textContent=e.message;}}
  function draw(){
    const canvas=$("chart"),box=canvas.getBoundingClientRect(),ratio=window.devicePixelRatio || 1,ctx=canvas.getContext("2d");canvas.width=box.width*ratio;canvas.height=box.height*ratio;ctx.scale(ratio,ratio);ctx.fillStyle="#0b151c";ctx.fillRect(0,0,box.width,box.height);
    const rows=chartData?.candles?.slice(-100);if(!rows?.length)return;
    let low=Math.min(...rows.map(c=>c.low)),high=Math.max(...rows.map(c=>c.high));const pad=(high-low || .0001)*.1;low-=pad;high+=pad;
    const right=box.width-65,bottom=box.height-22,step=(right-10)/rows.length,y=p=>bottom-(p-low)*(bottom-14)/(high-low);ctx.font="10px system-ui";
    for(let i=0;i<=4;i++){const price=low+(high-low)*i/4;ctx.strokeStyle="#233440";ctx.beginPath();ctx.moveTo(10,y(price));ctx.lineTo(right,y(price));ctx.stroke();ctx.fillStyle="#9bb0bf";ctx.fillText(price.toFixed(5),right+5,y(price)+3);}
    rows.forEach((bar,i)=>{const x=10+(i+.5)*step;ctx.fillStyle=ctx.strokeStyle=bar.close>=bar.open?"#49d6a4":"#ec778e";ctx.beginPath();ctx.moveTo(x,y(bar.high));ctx.lineTo(x,y(bar.low));ctx.stroke();ctx.fillRect(x-step*.3,Math.min(y(bar.open),y(bar.close)),Math.max(1,step*.6),Math.max(1,Math.abs(y(bar.open)-y(bar.close))));if(i%25===0){ctx.fillStyle="#9bb0bf";ctx.fillText(new Date(bar.timestamp).toLocaleTimeString("pt-BR",{timeZone:"UTC",hour:"2-digit",minute:"2-digit"}),x,box.height-4);}});
  }
  new ResizeObserver(draw).observe($("chart"));refresh();quote();setInterval(refresh,5000);setInterval(quote,10000);
})();
