"use strict";

const canvas = document.getElementById("chart");
const ctx = canvas.getContext("2d");
const state = { timeframe: "M5", candles: [], quote: null, digits: 5, visible: 110, ema: true, timer: null, loading: false, crosshair: null };
const fmt = (value) => Number.isFinite(value) ? value.toFixed(state.digits) : "—";

async function loadChart() {
  if (state.loading) return;
  state.loading = true;
  try {
    const response = await fetch(`/api/mt5/chart?timeframe=${encodeURIComponent(state.timeframe)}&count=600`, { cache: "no-store" });
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error("Resposta inválida do servidor de cotações.");
    }
    if (!response.ok || !data.ok) throw new Error(data.error || "Não foi possível carregar o histórico do MT5.");
    state.candles = data.candles || [];
    state.quote = data.quote;
    state.digits = data.digits || 5;
    document.getElementById("symbol-name").textContent = data.symbol;
    document.getElementById("bid").textContent = fmt(state.quote?.bid);
    document.getElementById("ask").textContent = fmt(state.quote?.ask);
    document.getElementById("spread").textContent = state.quote ? `${((state.quote.ask - state.quote.bid) / data.pip_size).toFixed(1)} pips` : "—";
    document.getElementById("last-close").textContent = fmt(state.candles.at(-1)?.close);
    document.getElementById("market-meta").textContent = `EUR/USD · ${state.timeframe} · ${state.candles.length} candles · UTC · ${data.broker || "MT5"}`;
    document.getElementById("updated-at").textContent = `Atualizado ${new Date().toLocaleTimeString("pt-BR")} · próximo em 3 s`;
    document.getElementById("connection-label").textContent = "MT5 conectado";
    document.querySelector(".connection").classList.add("connected");
    document.querySelector(".connection").classList.remove("disconnected");
    document.getElementById("chart-error").classList.remove("visible");
    draw();
  } catch (error) {
    document.getElementById("connection-label").textContent = "Sem conexão";
    document.querySelector(".connection").classList.remove("connected");
    document.querySelector(".connection").classList.add("disconnected");
    document.getElementById("error-message").textContent = error.message;
    document.getElementById("chart-error").classList.add("visible");
  } finally {
    state.loading = false;
  }
}

function emaValues(candles, period = 21) {
  const alpha = 2 / (period + 1);
  const values = [];
  candles.forEach((candle, i) => values.push(i ? candle.close * alpha + values[i - 1] * (1 - alpha) : candle.close));
  return values;
}

function draw() {
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.floor(rect.width * scale);
  canvas.height = Math.floor(rect.height * scale);
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  const w = rect.width, h = rect.height;
  ctx.fillStyle = "#080b0e";
  ctx.fillRect(0, 0, w, h);
  if (!state.candles.length) return;

  const right = 66, top = 14, bottom = 33, left = 10;
  const plotW = w - left - right, plotH = h - top - bottom;
  const visible = state.candles.slice(-state.visible);
  const forecast = state.timeframe === "M5" ? (window.aureliaTimestral || []).filter(p =>
    Date.now() - new Date(p.as_of).getTime() < 360000 &&
    visible.some(c => c.timestamp === p.reference_time)) : [];
  const extra = forecast.length ? 12 : 0;
  const ema = emaValues(state.candles).slice(-visible.length);
  const rawMin = Math.min(...visible.map(c => c.low), ...forecast.map(p => p.quantiles["0.1"]));
  const rawMax = Math.max(...visible.map(c => c.high), ...forecast.map(p => p.quantiles["0.9"]));
  const pad = (rawMax - rawMin) * .08 || .0001;
  const min = rawMin - pad, max = rawMax + pad;
  const y = price => top + (max - price) / (max - min) * plotH;
  const candleW = Math.max(2, Math.min(10, plotW / (visible.length + extra) * .64));

  ctx.lineWidth = 1;
  ctx.font = "10px 'DM Mono', monospace";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 8; i++) {
    const gy = top + plotH * i / 8;
    const price = max - (max - min) * i / 8;
    ctx.strokeStyle = "#29343d";
    ctx.setLineDash([2, 4]);
    ctx.beginPath(); ctx.moveTo(left, gy); ctx.lineTo(w - right, gy); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#a0abb5";
    ctx.textAlign = "left";
    ctx.fillText(price.toFixed(state.digits), w - right + 8, gy);
  }
  for (let i = 0; i <= 10; i++) {
    const gx = left + plotW * i / 10;
    ctx.strokeStyle = "#202a32";
    ctx.setLineDash([2, 4]);
    ctx.beginPath(); ctx.moveTo(gx, top); ctx.lineTo(gx, h - bottom); ctx.stroke();
    ctx.setLineDash([]);
    const gridIndex = Math.floor(i / 10 * (visible.length + extra));
    const candle = visible[gridIndex] || (extra ? { timestamp: new Date(new Date(visible.at(-1).timestamp).getTime() + (gridIndex - visible.length + 1) * 300000).toISOString() } : visible.at(-1));
    if (candle) {
      const stamp = new Date(candle.timestamp);
      const label = state.timeframe.startsWith("D") || state.timeframe.startsWith("W") || state.timeframe === "MN"
        ? stamp.toLocaleDateString("pt-BR", { day: "2-digit", month: "short", timeZone: "UTC" })
        : stamp.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
      ctx.fillStyle = "#89949e"; ctx.textAlign = "center";
      ctx.fillText(label, gx, h - 14);
    }
  }

  const step = plotW / (visible.length + extra);
  visible.forEach((c, i) => {
    const x = left + i * step + step / 2;
    const up = c.close >= c.open;
    const color = up ? "#16e875" : "#ff5267";
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, y(c.high)); ctx.lineTo(x, y(c.low)); ctx.stroke();
    const bodyTop = y(Math.max(c.open, c.close));
    const bodyBottom = y(Math.min(c.open, c.close));
    const bodyHeight = Math.max(1, bodyBottom - bodyTop);
    ctx.fillRect(x - candleW / 2, bodyTop, candleW, bodyHeight);
  });

  if (state.ema) {
    ctx.beginPath(); ctx.strokeStyle = "#ff293e"; ctx.lineWidth = 1.25;
    ema.forEach((value, i) => {
      const x = left + i * step + step / 2;
      if (!i) ctx.moveTo(x, y(value)); else ctx.lineTo(x, y(value));
    });
    ctx.stroke();
  }

  if (forecast.length === 3) {
    const referenceIndex = visible.findIndex(c => c.timestamp === forecast[0].reference_time);
    const points = [{ index: referenceIndex, median: forecast[0].base_price,
      low: forecast[0].base_price, high: forecast[0].base_price }, ...forecast.map(p => ({
        index: referenceIndex + p.horizon, median: p.median,
        low: p.quantiles["0.1"], high: p.quantiles["0.9"] }))];
    const fx = p => left + p.index * step + step / 2;
    ctx.beginPath(); points.forEach((p, i) => i ? ctx.lineTo(fx(p), y(p.high)) : ctx.moveTo(fx(p), y(p.high)));
    [...points].reverse().forEach(p => ctx.lineTo(fx(p), y(p.low)));
    ctx.closePath(); ctx.fillStyle = "#6baaff22"; ctx.fill();
    ctx.beginPath(); ctx.strokeStyle = "#85b7ff"; ctx.setLineDash([5, 4]);
    points.forEach((p, i) => i ? ctx.lineTo(fx(p), y(p.median)) : ctx.moveTo(fx(p), y(p.median)));
    ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle = "#9fc7ff"; ctx.textAlign = "right";
    ctx.fillText("Timestral · 15/30/60 min · Q10–Q90 nominal", w - right - 8, top + 12);
  }

  const price = state.quote?.bid || visible.at(-1).close;
  const priceY = y(price);
  ctx.strokeStyle = "#74828d"; ctx.setLineDash([3, 4]);
  ctx.beginPath(); ctx.moveTo(left, priceY); ctx.lineTo(w - right, priceY); ctx.stroke(); ctx.setLineDash([]);
  ctx.fillStyle = "#26333c"; ctx.fillRect(w - right + 2, priceY - 9, right - 3, 18);
  ctx.fillStyle = "#ecf3f5"; ctx.textAlign = "left"; ctx.fillText(fmt(price), w - right + 8, priceY);

  if (state.crosshair) {
    ctx.strokeStyle = "#aab6bf88"; ctx.setLineDash([3, 4]);
    ctx.beginPath(); ctx.moveTo(state.crosshair.x, top); ctx.lineTo(state.crosshair.x, h - bottom); ctx.moveTo(left, state.crosshair.y); ctx.lineTo(w - right, state.crosshair.y); ctx.stroke(); ctx.setLineDash([]);
  }
}

document.querySelectorAll("[data-timeframe]").forEach(button => button.addEventListener("click", () => {
  document.querySelector("[data-timeframe].active")?.classList.remove("active");
  button.classList.add("active"); state.timeframe = button.dataset.timeframe; loadChart();
}));
document.getElementById("zoom-in").addEventListener("click", () => { state.visible = Math.max(35, state.visible - 20); draw(); });
document.getElementById("zoom-out").addEventListener("click", () => { state.visible = Math.min(500, state.visible + 20); draw(); });
document.getElementById("ema-toggle").addEventListener("click", event => { state.ema = !state.ema; event.currentTarget.classList.toggle("active", state.ema); draw(); });
document.getElementById("refresh").addEventListener("click", loadChart);
document.getElementById("retry").addEventListener("click", loadChart);
canvas.addEventListener("mousemove", event => { const rect = canvas.getBoundingClientRect(); state.crosshair = { x: event.clientX - rect.left, y: event.clientY - rect.top }; draw(); });
canvas.addEventListener("mouseleave", () => { state.crosshair = null; draw(); });
window.addEventListener("resize", draw);
window.addEventListener("timestral-update", draw);
loadChart();
state.timer = window.setInterval(loadChart, 3000);
