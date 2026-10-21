"use strict";
(() => {
  const $=id=>document.getElementById(id);
  const labels={STOPPED:"Agente parado",QUEUED:"Início solicitado",CONNECTING:"Conectando ao MT5",LOADING_HISTORY:"Preparando o histórico",PREPARING_EXPERIENCES:"Identificando hipóteses de pesquisa",FORECASTING:"Gerando previsões históricas",REPLAYING:"Simulando oportunidades históricas",TRAINING:"Treinamento em andamento",VALIDATING:"Validando a versão candidata",ANALYZING:"Analisando o mercado",POSITION_OPEN:"Operação em andamento",PAUSE_REQUESTED:"Pausa solicitada",PAUSED:"Agente pausado",STOP_REQUESTED:"Parada solicitada",RECOVERY_REQUIRED:"Retomada exige revisão",ERROR:"Não foi possível iniciar",INSUFFICIENT_DATA:"Histórico insuficiente",TRAINING_UNAVAILABLE:"Histórico pronto · treinamento pendente",TRAINING_BLOCKED:"Treinamento concluído · operação bloqueada",AWAITING_APPROVAL:"Versão candidata aguarda aprovação"};
  let current=null, csrf="", busy=false, pending=null, chartData=null, polling=false;
  labels.CHECKING_MODEL="Verificando Timestral";
  labels.LOADING_RESEARCH_HISTORY="Preparando dados para o treino";
  labels.ANALYSIS_WARMUP="Preparando o contexto ao vivo";
  labels.WAITING_QUOTE="Aguardando fonte válida";
  labels.WAITING_SOURCE="Aguardando conexão com o MT5";
  const reasonsDecision={INSUFFICIENT_CONTEXT:"Falta contexto para avaliar esta oportunidade.",DAILY_CONTEXT_INSUFFICIENT:"O contexto diário ainda está em preparação.",REGIME_UNKNOWN:"O regime ainda está indefinido.",REGIME_RANGE:"O mercado está lateral; este setup de tendência não é elegível.",REGIME_TRANSITION:"O regime está em transição; o agente aguarda clareza.",OUTSIDE_SESSION:"Fora das sessões permitidas para novas entradas.",CONTEXT_TREND_UNRESOLVED:"A direção do contexto ainda não foi confirmada.",INVALIDATING_EVIDENCE:"Há evidência que invalida a oportunidade.",NONCONTIGUOUS_TRIGGER:"Faltam candles contíguos para confirmar o gatilho.",SPREAD_UNAVAILABLE_OR_HIGH:"Spread indisponível ou acima do limite.",VOLATILITY_UNAVAILABLE:"Ainda não foi possível medir a volatilidade.",WAITING_PULLBACK_TRIGGER:"Aguardando correção e fechamento que confirme o gatilho.",STOP_TOO_NARROW:"A distância do stop é insuficiente para a volatilidade e os custos.",HISTORY_NOT_READY:"O histórico mensal precisa ser atualizado antes de abrir operações.",MODEL_APPROVAL_EXPIRED:"A aprovação do modelo expirou. Encerre e inicie para preparar uma nova versão.",SIGNAL_TOO_OLD:"A oportunidade já passou; o agente aguardará um novo candle.",POSITION_ALREADY_OPEN:"Uma posição já está sendo acompanhada.",PRICE_MOVED_OUTSIDE_FROZEN_LEVELS:"O preço mudou e invalidou os níveis da proposta.",FIXED_LOT_EXCEEDS_RISK_BUDGET:"O lote escolhido excede o limite de risco para este stop.",NET_RISK_REWARD_TOO_LOW:"A relação retorno/risco após custos ficou abaixo do mínimo.",DAILY_TRADE_LIMIT:"Limite diário de operações atingido.",DAILY_LOSS_LIMIT:"Limite diário de perda atingido.",DRAWDOWN_LIMIT:"Limite de queda da conta simulada atingido.",SPREAD_LIMIT:"Spread acima do limite.",SESSION_NOT_AUTHORIZED:"A sessão atual não permite novas entradas."};
  const decisionReason=value=>String(value || "").split(", ").map(code=>reasonsDecision[code] || code).join(" ");
  const date=value=>value?new Date(value).toLocaleString("pt-BR",{timeZone:"UTC",hour12:false}):"—";
  const number=value=>typeof value==="number"?value.toLocaleString("pt-BR",{maximumFractionDigits:5}):"—";
  async function api(path,payload,key){
    const response=await fetch(`/api/diagnostics/agent${path}`,{cache:"no-store",...(payload?{method:"POST",headers:{"Content-Type":"application/json","X-Diagnostics-CSRF":csrf,...(key?{"Idempotency-Key":key}:{})},body:JSON.stringify(payload)}:{})});
    const result=await response.json(); if(!response.ok || !result.ok)throw new Error(result.error || "Não foi possível consultar o agente."); return result;
  }
  function error(message){$("error").textContent=message;$("error").hidden=!message;}
  function render(data){
    current=data.state;csrf=data.csrf;
    $("state-title").textContent=labels[current.state] || current.state;
    $("state-message").textContent=current.message;
    $("worker-label").textContent=data.worker.available?"Serviço Windows disponível":"Serviço Windows sem comunicação recente";
    const terminal=["STOPPED","ERROR","INSUFFICIENT_DATA","TRAINING_UNAVAILABLE","TRAINING_BLOCKED"].includes(current.state);
    $("start").disabled=busy || !terminal;$("pause").disabled=busy || terminal || current.desired!=="running";
    $("stop").disabled=busy || terminal || current.desired==="stopped";
    $("resume").hidden=current.desired!=="paused";$("resume").disabled=busy;
    $("lot").disabled=!terminal || busy;
    $("execution-mode").disabled=!terminal || busy;
    if(!terminal)$("execution-mode").value=current.mode || "paper";
    $("account-basis").textContent=current.mode==="demo"?"Resultados confirmados pelo MT5 Demo, com comissão e swap. Saldo e equidade são os da corretora.":"Simulador local: preenchimentos estimados por cotações observadas; não são negócios enviados ao MT5.";
    if(!terminal && current.lot)$("lot").value=current.lot;
    if(current.symbol_contract){$("lot").min=current.symbol_contract.volume_min;$("lot").max=current.symbol_contract.volume_max;$("lot").step=current.symbol_contract.volume_step;}
    const stages=["connection","history","training","validation","analysis"],index=stages.indexOf(current.stage);
    for(const step of $("steps").children){const i=stages.indexOf(step.dataset.stage);step.classList.toggle("current",i===index);step.classList.toggle("done",index>=0 && i<index);}
    const history=current.history;
    $("history-info").textContent=history?`Histórico: ${date(history.start)} a ${date(history.end)} UTC · ${Object.values(history.bars).reduce((a,b)=>a+b,0).toLocaleString("pt-BR")} candles nos períodos exigidos.`:"O histórico será verificado ao iniciar.";
    const training=current.training;
    const autonomous=["autonomous_paper","autonomous_demo"].includes(current.execution_profile) || training?.status==="autonomous_research";
    $("autonomous-learning").hidden=!autonomous;
    $("hypotheses-table").replaceChildren();
    $("autonomy-info").textContent=autonomous?`Memória histórica inicial: ${current.autonomy?.historical_samples ?? "preparando"} experiências de desenvolvimento. Novos resultados são gravados automaticamente por hipótese e contexto.`:"";
    if(current.autonomy){
      const table=document.createElement("table"),head=document.createElement("tr");
      for(const title of ["Hipótese","Resultados avaliados","Ganhos","Perdas","Resultado (USD)"]){const th=document.createElement("th");th.textContent=title;head.append(th);}table.append(head);
      for(const row of current.autonomy.hypotheses || []){const tr=document.createElement("tr");for(const value of [row.name,row.n,row.wins,row.losses,number(row.net_pnl)]){const td=document.createElement("td");td.textContent=value;tr.append(td);}table.append(tr);}$("hypotheses-table").append(table);
    }
    const reward=current.autonomy?.last_result;
    $("last-learning").textContent=reward?`Último resultado usado na pesquisa: ${number(reward.net_pnl)} USD. ${reward.net_pnl>0?"Evidência favorável registrada neste contexto.":"A próxima seleção priorizará outra hipótese elegível."}`:"Aguardando o primeiro resultado observado. Ganhos e perdas atualizam evidências; um único resultado não comprova uma estratégia.";
    $("approve").hidden=true;
    $("approve").disabled=busy || current.state!=="AWAITING_APPROVAL";
    $("approval-note").hidden=true;
    $("model-version").textContent=autonomous?"Seleção autônoma por contexto":training?.active_version || "Nenhuma versão aprovada";
    $("samples").textContent=autonomous?(current.autonomy?.historical_samples ?? "Preparando memória"):training?.samples===null || training?.samples===undefined?"Ainda não calculadas":training.samples.toLocaleString("pt-BR");
    $("training-state").textContent=({autonomous_research:"Pesquisa aut\u00f4noma ativa",not_implemented:"Treinamento integrado em implementação",running:"Em treinamento",preparing_examples:"Identificando hipóteses",forecasting:"Gerando previsões Timestral",replaying:"Simulando oportunidades",validating:"Em validação",validated_pending_approval:"Versão candidata aguarda aprovação",approved:"Versão validada",rejected:"Versão reprovada",insufficient_samples:"Amostra insuficiente"})[training?.status] || "Aguardando preparação";
    $("training-progress").textContent=training?.processed_bars!==undefined && ["preparing_examples","forecasting","replaying"].includes(training.status)?`Arquivo de pesquisa: ${training.research_history_days || "—"} dias, incluindo 30 dias de aquecimento. ${number(training.processed_bars)} de ${number(training.total_bars)} candles percorridos; ${number(training.candidates)} hipóteses identificadas. Hipóteses ainda não equivalem a operações encerradas ou amostras aprovadas.`:training?.training_period?`Pesquisa: ${date(training.training_period.start)} a ${date(training.training_period.end)} UTC. ${training.operational_validation_samples!==undefined && training.operational_validation_samples!==null?`${training.operational_validation_samples} oportunidades elegíveis na validação; mínimo de 20 operações para avaliar o resultado.`:""}`:"";
    const reasons={INSUFFICIENT_DEVELOPMENT_OR_VALIDATION_SAMPLES:"Ainda faltam experiências completas nos períodos de desenvolvimento ou validação.",INSUFFICIENT_DEVELOPMENT_SAMPLES_OR_CLASSES:"O treino exige mais operações encerradas e exemplos de ganhos e perdas.",INSUFFICIENT_CALIBRATION_CLASSES:"Faltam ganhos e perdas no período separado para calibrar o modelo.",INSUFFICIENT_WALK_FORWARD_SAMPLES:"A amostra ainda não permite repetir o ajuste e a avaliação em janelas posteriores.",INSUFFICIENT_OPERATIONAL_VALIDATION_SAMPLES:"O modelo foi pesquisado, mas faltam oportunidades operacionalmente elegíveis no período de validação.",NO_VALIDATED_INCREMENTAL_ADVANTAGE:"O modelo não demonstrou melhoria suficiente na validação após custos.",INSUFFICIENT_FINAL_SAMPLES:"Ainda faltam exemplos no período final reservado.",FINAL_EVALUATION_REJECTED:"A versão não cumpriu os critérios no teste final.",PAPER_VERSION_REQUIRES_EXPLICIT_APPROVAL:"A versão é candidata à simulação. Ela ainda não foi aprovada pelo operador."};
    $("training-detail").textContent=(training?.candidate_version?"Filtro candidato ajustado. ":"")+(training?.message || reasons[training?.reason] || "A disponibilidade de histórico ou previsões isoladas não significa que o treinamento integrado foi concluído.");
    const previous=data.last_training_report;
    $("last-research").textContent=!autonomous && previous && previous.report_id!==training?.report_id?`Última pesquisa concluída: ${previous.training_period?.days || "—"} dias de pesquisa, além de 30 dias de aquecimento; ${previous.samples} experiências encerradas. ${previous.candidate_version?"O filtro foi ajustado, mas ainda não foi aprovado.":"O ajuste ainda não pôde ser concluído."} ${typeof previous.operational_validation_samples==="number"?`${previous.operational_validation_samples} oportunidades operacionalmente elegíveis na validação; mínimo de 20 operações. `:""}${reasons[previous.reason] || ""} O processamento atual usa a janela indicada acima.`:"";
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
    $("decision-reason").textContent=decisionReason(decision?.reason) || "O agente precisa concluir a preparação e ter uma versão validada.";
    if(autonomous && !decision)$("decision-reason").textContent="Preparando contexto ou aguardando um gatilho para testar uma hipótese automaticamente.";
    for(const [id,key] of [["entry","entry"],["stop-price","stop"],["target","target"],["risk","risk"]])$(id).textContent=number(decision?.[key]);
    $("position").textContent=current.position?`${current.position.side==="long"?"Compra":"Venda"} · lote ${current.position.lot} · entrada ${number(current.position.entry)} · ${date(current.position.entry_at)} UTC`:"Nenhuma posição registrada nesta sessão.";
    $("pnl-today").textContent=number(current.account?.realized_today);
    $("pnl-open").textContent=number(current.account?.unrealized_pnl);
    $("closed-trades").textContent=current.account?.closed_trades ?? "—";
    $("decision-score").textContent=typeof decision?.probability==="number"?`Estimativa do modelo para resultado positivo: ${(100*decision.probability).toFixed(1)}% · limiar exigido: ${(100*decision.threshold).toFixed(1)}%. Não é garantia de acerto.`:"";
    $("decision-time").textContent=decision?`Decisão: ${date(decision.at)} UTC · candle de referência: ${date(decision.candle)} UTC`:"";
    draw();
    $("updated").textContent=`Estado registrado: ${date(current.updated_at)} UTC`;
  }
  async function refresh(){if(polling)return;polling=true;try{render(await api(""));}catch(e){error(e.message);}finally{polling=false;}}
  async function command(action){
    if(busy)return;
    busy=true;
    const payload={action,mode:action==="START"?$("execution-mode").value:(current.mode || "paper"),...(action==="START"?{lot:$("lot").value}:{}),...(action==="APPROVE"?{report_id:current.training.report_id}:{})},signature=JSON.stringify(payload);
    if(!pending || pending.signature!==signature)pending={signature,key:Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,"0")).join("")};
    for(const id of ["start","pause","resume","stop"])$(id).disabled=true;
    try{await api("/command",payload,pending.key);pending=null;error("");}catch(e){error(e.message);}finally{busy=false;await refresh();}
  }
  for(const [id,action] of [["start","START"],["pause","PAUSE"],["resume","RESUME"],["stop","STOP"]])$(id).onclick=()=>command(action);
  $("approve").onclick=()=>command("APPROVE");
  async function quote(){try{const response=await fetch("/api/mt5/chart?timeframe=M5&count=120",{cache:"no-store"}),data=await response.json();if(!response.ok || !data.ok)throw new Error(data.error || "Cotação indisponível.");chartData=data;$("quote").textContent=`Compra (ask): ${number(data.quote?.ask)} · Venda (bid): ${number(data.quote?.bid)}`;$("chart-time").textContent=`${date(data.quote?.time)} UTC`;$("chart-message").textContent="Preço do MT5. O último candle ainda pode estar em formação.";draw();}catch(e){$("chart-message").textContent=e.message;}}
  function draw(){
    const canvas=$("chart"),box=canvas.getBoundingClientRect(),ratio=window.devicePixelRatio || 1,ctx=canvas.getContext("2d");canvas.width=box.width*ratio;canvas.height=box.height*ratio;ctx.scale(ratio,ratio);ctx.fillStyle="#0b151c";ctx.fillRect(0,0,box.width,box.height);
    const rows=chartData?.candles?.slice(-100);if(!rows?.length)return;
    const forecast=current?.last_decision?.forecast, now=Date.now();
    const usable=forecast && forecast.symbol==="EURUSD" && forecast.timeframe==="M5" && forecast.clock_id===chartData.source_clock?.clock_id && now>=Date.parse(forecast.reference_at) && now<Date.parse(forecast.valid_until) && Math.abs(now-Date.parse(chartData.quote?.time))<60000 && forecast.points?.length===12;
    const points=usable?[{at:forecast.reference_at,low:forecast.reference_price,median:forecast.reference_price,high:forecast.reference_price},...forecast.points]:[];
    $("forecast-note").textContent=usable?`Timestral · estimativa avaliada nesta oportunidade · referência ${date(forecast.reference_at)} UTC · faixa Q10–Q90 nominal, sem garantia de cobertura.`:forecast?"A previsão da última oportunidade está antiga ou pertence a outra fonte. Aguardando nova avaliação.":"A previsão aparece quando uma oportunidade técnica é avaliada pelo modelo. Ainda não há previsão operacional atual.";
    const position=current?.position, levels=position && current.history?.clock_id===chartData.source_clock?.clock_id?[position.entry,position.stop,position.target]:[];
    let low=Math.min(...rows.map(c=>c.low),...points.map(p=>p.low),...levels),high=Math.max(...rows.map(c=>c.high),...points.map(p=>p.high),...levels);const pad=(high-low || .0001)*.1;low-=pad;high+=pad;
    const right=box.width-65,bottom=box.height-22,step=(right-10)/(rows.length+(usable?12:0)),y=p=>bottom-(p-low)*(bottom-14)/(high-low);ctx.font="10px system-ui";
    for(let i=0;i<=4;i++){const price=low+(high-low)*i/4;ctx.strokeStyle="#233440";ctx.beginPath();ctx.moveTo(10,y(price));ctx.lineTo(right,y(price));ctx.stroke();ctx.fillStyle="#9bb0bf";ctx.fillText(price.toFixed(5),right+5,y(price)+3);}
    rows.forEach((bar,i)=>{const x=10+(i+.5)*step;ctx.fillStyle=ctx.strokeStyle=bar.close>=bar.open?"#49d6a4":"#ec778e";ctx.beginPath();ctx.moveTo(x,y(bar.high));ctx.lineTo(x,y(bar.low));ctx.stroke();ctx.fillRect(x-step*.3,Math.min(y(bar.open),y(bar.close)),Math.max(1,step*.6),Math.max(1,Math.abs(y(bar.open)-y(bar.close))));if(i%25===0){ctx.fillStyle="#9bb0bf";ctx.fillText(new Date(bar.timestamp).toLocaleTimeString("pt-BR",{timeZone:"UTC",hour:"2-digit",minute:"2-digit"}),x,box.height-4);}});
    if(usable){
      const lastClose=Date.parse(rows.at(-1).timestamp)+300000,x=p=>10+(rows.length-.5+(Date.parse(p.at)-lastClose)/300000)*step;
      ctx.save();ctx.beginPath();ctx.rect(10,10,right-10,bottom-10);ctx.clip();ctx.fillStyle="rgba(128,187,255,.13)";ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(x(p),y(p.high)):ctx.moveTo(x(p),y(p.high)));[...points].reverse().forEach(p=>ctx.lineTo(x(p),y(p.low)));ctx.closePath();ctx.fill();ctx.strokeStyle="#80bbff";ctx.setLineDash([5,4]);ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(x(p),y(p.median)):ctx.moveTo(x(p),y(p.median)));ctx.stroke();ctx.restore();
    }
    if(levels.length){ctx.save();ctx.setLineDash([4,4]);for(const [label,price,color] of [["Entrada",position.entry,"#9bb0bf"],["Stop",position.stop,"#ec778e"],["Alvo",position.target,"#49d6a4"]]){ctx.strokeStyle=ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(10,y(price));ctx.lineTo(right,y(price));ctx.stroke();ctx.fillText(label,14,y(price)-4);}ctx.restore();}

  }
  new ResizeObserver(draw).observe($("chart"));refresh();quote();setInterval(refresh,5000);setInterval(quote,10000);
})();
