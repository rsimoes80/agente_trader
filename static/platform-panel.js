"use strict";
(() => {
  const root = document.getElementById("platform-panel");
  if (!root) return;
  const el = (tag, text) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; return n; };
  const labels = { STOPPED: "Sem sessão manual", CHECKING_PREREQUISITES: "Verificando condições", RUNNING: "Sessão em observação", PAUSED: "Sessão pausada", PAUSED_BY_DATA: "Pausada por dados ou serviço", RECOVERY_REQUIRED: "Retomada exige revisão", ERROR: "Condições de início não atendidas", EMERGENCY_STOP: "Emergência da sessão acionada" };
  const title = el("summary", "Sessão de observação e prontidão de aprendizado"), box = el("div"); root.append(title, box);
  box.append(el("p", "A coleta automática permanece independente. Estes controles delimitam uma sessão auditável de observação; não iniciam operações na corretora."));
  const status = el("p", "Consultando estado…"), checks = el("p"), learning = el("p"), message = el("p"); message.setAttribute("role", "status");
  const form = el("div"), actor = el("input"), reason = el("input"), token = el("input");
  for (const [input, name, type, placeholder] of [[actor, "Operador", "text", "Seu nome"], [reason, "Justificativa", "text", "Motivo da ação"], [token, "Token de operador", "password", "Token do arquivo local de operador"]]) {
    const label = el("label", name); input.type = type; input.placeholder = placeholder; input.autocomplete = "off"; input.maxLength = type === "password" ? 256 : name === "Operador" ? 80 : 500; label.append(input); form.append(label);
  }
  const buttons = el("div"), actions = {}, states = {};
  for (const [action, label, allowed] of [["START", "Iniciar observação", ["STOPPED", "ERROR"]], ["PAUSE", "Pausar sessão", ["RUNNING"]], ["RESUME", "Retomar sessão", ["PAUSED", "PAUSED_BY_DATA", "RECOVERY_REQUIRED"]], ["STOP", "Encerrar sessão", ["RUNNING", "PAUSED", "PAUSED_BY_DATA", "RECOVERY_REQUIRED", "ERROR"]], ["EMERGENCY_STOP", "Emergência da sessão", ["RUNNING", "PAUSED", "PAUSED_BY_DATA", "RECOVERY_REQUIRED"]], ["RESET", "Rearmar sessão", ["EMERGENCY_STOP"]]]) {
    const button = el("button", label); button.type = "button"; button.dataset.action = action; button.onclick = () => command(action); buttons.append(button); actions[action] = button; states[action] = allowed;
  }
  box.append(status, checks, learning, form, buttons, message);
  let busy = false, latest = null, pending = null;
  const enabled = () => { for (const [action, button] of Object.entries(actions)) button.disabled = busy || !latest?.operator_configured || !states[action].includes(latest?.session.state); };
  async function refresh() {
    try {
      const response = await fetch("/api/diagnostics/platform", { cache: "no-store" }), data = await response.json();
      if (!response.ok || !data.ok) throw new Error("Controle de sessão indisponível.");
      latest = data; const state = data.session;
      title.textContent = `Sessão de observação · ${labels[state.state] || state.state}`;
      status.textContent = `${labels[state.state] || state.state}${state.session_id ? ` · ${state.session_id.slice(0, 8)}` : ""} · ordens desativadas`;
      checks.textContent = `Pré-condições: ${data.preflight.ready ? "disponíveis para observar" : data.preflight.checks.filter(c => !c.passed).map(c => c.reason).join(" · ")}${data.operator_configured ? "" : " · credencial de operador não configurada"}`;
      const audit = data.learning;
      learning.textContent = audit ? `Aprendizado local: ${audit.eligible_samples} amostras compatíveis, ${audit.closed_events_inspected} resultados simulados inspecionados, ${audit.no_trade_observations} decisões de espera. Treino não iniciado: faltam amostra suficiente e contrato aprovado de features. Promoção automática desativada.` : "Auditoria de aprendizado aguardando execução local.";
      enabled();
    } catch (error) { status.textContent = error.message; latest = null; enabled(); }
  }
  async function command(action) {
    if (busy) return;
    if (!actor.value.trim() || !reason.value.trim() || !token.value.trim()) { message.textContent = "Preencha operador, justificativa e token."; return; }
    busy = true; enabled();
    const payload = { action, mode: "observe_only", actor: actor.value.trim(), reason: reason.value.trim() }, signature = JSON.stringify(payload);
    if (!pending || pending.signature !== signature) pending = { signature, key: Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, "0")).join("") };
    try {
      const bootstrap = await (await fetch("/api/diagnostics/bootstrap", { cache: "no-store" })).json();
      const response = await fetch("/api/diagnostics/platform/command", { method: "POST", headers: { "Content-Type": "application/json", "X-Diagnostics-CSRF": bootstrap.csrf, "X-Operator-Token": token.value.trim(), "Idempotency-Key": pending.key }, body: JSON.stringify(payload) });
      const result = await response.json(); if (!response.ok || !result.ok) throw new Error(result.error || "Comando recusado.");
      pending = null; message.textContent = "Comando registrado. Estado confirmado pelo servidor.";
    } catch (error) { message.textContent = error.message; }
    finally { busy = false; await refresh(); }
  }
  refresh(); setInterval(refresh, 20000);
})();
