"use strict";
(() => {
  const $=id=>document.getElementById(id);
  const labels={STOPPED:"Agente parado",QUEUED:"Início solicitado",CONNECTING:"Conectando ao MT5",LOADING_HISTORY:"Preparando o histórico",ANALYZING:"Analisando o mercado",POSITION_OPEN:"Operação em andamento",PAUSE_REQUESTED:"Pausa solicitada",PAUSED:"Agente pausado",STOP_REQUESTED:"Parada solicitada",ERROR:"Aguardando recuperação",INSUFFICIENT_DATA:"Histórico insuficiente"};
  let current=null, csrf="", busy=false, pending=null, chartData=null, polling=false;
  let quotePending=false,chartStale=true;
  const chartCacheKey="aurelia-eurusd-m5-chart-v1";
  function cacheChart(data){try{localStorage.setItem(chartCacheKey,JSON.stringify({saved_at:Date.now(),data:{candles:data.candles.slice(-120),quote:data.quote,source_clock:data.source_clock}}));}catch{}}
  function restoreChart(){try{const cached=JSON.parse(localStorage.getItem(chartCacheKey));if(cached && Date.now()-cached.saved_at>=0 && Date.now()-cached.saved_at<7*86400000 && validChart(cached.data)){chartData=cached.data;showQuote();$("chart-message").textContent="Último gráfico salvo, desatualizado. Aguardando conexão para atualizar.";draw();}}catch{}}
  function validChart(data){return Array.isArray(data?.candles) && data.candles.length>0 && data.candles.every(row=>[row.open,row.high,row.low,row.close].every(p=>Number.isFinite(p)&&p>0)&&Number.isFinite(Date.parse(row.timestamp))) && Number.isFinite(data.quote?.bid) && Number.isFinite(data.quote?.ask) && Number.isFinite(Date.parse(data.quote?.time));}
  function showQuote(){if(!chartData)return;$("quote").textContent=`${chartStale?"Última cotação (desatualizada) · ":""}Compra (ask): ${number(chartData.quote.ask)} · Venda (bid): ${number(chartData.quote.bid)}`;$("chart-time").textContent=`${date(chartData.quote.time)} UTC`;}
  labels.ANALYSIS_WARMUP="Preparando o contexto ao vivo";
  labels.WAITING_QUOTE="Aguardando fonte válida";
  labels.WAITING_SOURCE="Aguardando conexão com o MT5";
  labels.RECOVERING="Reconectando o agente";
  const reasonsDecision={REGIME_DATA_UNAVAILABLE:"Dados insuficientes ou inválidos para classificar o regime.",TRANSITION_EXPIRED_WAITING_CONTEXT:"A transição expirou; aguardando um novo contexto confirmado.",REGIME_CONFIRMATION_PENDING:"Aguardando novas barras H1 fechadas para confirmar o regime.",REGIME_UNCLASSIFIED:"Os dados estão disponíveis, mas o regime ainda não foi definido.",TREND_CONTEXT_MISSING:"Contexto de tendência ausente.",TREND_REGIME_REQUIRED:"Aguardando regime de tendência; novas entradas bloqueadas fora de TREND.",TREND_CONFIRMATION_REQUIRED:"H4 e H1 precisam de tendência estrutural confirmada.",TREND_TIMEFRAME_CONFLICT:"H4 e H1 estão em direções opostas; aguardando alinhamento.",COUNTERTREND_ENTRY_BLOCKED:"Sinal contra a tendência: entrada bloqueada.",INSUFFICIENT_CONTEXT:"Falta contexto para avaliar esta oportunidade.",DAILY_CONTEXT_INSUFFICIENT:"O contexto diário ainda está em preparação.",REGIME_UNKNOWN:"O regime ainda está indefinido.",REGIME_RANGE:"O mercado está lateral; este setup de tendência não é elegível.",REGIME_TRANSITION:"O regime está em transição; o agente aguarda clareza.",OUTSIDE_SESSION:"Fora das sessões permitidas para novas entradas.",CONTEXT_TREND_UNRESOLVED:"A direção do contexto ainda não foi confirmada.",INVALIDATING_EVIDENCE:"Há evidência que invalida a oportunidade.",NONCONTIGUOUS_TRIGGER:"Faltam candles contíguos para confirmar o gatilho.",SPREAD_UNAVAILABLE_OR_HIGH:"Spread indisponível ou acima do limite.",VOLATILITY_UNAVAILABLE:"Ainda não foi possível medir a volatilidade.",WAITING_PULLBACK_TRIGGER:"Aguardando correção e fechamento que confirme o gatilho.",STOP_TOO_NARROW:"A distância do stop é insuficiente para a volatilidade e os custos.",HISTORY_NOT_READY:"O histórico mensal precisa ser atualizado antes de abrir operações.",SIGNAL_TOO_OLD:"A oportunidade já passou; o agente aguardará um novo candle.",POSITION_ALREADY_OPEN:"Uma posição já está sendo acompanhada.",PRICE_MOVED_OUTSIDE_FROZEN_LEVELS:"O preço mudou e invalidou os níveis da proposta.",FIXED_LOT_EXCEEDS_RISK_BUDGET:"O lote escolhido excede o limite de risco para este stop.",NET_RISK_REWARD_TOO_LOW:"A relação retorno/risco após custos ficou abaixo do mínimo.",DAILY_TRADE_LIMIT:"Limite diário de operações atingido.",DAILY_LOSS_LIMIT:"Limite diário de perda atingido.",DRAWDOWN_LIMIT:"Limite de queda da conta simulada atingido.",SPREAD_LIMIT:"Spread acima do limite.",SESSION_NOT_AUTHORIZED:"A sessão atual não permite novas entradas."};
  Object.assign(reasonsDecision,{LEARNED_CONTEXT_SUSPENDED:'Este contexto teve desempenho recente negativo. Novas entradas suspensas; alternativas continuam em simulação.',LEARNED_VARIANT_FILTER_WAIT:'A alternativa aprendida aguarda sua confirmação de entrada.',MODEL_RELOAD_PENDING:'Aguardando carregar a versão do modelo; novas entradas bloqueadas durante a troca.'});
  const decisionReason=value=>String(value || "").split(", ").map(code=>reasonsDecision[code] || code).join(" ");
  const date=value=>value?new Date(value).toLocaleString("pt-BR",{timeZone:"UTC",hour12:false}):"—";
  const number=value=>typeof value==="number"?value.toLocaleString("pt-BR",{maximumFractionDigits:5}):"—";
  async function api(path,payload,key){
    const controller=new AbortController(),deadline=setTimeout(()=>controller.abort(),12000);
    try{const response=await fetch(`/api/diagnostics/agent${path}`,{signal:controller.signal,cache:"no-store",...(payload?{method:"POST",headers:{"Content-Type":"application/json","X-Diagnostics-CSRF":csrf,...(key?{"Idempotency-Key":key}:{})},body:JSON.stringify(payload)}:{})});
    const result=await response.json(); if(!response.ok || !result.ok)throw new Error(result.error || "Não foi possível consultar o agente."); return result;}finally{clearTimeout(deadline);}
  }
  function error(message){$("error").textContent=message;$("error").hidden=!message;}
  function render(data){
    current=data.state;csrf=data.csrf;
    const trend=current.last_decision?.trend_context,dir=t=>t?.direction==='bullish'?'alta':t?.direction==='bearish'?'baixa':'indefinida';
    $("trend-status").textContent=current.autonomy?.entry_policy==='trend-only-h4-h1-confirmed-v1'?`Filtro obrigatório ativo · H4: ${dir(trend?.macro_trend)} · H1: ${dir(trend?.context_trend)}. Confirmação estrutural exigida nos dois períodos.`:"Aguardando confirmação do processo com a política de tendência atualizada.";
    $("state-title").textContent=labels[current.state] || current.state;
    $("state-message").textContent=current.message;
    $("worker-label").textContent=data.worker.available?"Serviço Windows disponível":"Serviço Windows sem comunicação recente";
    if(!data.worker.available && current.desired==="running"){
      $("state-title").textContent="Agente sem comunicação";
      $("state-message").textContent="O serviço Windows não está confirmando atividade. Último estado registrado: "+(labels[current.state] || current.state)+". Aguardando reconexão automática.";
    }
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
    const stages=["connection","history","analysis"],index=stages.indexOf(current.stage);
    for(const step of $("steps").children){const i=stages.indexOf(step.dataset.stage);step.classList.toggle("current",i===index);step.classList.toggle("done",index>=0 && i<index);}
    const history=current.history;
    $("history-info").textContent=history?`Histórico: ${date(history.start)} a ${date(history.end)} UTC · ${Object.values(history.bars).reduce((a,b)=>a+b,0).toLocaleString("pt-BR")} candles nos períodos exigidos.`:"O histórico será verificado ao iniciar.";
    const training=current.training;
    const autonomous=["autonomous_paper","autonomous_demo"].includes(current.execution_profile) || training?.status==="autonomous_research";
    $("autonomous-learning").hidden=!autonomous;
    $("hypotheses-table").replaceChildren();
    $("autonomy-info").textContent=autonomous?`Memória histórica inicial: ${current.autonomy?.historical_samples ?? "preparando"} experiências de desenvolvimento compatíveis com a política atual. Novos resultados são gravados por hipótese e contexto. ${current.autonomy?.previous_policy_results || 0} resultados de políticas anteriores preservados separadamente.`:"";
    if(current.autonomy){
      const table=document.createElement("table"),head=document.createElement("tr");
      for(const title of ["Hipótese","Resultados avaliados","Ganhos","Perdas","Resultado (USD)"]){const th=document.createElement("th");th.textContent=title;head.append(th);}table.append(head);
      for(const row of current.autonomy.hypotheses || []){const tr=document.createElement("tr");for(const value of [row.name,row.n,row.wins,row.losses,number(row.net_pnl)]){const td=document.createElement("td");td.textContent=value;tr.append(td);}table.append(tr);}$("hypotheses-table").append(table);
    }
    const reward=current.autonomy?.last_result;
    $("last-learning").textContent=reward?`Último resultado usado na pesquisa: ${number(reward.net_pnl)} USD. ${reward.net_pnl>0?"Evidência favorável registrada neste contexto.":"A próxima seleção priorizará outra hipótese elegível."}`:"Aguardando o primeiro resultado observado. Ganhos e perdas atualizam evidências; um único resultado não comprova uma estratégia.";
    $("model-version").textContent="Seleção autônoma por contexto";
    $("samples").textContent=current.autonomy?.historical_samples ?? "Preparando memória";
    $("training-state").textContent=training?.status==="autonomous_research"?"Pesquisa autônoma ativa":"Aguardando preparação";
    $("training-detail").textContent="A memória combina experiências históricas de desenvolvimento com resultados novos da sessão. Isso não altera os pesos do Timestral nem comprova lucratividade.";
    const learning=current.autonomy?.continual;
    if(learning){
      $("autonomy-info").textContent=`${learning.observations} candles novos observados · ${learning.eligible_signals} oportunidades elegíveis · ${learning.real_results} resultados da sessão aprendidos · ${learning.suspended_contexts} contextos suspensos por desempenho recente.`;
      $("hypotheses-table").replaceChildren();const table=document.createElement('table'),head=document.createElement('tr');
      for(const title of ['Alternativa','Simulações encerradas','Ganhos','Resultado simulado (USD)','Estratégia']){const th=document.createElement('th');th.textContent=title;head.append(th);}table.append(head);
      for(const row of learning.variants){const tr=document.createElement('tr');for(const value of [row.name,row.closed,row.wins,number(row.net_pnl),row.active?'Em uso':'Em avaliação']){const td=document.createElement('td');td.textContent=value;tr.append(td);}table.append(tr);}$("hypotheses-table").append(table);
      $("last-learning").textContent=learning.last_result?`Último resultado da sessão: ${number(learning.last_result.net_pnl)} USD. A memória foi atualizada no contexto dessa entrada.`:'Aguardando resultados novos. As alternativas são simuladas em paralelo; esses resultados não são operações da conta demo.';
      $("model-version").textContent=learning.champion_name;$("samples").textContent=learning.real_results;
      const review=learning.hypothesis_review;
      if(review){
        const labels={COSTS_CONSUMED_GROSS_GAIN:'Os custos consumiram o ganho bruto.',NET_POSITIVE:'Resultado positivo após custos.',NET_NEGATIVE:'Resultado negativo após custos.',FLAT:'Resultado líquido zero.'};
        const stages={COLLECTING_FUTURE:'Coletando dados futuros por 14 dias',INSUFFICIENT_FUTURE_SAMPLE:'Amostra futura insuficiente',PROMISING_REQUIRES_PORTFOLIO_TEST:'Indicação favorável; falta testar a carteira',NOT_SUPPORTED:'Melhoria não sustentada nos dados futuros',INVALIDATED_DATA_GAP:'Avaliação invalidada por lacuna nos dados'};
        const p=review.proposal;
        const rules={CONTRADICTIONS:'evitar hipóteses com evidências contrárias',WEAK_BODY:'evitar candles com corpo menor que metade do ATR',FORECAST_DISAGREES:'exigir confirmação dos dois horizontes do Timestral',FORECAST_BELOW_COST:'exigir deslocamento previsto maior que os custos estimados'};
        $("last-learning").textContent=`Revisão automática: ${review.reviewed} simulações da estratégia base avaliadas. ${labels[review.last_review?.assessment]||'Aguardando resultado de uma hipótese com crítica registrada.'} ${p?`Proposta: ${rules[p.rule]||p.rule}. ${stages[p.status]||p.status} · ${review.future_samples}/${p.minimum_samples} resultados mínimos · fim da coleta: ${date(p.ends_at)} UTC. Nenhuma ativação automática por esta pesquisa.`:'Buscando evidência para formular uma melhoria; nenhuma proposta criada ainda.'}`;
      }
      $("training-state").textContent=learning.evidence_status==='VALIDATED_ALTERNATIVE'?'Alternativa validada em uso':'Aprendendo e comparando';
      $("training-detail").textContent=learning.last_change?`Última mudança automática: ${learning.last_change.previous} → ${learning.last_change.selected}. Memória preservada no PostgreSQL. O retreinamento do Timestral funciona em segundo plano.`:'O agente atualiza a memória após cada resultado. Uma alternativa precisa de pelo menos 7 dias, 20 operações por versão e evidência favorável para substituir a base. O Timestral recebe retreino automático com dados novos.';
      if(current.desired!=='running'||!data.worker.available){$("training-state").textContent='Memória preservada';$("training-detail").textContent='A observação contínua retorna quando o agente estiver iniciado e o serviço Windows disponível.';}
    }
    const decision=current.last_decision;
    $("decision-action").textContent=decision?({BUY:"Comprar",SELL:"Vender",WAIT:"Aguardar",NO_TRADE:"Aguardar"}[decision.action] || decision.action):"Nenhuma decisão operacional";
    $("decision-reason").textContent=decisionReason(decision?.reason) || "Escolha o lote e inicie o agente para preparar o contexto.";
    if(autonomous && !decision)$("decision-reason").textContent="Preparando contexto ou aguardando um gatilho para testar uma hipótese automaticamente.";
    for(const [id,key] of [["entry","entry"],["stop-price","stop"],["target","target"],["risk","risk"]])$(id).textContent=number(decision?.[key]);
    $("position").textContent=current.position?`${current.position.side==="long"?"Compra":"Venda"} · lote ${current.position.lot} · entrada ${number(current.position.entry)} · ${date(current.position.entry_at)} UTC`:"Nenhuma posição registrada nesta sessão.";
    $("pnl-today").textContent=number(current.account?.realized_today);
    $("pnl-open").textContent=number(current.account?.unrealized_pnl);
    $("closed-trades").textContent=current.account?.closed_trades ?? "—";
    $("decision-time").textContent=decision?`Decisão: ${date(decision.at)} UTC · candle de referência: ${date(decision.candle)} UTC`:"";
    draw();
    $("updated").textContent=`Estado registrado: ${date(current.updated_at)} UTC`;
  }
  async function refresh(){if(polling)return;polling=true;try{render(await api(""));}catch(e){error(e.message);}finally{polling=false;}}
  async function command(action){
    if(busy)return;
    busy=true;
    const payload={action,mode:action==="START"?$("execution-mode").value:(current.mode || "paper"),...(action==="START"?{lot:$("lot").value}:{})},signature=JSON.stringify(payload);
    if(!pending || pending.signature!==signature)pending={signature,key:Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,"0")).join("")};
    for(const id of ["start","pause","resume","stop"])$(id).disabled=true;
    try{await api("/command",payload,pending.key);pending=null;error("");}catch(e){error(e.message);}finally{busy=false;await refresh();}
  }
  for(const [id,action] of [["start","START"],["pause","PAUSE"],["resume","RESUME"],["stop","STOP"]])$(id).onclick=()=>command(action);
  async function quote(){
    if(quotePending)return;quotePending=true;
    const controller=new AbortController(),deadline=setTimeout(()=>controller.abort(),12000);
    try{const response=await fetch("/api/mt5/chart?timeframe=M5&count=120",{cache:"no-store",signal:controller.signal}),data=await response.json();if(!response.ok || !data.ok || !validChart(data))throw new Error("Cotação indisponível.");chartData=data;chartStale=Math.abs(Date.now()-Date.parse(data.quote.time))>60000;cacheChart(data);showQuote();$("chart-message").textContent=chartStale?"Última cotação disponível no MT5, sem tick recente. Aguardando atualização.":"Preço do MT5. O último candle ainda pode estar em formação.";draw();}
    catch{chartStale=true;showQuote();$("chart-message").textContent="Ponte de dados indisponível; reconectando automaticamente."+(chartData?" Último gráfico preservado e desatualizado; não é cotação em tempo real.":"");draw();}
    finally{clearTimeout(deadline);quotePending=false;}
  }
  function draw(){
    const canvas=$("chart"),box=canvas.getBoundingClientRect(),ratio=window.devicePixelRatio || 1,ctx=canvas.getContext("2d");canvas.width=box.width*ratio;canvas.height=box.height*ratio;ctx.scale(ratio,ratio);ctx.fillStyle="#0b151c";ctx.fillRect(0,0,box.width,box.height);
    const rows=chartData?.candles?.slice(-100);if(!rows?.length)return;
    const forecast=current?.last_decision?.forecast, now=Date.now();
    const usable=!chartStale && forecast && forecast.symbol==="EURUSD" && forecast.timeframe==="M5" && forecast.clock_id===chartData.source_clock?.clock_id && now>=Date.parse(forecast.reference_at) && now<Date.parse(forecast.valid_until) && Math.abs(now-Date.parse(chartData.quote?.time))<60000 && forecast.points?.length===12;
    const points=usable?[{at:forecast.reference_at,low:forecast.reference_price,median:forecast.reference_price,high:forecast.reference_price},...forecast.points]:[];
    $("forecast-note").textContent=usable?`Timestral · estimativa avaliada nesta oportunidade · referência ${date(forecast.reference_at)} UTC · faixa Q10–Q90 nominal, sem garantia de cobertura.`:forecast?"A previsão da última oportunidade está antiga ou pertence a outra fonte. Aguardando nova avaliação.":"A previsão aparece quando uma oportunidade técnica é avaliada pelo modelo. Ainda não há previsão operacional atual.";
    const position=current?.position, levels=!chartStale && position && current.history?.clock_id===chartData.source_clock?.clock_id?[position.entry,position.stop,position.target]:[];
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
  new ResizeObserver(draw).observe($("chart"));restoreChart();refresh();quote();setInterval(refresh,5000);setInterval(quote,10000);
  document.addEventListener("visibilitychange",()=>{if(!document.hidden){refresh();quote();}});
})();
