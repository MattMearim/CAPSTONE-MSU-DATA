"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const valid = value => typeof value === "number" && Number.isFinite(value) && value >= 0;
  const clamp = value => Math.min(100, Math.max(0, value));
  const gib = value => valid(value) ? (value / 1073741824).toFixed(2) + " GiB" : "Unknown";
  const percent = value => valid(value) ? clamp(value).toFixed(1) + "%" : "Unknown";
  const detail = new URLSearchParams(location.search).get("details") === "1";
  $("details").hidden = !detail;
  $("full-view").hidden = detail;
  document.body.classList.toggle("expanded", detail);
  let paused = false, timer = null, controller = null, history = [], sequence = 0;
  function text(id, value) { $(id).textContent = value; }
  function status(message, state) { text("status", message); $("status-dot").className = "dot " + state; }
  function bar(id, value) {
    const element = $(id);
    if (valid(value)) element.value = clamp(value); else element.removeAttribute("value");
    element.setAttribute("aria-valuetext", valid(value) ? percent(value) : "Unavailable");
  }
  function table(id, rows) {
    const fragment = document.createDocumentFragment();
    for (const values of rows) {
      const row = document.createElement("tr");
      for (const value of values) { const cell = document.createElement("td"); cell.textContent = value; row.appendChild(cell); }
      fragment.appendChild(row);
    }
    $(id).replaceChildren(fragment);
  }
  function render(report) {
    const system = report.system, processes = report.processes || [], models = report.models || [];
    const appRam = processes.reduce((sum, entry) => sum + (valid(entry.resident_bytes) ? entry.resident_bytes : 0), 0);
    const appCpu = processes.reduce((sum, entry) => sum + (valid(entry.cpu_percent) ? entry.cpu_percent : 0), 0);
    const ramPercent = system.ram_total_bytes > 0 ? 100 * system.ram_used_bytes / system.ram_total_bytes : null;
    text("cpu", percent(system.cpu_percent)); bar("cpu-bar", system.cpu_percent);
    text("cpu-detail", "App " + percent(appCpu) + " · whole PC above");
    text("ram", gib(system.ram_used_bytes)); bar("ram-bar", ramPercent);
    text("ram-detail", "of " + gib(system.ram_total_bytes) + " · app ≈ " + gib(appRam));
    const devices = report.gpu && report.gpu.available ? report.gpu.devices : [];
    const totalGpu = devices.reduce((sum, entry) => sum + entry.total_bytes, 0);
    const usedGpu = devices.reduce((sum, entry) => sum + entry.used_bytes, 0);
    const gpuBusy = devices.length ? Math.max(...devices.map(entry => entry.utilization_percent)) : null;
    text("gpu", devices.length ? gib(usedGpu) : "Unavailable"); bar("gpu-bar", totalGpu > 0 ? usedGpu / totalGpu * 100 : null);
    text("gpu-detail", devices.length ? "of " + gib(totalGpu) + " · " + percent(gpuBusy) + " busy" : "No GPU telemetry; use is unknown");
    const selected = models.find(entry => entry.selected);
    let modelText;
    if (selected && selected.loaded === true) modelText = selected.model + " · model RAM ≈ " + gib(selected.non_gpu_bytes) + " · model GPU " + gib(selected.gpu_bytes);
    else if (selected && selected.loaded === false) modelText = selected.model + " · idle / unloaded · model files remain on disk";
    else modelText = (report.active && report.active.model || "Selected model") + " · model allocation unavailable";
    if (report.quality_agent && report.quality_agent.enabled) {
      const quality = models.find(entry => (entry.roles || []).includes('quality'));
      modelText += ' | Quality ' + report.quality_agent.model + ': ' + (quality && quality.loaded === true ? 'RAM ≈ ' + gib(quality.non_gpu_bytes) + ', GPU ' + gib(quality.gpu_bytes) : quality && quality.loaded === false ? 'idle / unloaded' : 'allocation unknown');
    }
    text("model", modelText); $("model").title = modelText + ". Model estimates overlap process and GPU totals.";
    const measured = new Date(report.measured_at);
    if (!Number.isFinite(measured.getTime())) throw new Error("Invalid measurement time");
    const age = Date.now() - measured.getTime();
    status(age > 15000 ? "Stale sample" : "Live · " + measured.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'}), age > 15000 ? "offline" : "live");
    $("status").dataset.measuredAt = report.measured_at;
    history.push({at: measured.getTime(), cpu: system.cpu_percent, ram: ramPercent, gpu: gpuBusy});
    const historyStart = measured.getTime() - 120000;
    history = history.filter(entry => entry.at >= historyStart).slice(-80);
    for (const key of ["cpu", "ram", "gpu"]) {
      $(key + "-history").setAttribute("points", history.map(entry => valid(entry[key]) ? (clamp((entry.at - historyStart) / 120000 * 100) * 6).toFixed(1) + "," + (100 - clamp(entry[key])).toFixed(1) : null).filter(Boolean).join(" "));
    }
    if (detail) {
      table("processes", processes.map(entry => [entry.component, gib(entry.resident_bytes), percent(entry.cpu_percent)]));
      table("models", models.map(entry => [entry.model + (entry.roles && entry.roles.length ? ' · ' + entry.roles.join(' / ') : entry.selected ? " · selected" : ""), entry.loaded === true ? "Loaded" : entry.loaded === false ? "Unloaded" : "Unknown", gib(entry.non_gpu_bytes), gib(entry.gpu_bytes)]));
      text("timestamp", "Updated " + measured.toLocaleTimeString() + " · about every two seconds · GPU totals include other apps.");
    }
  }
  function unavailable() {
    for (const id of ["cpu", "ram", "gpu"]) { text(id, "Unavailable"); bar(id + "-bar", null); text(id + "-detail", "Waiting for connection"); }
    text("model", "Live readings unavailable. Retrying automatically.");
    status("Connection lost", "offline");
    if (detail) {
      table("processes", [["Telemetry unavailable", "Unknown", "Unknown"]]);
      table("models", [["Telemetry unavailable", "Unknown", "Unknown", "Unknown"]]);
      text("timestamp", "Connection lost. Retrying automatically; the graph shows earlier samples.");
    }
  }
  async function poll() {
    clearTimeout(timer);
    if (paused || document.hidden) return;
    const current = ++sequence;
    const requestController = new AbortController();
    controller = requestController;
    const timeout = setTimeout(() => requestController.abort(), 8000);
    try {
      const response = await fetch("/system/ai/resources?storage=false", {cache:"no-store", credentials:"omit", signal:requestController.signal});
      if (!response.ok) throw new Error("Telemetry unavailable");
      const report = await response.json();
      if (current === sequence && !paused && !document.hidden) render(report);
    } catch (_) { if (current === sequence && !paused && !document.hidden) unavailable(); }
    finally {
      clearTimeout(timeout);
      if (current === sequence) { controller = null; if (!paused && !document.hidden) timer = setTimeout(poll, 2000); }
    }
  }
  function stop() { ++sequence; clearTimeout(timer); if (controller) controller.abort(); controller = null; }
  $("pause").addEventListener("click", () => {
    paused = !paused; $("pause").setAttribute("aria-pressed", String(paused)); text("pause", paused ? "Resume" : "Pause");
    if (paused) { stop(); status("Paused · last reading", ""); } else poll();
  });
  document.addEventListener("visibilitychange", () => {
    stop(); if (document.hidden) { if (!paused) status("Paused while hidden", ""); } else if (!paused) poll();
  });
  window.addEventListener("pagehide", stop);
  poll();
})();
