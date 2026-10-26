"use strict";
(() => {
  const root = document.getElementById("timestral-panel");
  if (!root) return;
  const symbol=new URLSearchParams(location.search).get('symbol')||'EURUSD';
  if(symbol!=='EURUSD'){window.aureliaTimestral=[];root.textContent='As previsões operacionais deste ativo serão exibidas após a preparação de seu ciclo de análise. Previsões de EURUSD não são reutilizadas neste gráfico.';return;}
  const el = (tag, text) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; return n; };
  const price = n => Number.isFinite(n) ? n.toFixed(5) : "—";
  const pct = n => Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : "—";
  const utc = t => new Date(t).toLocaleString("pt-BR", { timeZone: "UTC" });
  const header = el("div"), title = el("strong", "Previsão IA — Timestral"), scope = el("select");
  for (const [value, label] of [["live", "Mercado ao vivo"], ["replay", "Replay de pesquisa"]]) { const o = el("option", label); o.value = value; scope.append(o); }
  scope.setAttribute("aria-label", "Origem das previsões Timestral"); header.append(title, scope);
  const status = el("p", "Consultando modelo…"), content = el("div"), metrics = el("div");
  root.append(header, status, content, metrics, el("p", "Intervalos nominais de 80%; não representam probabilidade de lucro. Evidência em observação, sem autoridade para operar."));
  const table = (headings, rows) => {
    const wrap = el("div"), t = el("table"), h = el("thead"), b = el("tbody"), tr = el("tr");
    headings.forEach(x => tr.append(el("th", x))); h.append(tr);
    rows.forEach(values => { const r = el("tr"); values.forEach(x => r.append(el("td", x))); b.append(r); });
    t.append(h, b); wrap.className = "timestral-scroll"; wrap.append(t); return wrap;
  };
  async function refresh() {
    try {
      const response = await fetch(`/api/diagnostics/timestral?scope=${scope.value}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error("Serviço de previsões indisponível.");
      content.replaceChildren(); metrics.replaceChildren();
      const state = data.status || {}, labels = { observing: "Em observação", disabled: "Desabilitado", offline: "Coletor offline", insufficient_data: "Dados insuficientes", unavailable: "Indisponível" };
      const ps = data.predictions || [];
      status.textContent = `${labels[state.status] || "Aguardando dados"} · ${ps[0]?.model || state.model || "mistralai/Timestral-209M"}${state.updated_at ? ` · ${utc(state.updated_at)} UTC` : ""}`;
      if (!ps.length) content.append(el("p", "Dados insuficientes"));
      else {
        content.append(el("p", `Referência: ${utc(ps[0].reference_time)} UTC (abertura do último candle fechado) · versão ${ps[0].revision.slice(0, 12)} · ${ps[0].device} · latência ${ps[0].latency_ms.toFixed(0)} ms`));
        if (Date.now() - new Date(ps[0].as_of).getTime() > 360000 && scope.value === "live") content.append(el("p", "Previsão histórica: aguardando atualização. Não usar como leitura atual."));
        content.append(table(["Horizonte", "Direção", "Mediana", "Q10 — Q90", "Amplitude", "Retorno mediano"], ps.map(p => [`${p.horizon * 5} min`, ({ UP: "Alta", DOWN: "Baixa", FLAT: "Neutra" })[p.direction], price(p.median), `${price(p.quantiles["0.1"])} — ${price(p.quantiles["0.9"])}`, `${(p.uncertainty / .0001).toFixed(1)} pips`, `${(p.expected_return * 100).toFixed(4)}%`])));
      }
      if (!data.metrics?.length) metrics.append(el("p", "Ainda não há previsões avaliadas para este modelo e origem."));
      else metrics.append(table(["Horizonte / regime", "Avaliadas", "Acerto direcional", "MAE (pips)", "Baseline constante", "Baseline drift", "Cobertura Q10–Q90"], data.metrics.map(m => [`${m.horizon * 5} min / ${m.regime}`, m.evaluated, pct(m.directional_accuracy), (m.mae / .0001).toFixed(2), (m.baseline_mae / .0001).toFixed(2), (m.drift_mae / .0001).toFixed(2), pct(m.interval_coverage)])));
      if (scope.value === "live") { window.aureliaTimestral = ps; window.dispatchEvent(new Event("timestral-update")); }
    } catch (error) { status.textContent = error.message; window.aureliaTimestral = []; window.dispatchEvent(new Event("timestral-update")); }
  }
  scope.onchange = refresh; refresh(); setInterval(refresh, 20000);
})();
