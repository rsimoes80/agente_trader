"use strict";

const $ = id => document.getElementById(id);
const state = { csrf: "", runs: [], offset: 0, reason: "", selected: null, detail: null, loading: false, live: null, follow: true, chartBars: [] };
const colors = { TREND: "#46d6a0", RANGE: "#69aefa", TRANSITION: "#e5ab62", UNKNOWN: "#82919e" };
const words = { REGIME_UNKNOWN: "O classificador ainda não tem contexto suficiente para escolher um regime.", REGIME_MISMATCH: "A estratégia de tendência não é elegível neste regime. Nenhum setup foi procurado.", TREND_TRANSITION_WAIT: "A estrutura entre timeframes apresenta transição ou enfraquecimento.", TREND_CONTEXT_INSUFFICIENT: "Faltam swings confirmados nos horizontes exigidos.", SESSION_NOT_AUTHORIZED: "A observação está fora das sessões permitidas pela estratégia.", EVIDENCE_INVALIDATED: "Há evidência invalidante, como dados atrasados ou spread inadequado.", OBSERVATION_ONLY_HYPOTHESIS_REQUIRED: "Contexto observado. Faltam hipótese operacional, confirmação, gatilho e risco para considerar uma operação.", TREND_CONFIRMATION_PENDING: "A tendência candidata ainda não cumpriu a confirmação configurada.", EVIDENCE_CONFLICTED: "Há fatos direcionais contrários. O agente preservou o conflito e esperou." };
const number = value => Number(value).toLocaleString("pt-BR");
const percent = value => Number.isFinite(value) ? `${(100 * value).toFixed(1)}%` : "—";
const utc = value => value ? new Date(value).toLocaleString("pt-BR", { timeZone: "UTC", hour12: false }) : "—";
function node(tag, text, className) { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; }
function error(message) { $("error").textContent = message; $("error").hidden = !message; }
async function api(path, payload) {
  const response = await fetch(`/api/diagnostics/${path}`, { cache: "no-store", ...(payload ? { method: "POST", headers: { "Content-Type": "application/json", "X-Diagnostics-CSRF": state.csrf }, body: JSON.stringify(payload) } : {}) });
  let data;
  try { data=await response.json(); } catch { throw new Error("O serviço de diagnóstico está indisponível. Tente atualizar em alguns segundos."); }
  if (!response.ok || !data.ok) throw new Error(data.error || "Não foi possível consultar o diagnóstico.");
  return data;
}
function filters() {
  const params = new URLSearchParams({ run_id: $("run").value, offset: state.offset });
  for (const key of ["regime", "session", "timeframe"]) if ($(key).value) params.set(key, $(key).value);
  for (const key of ["from", "to"]) if ($(key).value) params.set(key, new Date($(key).value).toISOString());
  if (state.reason) params.set("reason", state.reason);
  return params;
}
function badge(regime, suffix = "") { return node("span", regime + suffix, `badge ${regime}`); }
function observer(info) {
  state.live = info.run_id;
  $("observer-dot").className = `dot ${info.status}`;
  $("observer-title").textContent = ({ observing: "Observador ativo · MT5", unavailable: "Fonte ou banco indisponível", stale: "Dados do MT5 atrasados", starting: "Iniciando observador",warming:"Preparando histórico fechado",passive:"Observador já ativo em outra instância" })[info.status] || info.status;
  $("observer-detail").textContent = info.status==='unavailable' ? info.message : info.last_candle ? `Último candle: ${utc(info.last_candle)} UTC · consultado ${utc(info.checked_at)} UTC` : info.message || "Aguardando candles fechados";
  $("open-live").hidden = !info.run_id;
}
function populateRuns(runs) {
  const previous = $("run").value;
  state.runs = runs;
  for (const id of ["run", "research-run"]) {
    const select = $(id), old = select.value; select.replaceChildren();
    const eligible = runs.filter(run => id === "run" || (run.partition === "development" && run.utc_normalized));
    for (const run of eligible) {
      const phase = { development: "Desenvolvimento", validation: "Validação", live: "Ao vivo", unassigned: "Sem partição" }[run.partition] || run.partition;
      const label = `${phase} · ${run.timeframe} · ${utc(run.created_at)} · ${run.run_id.slice(0, 8)}${run.utc_normalized ? " · UTC" : " · horário legado"}`;
      const option = node("option", label); option.value = run.run_id; select.append(option);
    }
    if (!eligible.length) { const option = node("option", "Nenhuma execução disponível"); option.value = ""; select.append(option); }
    if (eligible.some(run => run.run_id === old)) select.value = old;
    else if (id === "run") select.value = (eligible.find(run => run.partition === "development") || eligible[0])?.run_id || "";
  }
  if (previous && previous !== $("run").value) { state.selected = null; state.detail = null; }
  $("compare-button").disabled = !$("research-run").value;
}
function bar(container, label, count, total, color, click) {
  const row = node("div", undefined, "bar-row");
  const name = node(click ? "button" : "span", label); if (click) { name.type = "button"; name.onclick = click; }
  const track = node("div", undefined, "bar-track"), fill = node("i");
  fill.style.width = `${total ? 100 * count / total : 0}%`; fill.style.background = color; track.append(fill);
  row.append(name, track, node("strong", number(count))); container.append(row);
}
function audit(data) {
  const counts = {}, reasons = {};
  let blocked = 0;
  for (const group of data.groups) { counts[group.regime] = (counts[group.regime] || 0) + group.count; reasons[group.reason_code] = (reasons[group.reason_code] || 0) + group.count; if (group.stage === "regime") blocked += group.count; }
  $("total").textContent = number(data.total); $("no-trade").textContent = number(data.total - data.signals);
  $("unknown").textContent = percent(data.total ? (counts.UNKNOWN || 0) / data.total : NaN); $("regime-blocks").textContent = number(blocked);
  const periods = [...new Set(data.groups.map(row => row.regime_timeframe).filter(Boolean))];
  $("timeframe-note").textContent = `Regime no contexto ${periods.join(" / ") || "—"}`;
  $("regime-bars").replaceChildren(); $("reason-bars").replaceChildren();
  for (const name of ["TREND", "RANGE", "TRANSITION", "UNKNOWN"]) bar($("regime-bars"), name, counts[name] || 0, data.total, colors[name]);
  for (const [reason, count] of Object.entries(reasons).sort((a, b) => b[1] - a[1]).slice(0, 6)) bar($("reason-bars"), reason, count, data.total, "#829fb1", () => { state.reason = reason; state.offset = 0; state.selected = null; load(); });
  if (!data.total) $("reason-bars").append(node("p", "Nenhuma observação corresponde aos filtros.", "hint"));
  $("clear-reason").hidden = !state.reason;
  $("audit-matrix").replaceChildren();
  for(const group of data.groups){const row=node('tr');for(const value of [group.regime,`${group.timeframe} / ${group.regime_timeframe}`,group.session,group.reason_code,number(group.count)])row.append(node('td',value));$("audit-matrix").append(row);}
  const human=data.human_review;
  $("review-summary").textContent=human?.judgments?`${human.judgments} pareceres em ${human.unique_snapshots} snapshots; ${human.agreements} concordâncias com o modelo. Última revisão por pessoa/snapshot; concordância informada não é acurácia independente.`:'Ainda não há revisões humanas nesta amostra.';
}
function samples(data) {
  $("samples").replaceChildren();
  for (const row of data.rows) {
    const tr = node("tr"); tr.tabIndex = 0; tr.dataset.id = row.decision_id;
    if (row.decision_id === state.selected) tr.className = "selected";
    const time = node("td"); time.append(node("span", utc(row.created_at_utc)), node("div", `${row.timeframe} · ${row.session}`, "muted"));
    const regime = node("td"); regime.append(badge(row.regime), node("div", row.regime_timeframe || "—", "muted"));
    tr.append(time, regime, node("td", row.reason_code, "reason-text"));
    const choose = () => { state.follow = false; updateFollow(); select(row.decision_id); };
    tr.onclick = choose; tr.onkeydown = event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(); } };
    $("samples").append(tr);
  }
  $("page-info").textContent = data.rows.length ? `${data.offset + 1}–${data.offset + data.rows.length}` : "Sem amostras";
  $("newer").disabled = !data.offset; $("older").disabled = data.rows.length < data.page_size;
  if (data.rows.length && (!state.selected || state.follow)) {
    const id = data.rows[0].decision_id;
    if (state.selected !== id || !state.detail) select(id);
  } else if (!data.rows.length) { state.selected = null; state.detail = null; $("detail").hidden = true; $("empty-detail").hidden = false; }
}
async function load() {
  if (state.loading || !$("run").value) return;
  state.loading = true;
  try {
    const params = filters();
    const [summary, rows] = await Promise.all([api(`audit?${params}`), api(`samples?${params}`)]);
    audit(summary); samples(rows);
    const run = state.runs.find(r => r.run_id === $("run").value);
    $("sample-note").textContent = `${run?.partition === "live" ? "Observação ao vivo somente leitura." : "Replay histórico; não representa o estado atual do MT5."} ${run?.utc_normalized ? "Horários normalizados em UTC." : "Horário legado não validado: não use estes resultados para calibrar sessões ou parâmetros."} Contagens de uma única execução.`;
    $("last-refresh").textContent = `Atualizado ${new Date().toLocaleTimeString("pt-BR")}`;
    error("");
  } catch (e) { error(e.message); } finally { state.loading = false; }
}
function reviews(rows) {
  $("review-history").replaceChildren();
  for (const row of rows) $("review-history").append(node("div", `${row.reviewer} · ${row.label} · ${utc(row.reviewed_at)} UTC${row.note ? " — " + row.note : ""}`));
}
async function select(id) {
  state.selected = id;
  $("detail").hidden=true;$("empty-detail").hidden=false;$("empty-detail").textContent="Carregando a observação…";
  for (const row of $("samples").children) row.classList.toggle("selected", row.dataset.id === id);
  try {
    const data = await api(`detail?decision_id=${encodeURIComponent(id)}`);
    if (state.selected !== id) return;
    state.detail = data; const s = data.snapshot, d = data.decision;
    $("detail").hidden = false; $("empty-detail").hidden = true;
    $("selection-time").textContent = `${utc(d.created_at_utc)} UTC`;
    $("regime-badge").replaceWith(Object.assign(badge(s.regime, ` / ${s.regime_subtype}`), { id: "regime-badge" }));
    $("location-label").textContent = `Localização: ${s.market_location.relative_location}`;
    $("model-label").textContent = `${s.regime_model_version} · ${s.regime_state.timeframe}`;
    $("blocker").textContent = d.reason_code;
    $("blocker-description").textContent = words[d.reason_code] || `O agente registrou este motivo na etapa de ${stage(d.reason_code)}. A ausência de entrada é uma decisão válida.`;
    $("quality").textContent = `${s.regime_state.classification_status} · ${s.regime_stability} · evidências ${s.evidence_status}`;
    $("missing").replaceChildren();
    for (const item of [...(s.regime_state.missing_data || []), ...(s.missing_evidence || [])]) $("missing").append(node("span", item));
    $("features").textContent = JSON.stringify({ timeframe: s.regime_state.timeframe, features: s.regime_state.features, parameters: s.regime_state.parameters, config_hash: s.regime_config_hash }, null, 2);
    $("evidence-list").replaceChildren();
    for (const item of s.evidence_set.items) {
      const li = node("li", item.observation, item.status === "invalidating" ? "invalidating" : item.direction);
      li.append(node("small", `${item.source_component} · ${item.timeframe} · ${item.regime} · ${item.status} · ${item.dependency_group}`)); $("evidence-list").append(li);
    }
    $("review-status").textContent = ""; $("review-note").value = ""; $("human-label").value = "UNKNOWN";
    reviews(data.reviews); draw();
  } catch (e) { error(e.message); }
}
function stage(reason) { if (reason.startsWith("EVIDENCE_")) return "evidências"; if (reason.startsWith("TREND_")) return "contexto"; if (reason.startsWith("RISK_")) return "risco"; return "observação"; }
function period(tf) { const match = /^([MHD])(\d+)$/.exec(tf); return match ? Number(match[2]) * ({ M: 60, H: 3600, D: 86400 })[match[1]] : 300; }
function chartData() {
  const data = state.detail; if (!data) return [];
  const source = data.candles;
  if ($("chart-timeframe").value !== "context" || data.snapshot.regime_state.timeframe === data.decision.timeframe) return source;
  const target = period(data.snapshot.regime_state.timeframe), base = period(data.decision.timeframe), buckets = new Map();
  for (const row of source) { const key = Math.floor(Date.parse(row.timestamp) / (target * 1000)) * target * 1000; if (!buckets.has(key)) buckets.set(key, []); buckets.get(key).push(row); }
  const result = [];
  for (const [stamp, rows] of buckets) {
    const complete = rows.length === target / base && rows.every((row, i) => Date.parse(row.timestamp) === stamp + i * base * 1000);
    if (!complete || stamp + target * 1000 > Date.parse(data.decision.created_at_utc)) continue;
    result.push({ timestamp: new Date(stamp).toISOString(), open: rows[0].open, high: Math.max(...rows.map(r => r.high)), low: Math.min(...rows.map(r => r.low)), close: rows.at(-1).close });
  }
  return result;
}
function draw() {
  if (!state.detail || $("detail").hidden) return;
  const canvas = $("regime-chart"), ctx = canvas.getContext("2d"), box = canvas.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(box.width * ratio); canvas.height = Math.round(box.height * ratio); ctx.scale(ratio, ratio);
  const width = box.width, height = box.height, rows = chartData().slice(-Number($("chart-count").value)); state.chartBars = rows;
  ctx.fillStyle = "#080e13"; ctx.fillRect(0, 0, width, height); ctx.font = "10px system-ui";
  const data = state.detail, s = data.snapshot, timeframe = $("chart-timeframe").value === "context" ? s.regime_state.timeframe : data.decision.timeframe;
  $("chart-caption").textContent = `EUR/USD · ${timeframe} · ${rows.length} candles fechados`;
  $("chart-note").textContent = `Sem candles futuros. Fundos mostram rótulos conhecidos no fechamento; limites da faixa aparecem a partir de sua detecção. Contexto do regime: ${s.regime_state.timeframe}.`;
  if (!rows.length) { ctx.fillStyle = "#91a7b5"; ctx.fillText("Candles desta amostra não estão disponíveis no banco.", 18, height / 2); return; }
  const left = 12, right = width - 65, top = 18, bottom = height - 30, step = (right - left) / rows.length;
  let low = Math.min(...rows.map(r => r.low)), high = Math.max(...rows.map(r => r.high));
  const range = s.regime_state.range_state;
  if (range?.upper_boundary) { low = Math.min(low, range.lower_boundary); high = Math.max(high, range.upper_boundary); }
  const pad = (high - low || 0.0001) * .12; low -= pad; high += pad;
  const y = value => bottom - (value - low) * (bottom - top) / (high - low);
  for (let i = 0; i <= 4; i++) { const price = low + (high - low) * i / 4; ctx.strokeStyle = "#1c2a34"; ctx.beginPath(); ctx.moveTo(left, y(price)); ctx.lineTo(right, y(price)); ctx.stroke(); ctx.fillStyle = "#839aaa"; ctx.fillText(price.toFixed(5), right + 8, y(price) + 3); }
  const timeline = data.timeline || [];
  rows.forEach((bar, i) => {
    const knownAt = Date.parse(bar.timestamp) + period(timeframe) * 1000;
    const known = timeline.filter(t => Date.parse(t.timestamp) + period(data.decision.timeframe) * 1000 <= knownAt).at(-1);
    if (known) { ctx.fillStyle = (colors[known.regime] || colors.UNKNOWN) + "12"; ctx.fillRect(left + i * step, top, step, bottom - top); }
    const x = left + (i + .5) * step; ctx.strokeStyle = bar.close >= bar.open ? "#42d99a" : "#e76f88"; ctx.fillStyle = ctx.strokeStyle;
    ctx.beginPath(); ctx.moveTo(x, y(bar.high)); ctx.lineTo(x, y(bar.low)); ctx.stroke(); const body = Math.max(1, Math.abs(y(bar.open) - y(bar.close)));
    ctx.fillRect(x - Math.max(1, step * .3), Math.min(y(bar.open), y(bar.close)), Math.max(2, step * .6), body);
    if (i % Math.max(1, Math.floor(rows.length / 5)) === 0) { ctx.fillStyle = "#839aaa"; ctx.fillText(new Date(bar.timestamp).toLocaleTimeString("pt-BR", { timeZone: "UTC", hour: "2-digit", minute: "2-digit" }), Math.min(x, right - 35), height - 10); }
  });
  if (range?.upper_boundary) {
    const start = Math.max(0, rows.findIndex(bar => Date.parse(bar.timestamp) + period(timeframe) * 1000 >= Date.parse(range.detected_at)));
    ctx.setLineDash([4, 4]); ctx.strokeStyle = "#79a9e5";
    for (const price of [range.upper_boundary, range.lower_boundary]) { ctx.beginPath(); ctx.moveTo(left + start * step, y(price)); ctx.lineTo(right, y(price)); ctx.stroke(); }
    ctx.setLineDash([]);
  }
}
function updateFollow() { const button = $("follow"); if (button) { button.textContent = state.follow ? "● Seguindo últimas" : "Seguir últimas"; button.setAttribute("aria-pressed", String(state.follow)); } }
function jobResults(jobs) {
  $("jobs").replaceChildren();
  for (const job of jobs) {
    const box = node("article", undefined, "job"); box.append(node("h3", `${job.status === "completed" ? "Concluído" : job.status === "failed" ? "Falhou" : "Processando"} · ${utc(job.created_at)} UTC · desenvolvimento`));
    if (job.result) {
      const table = node("table"), head = node("tr");
      for (const label of ["Variante", "Janela", "UNKNOWN", "Mudanças / 100", "Duração mediana", "Concordância baseline"]) head.append(node("th", label));
      const thead = node("thead"); thead.append(head); table.append(thead); const body = node("tbody");
      for (const result of job.result.variants) { const tr = node("tr"); for (const value of [result.variant, result.config.window, percent(result.unknown_fraction), result.changes_per_100_context_updates?.toFixed(1) ?? "—", `${result.median_dwell_context_bars ?? "—"} barras ${job.result.regime_timeframe}`, percent(result.agreement_with_baseline)]) tr.append(node("td", String(value))); body.append(tr); }
      table.append(body); const wrap = node("div", undefined, "table-wrap"); wrap.append(table); box.append(wrap);
      box.append(node("p", "Somente sensibilidade de classificação. Validação e holdout não acessados; nenhuma promoção ou avaliação de lucro.", "hint"));
    }
    if (job.status === "failed") box.append(node("p", `Falha ${job.error_type}. A configuração em uso foi preservada.`, "hint"));
    $("jobs").append(box);
  }
}
async function refresh() {
  try { const data = await api("bootstrap"); state.csrf = data.csrf; populateRuns(data.runs); observer(data.observer); await load(); const jobs = await api("jobs"); jobResults(jobs.jobs); } catch (e) { error(e.message); }
}
$("filters").onsubmit = event => { event.preventDefault(); state.offset = 0; state.selected = null; state.follow = true; updateFollow(); load(); };
$("run").onchange = () => { state.offset = 0; state.reason = ""; state.selected = null; state.detail = null; state.follow = true; updateFollow(); load(); };
$("reset").onclick = () => { for (const key of ["regime", "session", "timeframe", "from", "to"]) $(key).value = ""; state.reason = ""; state.offset = 0; state.selected = null; load(); };
$("clear-reason").onclick = () => { state.reason = ""; state.offset = 0; load(); };
$("older").onclick = () => { state.offset += 60; state.selected = null; state.follow = false; updateFollow(); load(); };
$("newer").onclick = () => { state.offset = Math.max(0, state.offset - 60); state.selected = null; load(); };
$("open-live").onclick = () => { if (state.runs.some(r => r.run_id === state.live)) { $("run").value = state.live; $("run").onchange(); } else refresh(); };
$("refresh").onclick = refresh;
$("chart-timeframe").onchange = draw; $("chart-count").onchange = draw;
$("review-form").oninput = () => { state.follow = false; updateFollow(); };
$("review-form").onsubmit = async event => {
  event.preventDefault(); if (!state.selected) return;
  const decisionId=state.selected;
  const button = event.submitter; button.disabled = true;
  try { await api("reviews", { decision_id: decisionId, reviewer: $("reviewer").value, label: $("human-label").value, note: $("review-note").value }); const data = await api(`detail?decision_id=${encodeURIComponent(decisionId)}`); if(state.selected===decisionId){$("review-status").textContent = "Revisão registrada. Modelo preservado.";reviews(data.reviews);} } catch (e) { error(e.message); } finally { button.disabled = false; }
};
$("experiment-form").onsubmit = async event => {
  event.preventDefault(); const windows = $("windows").value.split(",").map(x => Number(x.trim()));
  if (!windows.length || windows.length > 3 || windows.some(x => !Number.isInteger(x) || x < 6 || x > 80)) { error("Informe até três janelas inteiras entre 6 e 80, separadas por vírgula."); return; }
  $("compare-button").disabled = true;
  try { await api("experiments", { run_id: $("research-run").value, variations: windows.map(window => ({ window })) }); const jobs = await api("jobs"); jobResults(jobs.jobs); error(""); } catch (e) { error(e.message); } finally { $("compare-button").disabled = false; }
};
$("regime-chart").onmousemove = event => {
  const box = event.currentTarget.getBoundingClientRect(), x = event.clientX - box.left, index = Math.floor((x - 12) / (box.width - 77) * state.chartBars.length), row = state.chartBars[index];
  $("chart-tooltip").hidden = !row; if (row) $("chart-tooltip").textContent = `${utc(row.timestamp)} UTC\nO ${row.open.toFixed(5)}  H ${row.high.toFixed(5)}\nL ${row.low.toFixed(5)}  C ${row.close.toFixed(5)}`;
};
$("regime-chart").onmouseleave = () => { $("chart-tooltip").hidden = true; };
const follow = node("button", "● Seguindo últimas", "quiet"); follow.id = "follow"; follow.type = "button"; follow.setAttribute("aria-pressed", "true"); follow.onclick = () => { state.follow = true; state.offset = 0; state.selected = null; updateFollow(); load(); }; $("page-info").before(follow);
new ResizeObserver(draw).observe($("regime-chart"));
refresh(); setInterval(refresh, 20000);
