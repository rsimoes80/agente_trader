"use strict";
(() => {
  const root = document.getElementById("history-panel");
  if (!root) return;
  const node = (tag, text) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; return n; };
  const heading = node("summary", "Histórico e estatísticas — consultando PostgreSQL…"), content = node("div");
  root.append(heading, content);
  const number = value => Number.isFinite(value) ? value.toFixed(2) : "—";
  const utc = t => t ? new Date(t).toLocaleString("pt-BR", { timeZone: "UTC" }) : "—";
  async function refresh() {
    try {
      const response = await fetch("/api/diagnostics/history", { cache: "no-store" }), data = await response.json();
      if (!response.ok || !data.ok) throw new Error("Histórico indisponível para análise.");
      const baseline = data.baseline;
      heading.textContent = `Histórico antes da análise · ${baseline?.days || 30} dias · ${data.blocker ? "Aguardando histórico válido" : "Disponível no PostgreSQL"}`;
      content.replaceChildren();
      if (!baseline) { content.append(node("p", "Aguardando importação do MT5. Dados ausentes não autorizam uma operação.")); return; }
      content.append(node("p", `${utc(baseline.start)} a ${utc(baseline.as_of)} UTC · fonte ${baseline.source_clock.server} · ${data.blocker || "Cobertura validada"}`));
      const wrap = node("div"), table = node("table"), head = node("tr"), body = node("tbody");
      wrap.className = "history-scroll";
      ["Período", "Candles", "Cobertura", "Amplitude média (pips)", "Spread médio (pips)", "Qualidade"].forEach(t => head.append(node("th", t)));
      for (const [tf, info] of Object.entries(baseline.timeframes)) {
        const tr = node("tr");
        [tf, info.statistics.bars.toLocaleString("pt-BR"), `${(info.coverage * 100).toFixed(1)}%`, number(info.statistics.mean_range_pips), number(info.statistics.mean_spread_pips), info.ready ? "Disponível" : "Insuficiente"].forEach(t => tr.append(node("td", t)));
        body.append(tr);
      }
      const thead = node("thead"); thead.append(head); table.append(thead, body); wrap.append(table); content.append(wrap);
      if (data.research) {
        const research = data.research;
        content.append(node("p", `Pesquisa de hipóteses: continuação e reversão · ${research.results.filter(r => r.phase === "validation").reduce((n, r) => n + r.samples, 0)} avaliações de hipóteses na validação (horizontes correlacionados) · holdout reservado · sem promoção automática.`));
        content.append(node("p", "Os estudos medem direção e movimento bruto, sem custos de negociação. Não demonstram rentabilidade. Estatísticas por sessão e hora UTC ficam preservadas no banco."));
      }
    } catch (error) { heading.textContent = "Histórico antes da análise · indisponível"; content.replaceChildren(node("p", error.message)); }
  }
  refresh(); setInterval(refresh, 60000);
})();
