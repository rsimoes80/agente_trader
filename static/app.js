"use strict";

const state = { csrf: "", config: {}, selectedFile: null, backtest: null, toastTimer: null, typesafeConfigured: false, market: null, dukascopyConfigured: false, lastJevRequested: "" };
const numericKeys = new Set([
  "starting_balance", "risk_per_trade_pct", "max_daily_loss_pct", "max_drawdown_pct", "max_open_positions",
  "max_trades_per_day", "max_spread_pips", "max_slippage_pips", "minimum_risk_reward", "minimum_confluence",
  "ema_fast", "ema_slow", "rsi_period", "rsi_long_min", "rsi_long_max", "rsi_short_min", "rsi_short_max",
  "adx_period", "adx_min", "atr_period", "atr_min_pct", "atr_max_pct", "swing_window", "pullback_min_pct",
  "pullback_max_pct", "fib_zone_min_pct", "fib_zone_max_pct", "stop_atr_buffer", "maximum_bars_in_trade", "pip_size",
]);

function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => el.classList.remove("show"), 3600);
}

async function api(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Local-Token": state.csrf },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Falha na solicitação.");
  return data;
}

function setConfigFields(config) {
  document.querySelectorAll("[data-config]").forEach((input) => {
    const key = input.dataset.config;
    if (!(key in config)) return;
    if (input.type === "checkbox") input.checked = Boolean(config[key]);
    else input.value = config[key];
  });
  document.querySelectorAll('input[name="broker"]').forEach((input) => {
    input.checked = input.value === config.broker;
    input.closest(".broker-option")?.classList.toggle("selected", input.checked);
  });
  document.getElementById("overview-symbol").value = config.instrument || "EUR/USD";
  document.getElementById("overview-timeframe").value = config.timeframe || "H1";
  document.getElementById("metric-risk").innerHTML = `${Number(config.risk_per_trade_pct).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}<small>%</small>`;
  document.getElementById("metric-daily").textContent = `${Number(config.max_daily_loss_pct).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}%`;
  document.getElementById("protection-risk").textContent = `${Number(config.risk_per_trade_pct).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}%`;
  document.getElementById("protection-daily").textContent = `${Number(config.max_daily_loss_pct).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}%`;
  document.getElementById("protection-dd").textContent = `${Number(config.max_drawdown_pct).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}%`;
  document.getElementById("footer-instrument").textContent = config.instrument || "EUR/USD";
  document.getElementById("footer-timeframe").textContent = config.timeframe || "H1";
  syncProviderDetails(config.broker || "paper");
}

function collectConfig() {
  const result = { ...state.config, mode: "paper" };
  document.querySelectorAll("[data-config]").forEach((input) => {
    const key = input.dataset.config;
    if (input.type === "checkbox") result[key] = input.checked;
    else if (numericKeys.has(key)) result[key] = Number(input.value);
    else result[key] = input.value;
  });
  result.instrument = document.getElementById("overview-symbol").value.replace("/", "/");
  result.timeframe = document.getElementById("overview-timeframe").value;
  result.broker = document.querySelector('input[name="broker"]:checked')?.value || "paper";
  return result;
}

function navigate(name) {
  const pageNames = {
    overview: "Visão geral", strategy: "Estratégias", risk: "Gestão de risco", brokers: "Corretoras",
    backtest: "Backtest & dados", research: "Caderno de pesquisa",
  };
  if (!(name in pageNames)) return;
  document.querySelectorAll(".page").forEach((page) => page.classList.remove("active"));
  document.getElementById(`page-${name}`).classList.add("active");
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.page === name));
  document.getElementById("crumb-title").textContent = pageNames[name];
  window.history.replaceState(null, "", `#${name}`);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function syncProviderDetails(provider) {
  const names = {
    paper: ["Paper trading selecionado", "Nenhuma ordem será enviada."],
    interactive_brokers: ["Interactive Brokers selecionada", "TWS/IB Gateway requer uma sessão iniciada no terminal local."],
    mt5_community: ["MetaTrader 5 local", "A validação histórica lê candles do terminal aberto neste Windows; não exige senha nem envia ordens."],
    custom: ["Adaptador próprio selecionado", "Requer um plugin compatível com a interface do motor."],
  };
  const [title, description] = names[provider] || names.paper;
  document.getElementById("connector-name").textContent = title;
  document.getElementById("connector-description").textContent = description;
  const isIb = provider === "interactive_brokers";
  document.getElementById("credential-api-key").closest("label").hidden = isIb;
  document.getElementById("credential-api-secret").closest("label").hidden = isIb;
  document.getElementById("credential-access-token").closest("label").hidden = isIb;
  const saved = document.getElementById("credentials-saved");
  if (provider === "paper") {
    saved.textContent = "Paper não requer credenciais";
  } else if (provider === "mt5_community") {
    saved.textContent = "Usa a sessão já autenticada no terminal MT5";
  } else if (state.credentialsSaved) {
    saved.textContent = `Dados criptografados salvos · ${provider}`;
  } else {
    saved.textContent = "Nenhum segredo salvo";
  }
}

async function saveConfig() {
  try {
    const response = await api("/api/config", collectConfig());
    state.config = response.config;
    setConfigFields(state.config);
    toast("Parâmetros salvos localmente.");
  } catch (error) {
    toast(error.message);
  }
}

function splitCsvLine(line, delimiter) {
  const output = [];
  let current = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"' && line[index + 1] === '"' && quoted) { current += '"'; index += 1; }
    else if (char === '"') quoted = !quoted;
    else if (char === delimiter && !quoted) { output.push(current.trim()); current = ""; }
    else current += char;
  }
  output.push(current.trim());
  return output;
}

function parseCsv(text) {
  const rows = text.replace(/^\uFEFF/, "").split(/\r?\n/).filter((line) => line.trim());
  if (rows.length < 2) throw new Error("O CSV precisa ter cabeçalho e linhas de candles.");
  const delimiter = rows[0].includes(";") ? ";" : ",";
  const header = splitCsvLine(rows[0], delimiter).map((name) => name.toLowerCase().trim());
  const find = (...names) => header.findIndex((name) => names.includes(name));
  const indexes = {
    timestamp: find("timestamp", "datetime", "date", "time", "open_time", "etc/utc"),
    open: find("open", "open_price"), high: find("high", "high_price"),
    low: find("low", "low_price"), close: find("close", "close_price"), volume: find("volume", "tick_volume"),
  };
  for (const required of ["timestamp", "open", "high", "low", "close"]) {
    if (indexes[required] < 0) throw new Error(`Coluna obrigatória ausente: ${required}.`);
  }
  const result = [];
  for (const line of rows.slice(1)) {
    const cells = splitCsvLine(line, delimiter);
    const date = new Date(cells[indexes.timestamp]);
    if (Number.isNaN(date.getTime())) continue;
    const value = (key) => Number(String(cells[indexes[key]] || "").replace(delimiter === ";" ? "," : /$^/, "."));
    const candle = { timestamp: date.toISOString() };
    for (const key of ["open", "high", "low", "close"]) candle[key] = value(key);
    candle.volume = indexes.volume >= 0 ? value("volume") || 0 : 0;
    if (Object.values(candle).every((v) => typeof v === "string" || Number.isFinite(v))) result.push(candle);
  }
  if (result.length < 100) throw new Error(`O CSV tem ${result.length} candles válidos; importe pelo menos 100.`);
  if (result.length > 20_000) throw new Error("O limite é de 20.000 candles por execução.");
  return result;
}

function metricCard(label, value, suffix = "") {
  const card = document.createElement("div");
  card.className = "result-metric";
  const small = document.createElement("small"); small.textContent = label;
  const strong = document.createElement("strong"); strong.textContent = `${value}${suffix}`;
  card.append(small, strong);
  return card;
}

function drawEquity(points) {
  const canvas = document.getElementById("equity-chart");
  const bounds = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(300, Math.floor(bounds.width * ratio));
  canvas.height = Math.floor(210 * ratio);
  canvas.style.height = "210px";
  const ctx = canvas.getContext("2d");
  const width = canvas.width; const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  if (points.length < 2) return;
  const values = points.map((point) => point.equity);
  const min = Math.min(...values); const max = Math.max(...values);
  const pad = 14 * ratio; const range = Math.max(max - min, 0.01);
  ctx.strokeStyle = "#edf2ed"; ctx.lineWidth = 1 * ratio;
  for (let i = 1; i < 4; i += 1) { const y = (height / 4) * i; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke(); }
  const yFor = (value) => height - pad - ((value - min) / range) * (height - pad * 2);
  const xFor = (index) => pad + (index / (points.length - 1)) * (width - pad * 2);
  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, "rgba(104,160,114,.20)"); gradient.addColorStop(1, "rgba(104,160,114,0)");
  ctx.beginPath(); values.forEach((value, index) => index ? ctx.lineTo(xFor(index), yFor(value)) : ctx.moveTo(xFor(index), yFor(value)));
  ctx.lineTo(xFor(values.length - 1), height); ctx.lineTo(xFor(0), height); ctx.closePath(); ctx.fillStyle = gradient; ctx.fill();
  ctx.beginPath(); values.forEach((value, index) => index ? ctx.lineTo(xFor(index), yFor(value)) : ctx.moveTo(xFor(index), yFor(value)));
  ctx.lineWidth = 2 * ratio; ctx.strokeStyle = "#5c9b6b"; ctx.stroke();
}

function drawLivePrice(candles) {
  const canvas = document.getElementById("live-price-chart");
  if (!canvas || candles.length < 2 || canvas.closest(".hidden")) return;
  const ratio = window.devicePixelRatio || 1;
  const bounds = canvas.getBoundingClientRect();
  canvas.width = Math.max(300, Math.floor(bounds.width * ratio));
  canvas.height = Math.floor(210 * ratio);
  canvas.style.height = "210px";
  const ctx = canvas.getContext("2d");
  const values = candles.map((item) => Number(item.close)).filter(Number.isFinite);
  if (values.length < 2) return;
  const min = Math.min(...values); const max = Math.max(...values); const pad = 16 * ratio;
  const range = Math.max(max - min, 0.00001);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "#edf2ed"; ctx.lineWidth = ratio;
  for (let i = 1; i < 4; i += 1) { const y = (canvas.height / 4) * i; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke(); }
  const x = (i) => pad + i / (values.length - 1) * (canvas.width - 2 * pad);
  const y = (v) => canvas.height - pad - (v - min) / range * (canvas.height - 2 * pad);
  ctx.beginPath(); values.forEach((value, i) => i ? ctx.lineTo(x(i), y(value)) : ctx.moveTo(x(i), y(value)));
  ctx.strokeStyle = "#558c65"; ctx.lineWidth = 2 * ratio; ctx.stroke();
}

function renderLive(market) {
  state.market = market;
  const statusNames = { desconectado: "Feed desconectado", conectando: "Conectando FIX…", autenticando: "Autenticando FIX…", conectado: "Dukascopy · ao vivo", erro: "Falha no feed" };
  const active = market.status === "conectado";
  document.getElementById("live-feed-status").textContent = statusNames[market.status] || market.status || "Feed desconectado";
  document.getElementById("live-tag").innerHTML = `<i></i> ${active ? "AO VIVO" : market.status === "erro" ? "ERRO" : "SEM DADOS"}`;
  document.getElementById("live-tag").classList.toggle("live-active", active);
  const mid = market.quote?.mid;
  document.getElementById("live-price").textContent = Number.isFinite(mid) ? Number(mid).toFixed(5) : "—";
  document.getElementById("live-spread").textContent = Number.isFinite(market.spread_pips) ? `${Number(market.spread_pips).toFixed(1)} pips` : "—";
  const candles = market.candles || [];
  document.getElementById("live-candles").textContent = Number(market.closed_candles || candles.length).toLocaleString("pt-BR");
  document.getElementById("live-last-time").textContent = market.last_closed_candle_utc ? new Date(market.last_closed_candle_utc).toLocaleString("pt-BR") : `${Number(market.ticks || 0).toLocaleString("pt-BR")} atualizações de preço`;
  const analysis = market.analysis || {};
  const jev = market.jev_review;
  const jevCurrent = jev && jev.candle_time === market.last_closed_candle_utc;
  document.getElementById("live-signal").textContent = jevCurrent ? (jev.action === "approve" ? "JEV APROVOU" : "JEV VETOU") : analysis.signal === "BUY" ? "COMPRA" : analysis.signal === "SELL" ? "VENDA" : "AGUARDANDO";
  document.getElementById("live-signal-detail").textContent = analysis.market_intelligence ? `V3 · ${analysis.market_intelligence.evidence_status} · contexto ${analysis.market_intelligence.context_trend.state} · execução ${analysis.market_intelligence.execution_trend.state} · aguarda hipótese e risco` : jevCurrent ? "Revisão do cenário concluída · sem ordem" : analysis.required_bars ? `${candles.length}/${analysis.required_bars} candles para aquecer os indicadores` : "Filtros não confirmam entrada";
  const bid = market.quote?.bid; const ask = market.quote?.ask;
  document.getElementById("live-quote-summary").textContent = Number.isFinite(bid) && Number.isFinite(ask)
    ? `Bid ${Number(bid).toFixed(5)} · Ask ${Number(ask).toFixed(5)} · ${market.instrument || state.config.instrument} · ${state.config.timeframe}`
    : market.message || "As cotações Dukascopy aparecerão aqui quando o feed FIX estiver conectado.";
  document.getElementById("chart-empty").classList.toggle("hidden", candles.length > 1);
  document.getElementById("live-chart").classList.toggle("hidden", candles.length < 2);
  document.getElementById("live-chart-count").textContent = `${candles.length} candles · ${Number(market.ticks || 0).toLocaleString("pt-BR")} ticks`;
  const btn = document.getElementById("live-connect");
  btn.textContent = active || market.status === "conectando" || market.status === "autenticando" ? "Desconectar feed" : "Conectar feed Dukascopy";
  document.getElementById("radar-title").textContent = analysis.signal === "BUY" ? "Candidato de compra" : analysis.signal === "SELL" ? "Candidato de venda" : "Aguardando cenário claro";
  document.getElementById("radar-message").textContent = analysis.message || market.message || "Aguardando fechamento de candles para avaliar os filtros.";
  document.getElementById("radar-footnote").textContent = jevCurrent
    ? `${jev.action === "approve" ? "Jev aprovou o cenário" : "Jev bloqueou o candidato"}: ${jev.reason} Nenhuma ordem foi enviada.`
    : analysis.signal === "BUY" || analysis.signal === "SELL"
    ? "Candidato técnico em candle fechado. Ainda não confirmado pelo Jev e nenhuma ordem foi enviada."
    : `Leitura contínua · ${Number(market.closed_candles || 0)} candles fechados · somente dados`;
  const plot = candles.slice(-180);
  if (market.current_candle) plot.push(market.current_candle);
  requestAnimationFrame(() => drawLivePrice(plot));
  const autoReview = document.getElementById("live-jev-enabled")?.checked;
  const candleTime = market.last_closed_candle_utc;
  if (autoReview && state.typesafeConfigured && ["BUY", "SELL"].includes(analysis.signal) && candleTime && !jevCurrent && state.lastJevRequested !== candleTime) {
    state.lastJevRequested = candleTime;
    api("/api/market/jev-review", {}).then(() => refreshMarket()).catch((error) => toast(error.message));
  }
}

async function refreshMarket() {
  try {
    const response = await fetch("/api/market", { cache: "no-store" });
    if (response.ok) renderLive(await response.json());
  } catch (_) { /* A próxima atualização tentará novamente. */ }
}

async function toggleLiveFeed() {
  const active = ["conectado", "conectando", "autenticando"].includes(state.market?.status);
  try {
    const response = await api(active ? "/api/market/disconnect" : "/api/market/connect", {});
    toast(response.message);
    await refreshMarket();
  } catch (error) { toast(error.message); }
}

async function saveDukascopySettings(event) {
  event.preventDefault();
  const payload = {
    host: document.getElementById("fix-host").value.trim(),
    port: document.getElementById("fix-port").value,
    target_comp_id: document.getElementById("fix-target-comp").value.trim(),
    feed_sender_comp_id: document.getElementById("fix-sender-comp").value.trim(),
    username: document.getElementById("fix-username").value,
    password: document.getElementById("fix-password").value,
  };
  try {
    const response = await api("/api/dukascopy/settings", payload);
    state.dukascopyConfigured = true;
    document.getElementById("dukascopy-form").reset();
    document.getElementById("fix-saved").textContent = "Acesso FIX protegido neste computador";
    toast(response.message);
  } catch (error) { toast(error.message); }
}

function renderBacktest(result, candleCount, source = null) {
  const panel = document.getElementById("results-panel");
  panel.classList.remove("hidden");
  const metrics = result.metrics;
  const grid = document.getElementById("result-metrics"); grid.replaceChildren(
    metricCard("RESULTADO LÍQUIDO", `${metrics.net_pnl.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}`, " USD"),
    metricCard("RETORNO", `${metrics.return_pct.toFixed(2).replace(".", ",")}`, "%"),
    metricCard("TAXA DE ACERTO", `${metrics.win_rate_pct.toFixed(1).replace(".", ",")}`, "%"),
    metricCard("FATOR DE LUCRO", metrics.profit_factor === null ? "—" : String(metrics.profit_factor).replace(".", ",")),
    metricCard("DRAWDOWN MÁXIMO", `${metrics.max_drawdown_pct.toFixed(2).replace(".", ",")}`, "%"),
  );
  const sourceLabel = source ? ` · ${source.symbol} ${source.timeframe} via MT5 · ${new Date(source.from_utc).toLocaleString("pt-BR")} a ${new Date(source.to_utc).toLocaleString("pt-BR")}` : "";
  const validationLabel = result.validation_split_pct ? ` · validação fora da amostra: ${100 - result.validation_split_pct}% final` : "";
  document.getElementById("backtest-caption").textContent = `${candleCount.toLocaleString("pt-BR")} candles${sourceLabel}${validationLabel} · ${metrics.trades} operações simuladas`;
  const tbody = document.getElementById("trades-body"); tbody.replaceChildren();
  if (!result.trades.length) {
    const row = document.createElement("tr"); const cell = document.createElement("td"); cell.colSpan = 6; cell.textContent = "Nenhuma operação atingiu os filtros e limites selecionados."; row.append(cell); tbody.append(row);
  }
  for (const trade of result.trades) {
    const tr = document.createElement("tr"); tr.className = trade.pnl >= 0 ? "win" : "loss";
    const values = [new Date(trade.entry_time).toLocaleString("pt-BR"), trade.side === "long" ? "COMPRA" : "VENDA", Number(trade.entry).toFixed(5), `${Number(trade.stop).toFixed(5)} / ${Number(trade.target).toFixed(5)}`, `${Number(trade.pnl).toFixed(2)} USD`, ({ stop_loss: "Stop de perda", take_profit: "Alvo de ganho", time_exit: "Saída por tempo", daily_loss_limit: "Limite diário", max_drawdown_limit: "Limite de drawdown", end_of_data: "Fim dos dados" }[trade.reason] || trade.reason.replaceAll("_", " "))];
    values.forEach((value) => { const cell = document.createElement("td"); cell.textContent = value; tr.append(cell); });
    tbody.append(tr);
  }
  const assumptions = document.getElementById("execution-assumptions");
  const learning = result.learning || {};
  const learningNote = learning.active
    ? `Filtro adaptativo validado: ${learning.samples} opera\u00e7\u00f5es anteriores; bloqueios nesta simula\u00e7\u00e3o: ${metrics.adaptive_blocked || 0}.`
    : `Aprendizado inativo: ${learning.samples || 0}/${learning.required_samples || 100} opera\u00e7\u00f5es encerradas; este resultado n\u00e3o ensinou o modelo o bastante.`;
  const training = result.training_metrics;
  const splitNote = training ? `Treino inicial: ${training.trades} operações, resultado ${training.net_pnl.toFixed(2)} USD, acerto ${training.win_rate_pct.toFixed(1)}%, drawdown ${training.max_drawdown_pct.toFixed(2)}%. A validação final não foi usada para treinar o modelo. ` : "";
  const optimization = result.optimization;
  const optimizationNote = optimization ? `Busca: perfil ${optimization.selected_profile}; ${optimization.search_trials.length} perfis comparados; ${optimization.promoted ? "modelo aprovado e ativado" : "meta de 70% não validada; configuração ativa preservada"}. ` : "";
  assumptions.textContent = `Fonte: ${source?.source || "CSV carregado pelo usuário"}. ${splitNote}${optimizationNote}${result.execution_assumptions.join(" / ")} / ${learningNote}`;
  document.getElementById("chart-empty").classList.add("hidden");
  document.getElementById("chart-result").classList.remove("hidden");
  document.getElementById("chart-result-count").textContent = `${result.equity.length.toLocaleString("pt-BR")} pontos`;
  const equityMetric = document.getElementById("metric-equity");
  if (equityMetric) equityMetric.textContent = `${metrics.ending_balance.toLocaleString("pt-BR", { style: "currency", currency: state.config.account_currency || "USD" })}`;
  state.backtest = result;
  requestAnimationFrame(() => drawEquity(result.equity));
}

async function refreshMt5Status() {
  const label = document.getElementById("mt5-status");
  const dot = document.getElementById("mt5-status-dot");
  if (!label) return;
  label.textContent = "Verificando terminal MT5…";
  try {
    const response = await fetch("/api/mt5/status", { cache: "no-store" });
    const status = await response.json();
    if (status.connected) {
      label.textContent = `Conectado · ${status.broker} · ${status.server} · conta ${status.trade_mode === "demo" ? "demo" : "conectada"} · somente leitura`;
      dot?.classList.add("connected");
    } else {
      label.textContent = status.message || "MT5 indisponível neste computador.";
      dot?.classList.remove("connected");
    }
  } catch {
    label.textContent = "Não foi possível consultar o terminal MT5.";
    dot?.classList.remove("connected");
  }
}

async function runMt5Backtest() {
  const button = document.getElementById("run-mt5-backtest");
  button.disabled = true; button.textContent = "Capturando dados e validando…";
  try {
    const config = collectConfig();
    config.instrument = document.getElementById("backtest-symbol").value;
    config.timeframe = document.getElementById("backtest-timeframe").value;
    const count = Math.min(100000, Math.max(100, Number(document.getElementById("mt5-bars").value) || 100000));
    const response = await api("/api/mt5/backtest", { config, count, starting_balance: config.starting_balance });
    const result = response.result;
    renderBacktest(result, result.source_candles, result.data_source);
    document.getElementById("mt5-history-note").textContent =
      `${result.data_source.count.toLocaleString("pt-BR")} candles recebidos de ${result.data_source.symbol} · ${new Date(result.data_source.from_utc).toLocaleString("pt-BR")} a ${new Date(result.data_source.to_utc).toLocaleString("pt-BR")} (UTC). Nenhuma ordem foi enviada ao MT5.`;
    toast("Dados reais do MT5 capturados. Validação simulada concluída.");
  } catch (error) {
    toast(error.message);
    await refreshMt5Status();
  } finally {
    button.disabled = false; button.textContent = "Capturar e validar estratégia";
  }
}

async function optimizeMt5Strategy() {
  const button = document.getElementById("optimize-mt5");
  button.disabled = true; button.textContent = "Testando 13 combina\u00e7\u00f5es em janelas futuras...";
  try {
    const config = collectConfig();
    config.instrument = document.getElementById("backtest-symbol").value;
    config.timeframe = document.getElementById("backtest-timeframe").value;
    const count = Math.min(100000, Math.max(20000, Number(document.getElementById("mt5-bars").value) || 100000));
    const response = await api("/api/mt5/optimize", { config, count, starting_balance: config.starting_balance });
    const result = response.result;
    renderBacktest(result, result.source_candles, result.data_source);
    document.getElementById("mt5-history-note").textContent = result.optimization.promoted
      ? `Modelo ${result.optimization.selected_profile} aprovado no período reservado e ativado para análise de sinais.`
      : `Perfil ${result.optimization.selected_profile} avaliado sem atingir os critérios de aprovação. A configuração ativa não foi substituída e nenhum modelo experimental foi ativado.`;
    toast(result.optimization.promoted ? "Modelo validado e ativado para filtrar sinais." : "Busca concluída; nenhum perfil atingiu os critérios para ativação.");
  } catch (error) {
    toast(error.message);
    await refreshMt5Status();
  } finally {
    button.disabled = false; button.textContent = "Testar combina\u00e7\u00f5es e validar";
  }
}

async function runBacktest() {
  if (!state.selectedFile) return;
  const button = document.getElementById("run-backtest");
  button.disabled = true; button.textContent = "Analisando candles…";
  try {
    const text = await state.selectedFile.text();
    const candles = parseCsv(text);
    const config = collectConfig();
    config.instrument = document.getElementById("backtest-symbol").value;
    config.timeframe = document.getElementById("backtest-timeframe").value;
    const response = await api("/api/backtest", { candles, config, starting_balance: config.starting_balance });
    renderBacktest(response.result, candles.length);
    toast("Backtest concluído. Resultados são simulados e dependem dos dados e custos informados.");
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false; button.textContent = "▶ Executar backtest";
  }
}

function exportTrades() {
  if (!state.backtest?.trades?.length) return toast("Não há operações para exportar.");
  const headers = ["entry_time", "exit_time", "side", "entry", "exit", "stop", "target", "units", "pnl", "reason", "score"];
  const rows = state.backtest.trades.map((trade) => headers.map((key) => JSON.stringify(trade[key] ?? "")).join(","));
  const blob = new Blob([[headers.join(","), ...rows].join("\n")], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = "aurelia-trades.csv"; link.click();
  URL.revokeObjectURL(link.href);
}

async function saveTypesafeKey() {
  const input = document.getElementById("typesafe-api-key");
  const apiKey = input.value.trim();
  if (!apiKey) return toast("Informe a chave de API TypeSafe.");
  try {
    const result = await api("/api/typesafe/key", { api_key: apiKey });
    state.typesafeConfigured = true;
    input.value = "";
    document.getElementById("typesafe-status").textContent = "Chave TypeSafe protegida neste computador.";
    toast(result.message);
  } catch (error) { toast(error.message); }
}

async function runJevReview() {
  if (!state.selectedFile) return toast("Carregue um CSV antes de pedir a revisão.");
  const button = document.getElementById("request-jev-review");
  const panel = document.getElementById("jev-review-panel");
  const output = document.getElementById("jev-review-result");
  button.disabled = true; button.textContent = "Enviando contexto...";
  panel.classList.remove("hidden"); output.textContent = "A estratégia local está avaliando o último candle.";
  try {
    const candles = parseCsv(await state.selectedFile.text());
    const config = collectConfig();
    config.instrument = document.getElementById("backtest-symbol").value;
    config.timeframe = document.getElementById("backtest-timeframe").value;
    const response = await api("/api/jev/review", { candles: candles.slice(-1500), config });
    const result = response.result;
    const title = result.action === "approve" ? "Candidato aprovado para simulação" : "Aguardar: nenhuma entrada";
    const details = result.jev_choice
      ? `Parecer experimental Jev: ${result.jev_choice}. Não representa probabilidade calibrada de mercado nem autorização de risco.`
      : `Sinal local: ${result.local_signal}.`;
    output.replaceChildren();
    const heading = document.createElement("strong"); heading.textContent = title;
    const summary = document.createElement("p"); summary.textContent = result.reason;
    const evidence = document.createElement("small"); evidence.textContent = details;
    output.append(heading, summary, evidence);
  } catch (error) {
    output.textContent = error.message;
    toast(error.message);
  } finally {
    button.disabled = false; button.textContent = "Revisar cenário com Jev";
  }
}

async function saveCredentials(event) {
  event.preventDefault();
  const provider = document.querySelector('input[name="broker"]:checked')?.value || "paper";
  if (provider === "paper") return toast("A simulação local não precisa de credenciais.");
  const payload = { provider };
  for (const [key, id] of Object.entries({ api_key: "credential-api-key", api_secret: "credential-api-secret", access_token: "credential-access-token", account_id: "credential-account-id", host: "credential-host", port: "credential-port", client_id: "credential-client-id", login_type: "credential-login-type" })) {
    payload[key] = document.getElementById(id).value;
  }
  try {
    const response = await api("/api/credentials", payload);
    state.credentialsSaved = true;
    document.getElementById("credentials-form").reset();
    syncProviderDetails(provider);
    toast(response.message);
  } catch (error) {
    toast(error.message);
  }
}

async function init() {
  document.getElementById("local-date").textContent = new Intl.DateTimeFormat("pt-BR", { weekday: "long", day: "2-digit", month: "long" }).format(new Date()).toUpperCase();
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    const data = await response.json();
    state.csrf = data.csrf; state.config = data.config; state.credentialsSaved = data.credentials_saved; state.typesafeConfigured = data.typesafe_configured; state.dukascopyConfigured = data.dukascopy_configured;
    document.getElementById("typesafe-status").textContent = state.typesafeConfigured ? "Chave TypeSafe protegida neste computador." : "Nenhuma chave configurada. A chave será criptografada pelo Windows neste computador.";
    setConfigFields(state.config);
    const learning = data.learning_status || {};
    document.getElementById("learning-status").textContent = learning.active
      ? `Filtro adaptativo validado com ${learning.samples} opera\u00e7\u00f5es anteriores; ele pode vetar candidatos, nunca aumentar o risco.`
      : `Filtro adaptativo inativo: ${learning.samples || 0}/${learning.required_samples || 100} opera\u00e7\u00f5es registradas para este par e per\u00edodo. ` + (learning.reason || "Ainda n\u00e3o h\u00e1 evid\u00eancia suficiente.");
    if (state.credentialsSaved) document.getElementById("credentials-saved").textContent = `Dados criptografados salvos · ${state.config.broker}`;
    document.getElementById("fix-saved").textContent = state.dukascopyConfigured ? "Acesso FIX protegido neste computador" : "Parâmetros FIX não configurados";
  } catch (_) {
    toast("Não foi possível carregar as configurações locais.");
  }

  document.querySelectorAll("[data-page]").forEach((element) => element.addEventListener("click", (event) => {
    event.preventDefault(); navigate(element.dataset.page);
  }));
  document.querySelectorAll("[data-goto]").forEach((element) => element.addEventListener("click", () => navigate(element.dataset.goto)));
  document.querySelectorAll(".save-config").forEach((button) => button.addEventListener("click", saveConfig));
  document.querySelectorAll('input[name="broker"]').forEach((input) => input.addEventListener("change", () => {
    document.querySelectorAll(".broker-option").forEach((option) => option.classList.toggle("selected", option.contains(document.querySelector('input[name="broker"]:checked'))));
    syncProviderDetails(input.value);
    saveConfig();
  }));
  document.getElementById("credentials-form").addEventListener("submit", saveCredentials);
  document.getElementById("dukascopy-form").addEventListener("submit", saveDukascopySettings);
  document.getElementById("live-connect").addEventListener("click", toggleLiveFeed);
  document.getElementById("save-typesafe-key").addEventListener("click", saveTypesafeKey);
  document.getElementById("request-jev-review").addEventListener("click", runJevReview);
  document.getElementById("test-connection").addEventListener("click", () => toast("Conector identificado. Testes de autenticação e ordens reais ainda não estão habilitados."));
  document.getElementById("help-btn").addEventListener("click", () => toast("Importe candles históricos e ajuste a estratégia antes de ativar qualquer execução."));
  document.getElementById("chart-expand").addEventListener("click", () => navigate("backtest"));
  document.getElementById("overview-symbol").addEventListener("change", saveConfig);
  document.getElementById("overview-timeframe").addEventListener("change", saveConfig);
  document.getElementById("csv-file").addEventListener("change", (event) => selectFile(event.target.files?.[0]));
  const drop = document.getElementById("drop-zone");
  drop.addEventListener("dragover", (event) => { event.preventDefault(); drop.classList.add("dragging"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("dragging"));
  drop.addEventListener("drop", (event) => { event.preventDefault(); drop.classList.remove("dragging"); selectFile(event.dataTransfer.files?.[0]); });
  document.getElementById("run-backtest").addEventListener("click", runBacktest);
  document.getElementById("run-mt5-backtest").addEventListener("click", runMt5Backtest);
  document.getElementById("optimize-mt5").addEventListener("click", optimizeMt5Strategy);
  document.getElementById("refresh-mt5-status").addEventListener("click", refreshMt5Status);
  document.getElementById("download-trades").addEventListener("click", exportTrades);
  const initialPage = window.location.hash.replace("#", "");
  if (initialPage) navigate(initialPage);
  window.addEventListener("resize", () => { if (state.backtest) drawEquity(state.backtest.equity); });
  await refreshMarket();
  await refreshMt5Status();
  window.setInterval(refreshMarket, 1000);
}

function selectFile(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".csv")) return toast("Selecione um arquivo CSV.");
  state.selectedFile = file;
  if (/5minute|m5/i.test(file.name)) document.getElementById("backtest-timeframe").value = "M5";
  if (/eur[-_]usd/i.test(file.name)) document.getElementById("backtest-symbol").value = "EUR/USD";
  document.getElementById("request-jev-review").disabled = false;
  document.getElementById("file-name").textContent = `${file.name} · ${(file.size / 1024).toFixed(0)} KB`;
  document.getElementById("run-backtest").disabled = false;
}

document.addEventListener("DOMContentLoaded", init);
