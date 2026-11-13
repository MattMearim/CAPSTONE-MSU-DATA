"use strict";

/* A self-contained, offline 3D canvas viewer. The iframe receives records from
 * Streamlit; it never fetches data or runs text supplied by those records. */
(() => {
  const MAX_NODES = 500;
  const MAX_EDGES = 3000;
  const PALETTE = Object.freeze({
    domain: {label: "Domain", color: "#8b7848"},
    event: {label: "Dataset", color: "#4e8b67"},
    finding: {label: "Finding", color: "#b8664b"},
    document: {label: "Procedure", color: "#83749e"},
    draft: {label: "AI draft", color: "#a96d50"},
    knowledge: {label: "Reviewed knowledge", color: "#2d7554"},
    topic: {label: "Topic", color: "#7d8d4e"},
    other: {label: "Record", color: "#737f71"}
  });
  const $ = (id) => document.getElementById(id);
  const canvas = $("knowledge-canvas");
  let ctx = null;
  try { ctx = canvas.getContext("2d", {alpha: true}); } catch (_error) { /* Native record list remains available. */ }
  const stage = $("map-stage");
  if (!ctx) {
    canvas.hidden = true;
    $("graph-count").textContent = "3D preview unavailable in this browser";
    $("empty-state").hidden = false;
    $("empty-state").querySelector("h2").textContent = "Explore your records below.";
    $("empty-text").textContent = "Your browser could not display the 3D canvas. The record list below this map gives you access to the same connected knowledge.";
    stage.style.height = "240px";
    document.querySelector(".accessible-explorer").hidden = true;
    document.querySelector(".map-navigation").hidden = true;
    $("keyboard-hint").hidden = true;
    for (const button of document.querySelectorAll("button")) button.disabled = true;
    window.parent.postMessage({isStreamlitMessage: true, type: "streamlit:componentReady", apiVersion: 1}, "*");
    window.parent.postMessage({isStreamlitMessage: true, type: "streamlit:setFrameHeight", height: 365}, "*");
    return;
  }
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const state = {
    nodes: [], edges: [], byId: new Map(), neighbors: new Map(), signature: "",
    selected: null, hover: null, focus: false, incomingFocus: null,
    yaw: -0.45, pitch: 0.22, zoom: 1, width: 800, height: 535,
    paused: reducedMotion.matches, motionChosen: false, motionEnabled: true, dragging: false,
    pointer: null, projected: [], dirty: true, disabled: false,
    lastFrame: 0, lastMotion: 0, nonce: 0,
    nonceSession: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 11)}`,
    parentOrigin: "*", ready: false
  };

  function send(type, extra) {
    window.parent.postMessage(Object.assign({isStreamlitMessage: true, type}, extra || {}), state.parentOrigin);
  }
  function announce(message) { $("map-announcement").textContent = message; }
  function tidy(value, maxLength) {
    return typeof value === "string" ? value.replace(/[\u0000-\u001f\u007f]/g, " ").slice(0, maxLength).trim() : "";
  }
  function ownObject(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }
  function statusLabel(node) {
    if (node.kind === "draft") return "Unreviewed";
    if (node.kind === "knowledge") return node.status ? node.status.replace(/_/g, " ") : "Reviewed";
    return node.status.replace(/_/g, " ");
  }
  function hash(value) {
    let result = 2166136261;
    for (let i = 0; i < value.length; i += 1) result = Math.imul(result ^ value.charCodeAt(i), 16777619);
    return result >>> 0;
  }
  function random(seed) {
    let n = seed || 1;
    return () => { n ^= n << 13; n ^= n >>> 17; n ^= n << 5; return (n >>> 0) / 4294967296; };
  }
  function sanitizeGraph(args) {
    const nodes = [], byId = new Map(), edges = [], edgeKeys = new Set();
    const rawNodes = Array.isArray(args.nodes) ? args.nodes : [];
    for (const raw of rawNodes.slice(0, MAX_NODES * 3)) {
      if (nodes.length === MAX_NODES) break;
      if (!ownObject(raw)) continue;
      const id = tidy(raw.id, 400);
      if (!id || byId.has(id)) continue;
      const rawKind = tidy(raw.kind, 30);
      const node = {
        id, label: tidy(raw.label, 160) || "Untitled record",
        kind: Object.prototype.hasOwnProperty.call(PALETTE, rawKind) ? rawKind : "other",
        status: tidy(raw.status, 100), summary: tidy(raw.summary, 700),
        degree: 0, x: 0, y: 0, z: 0
      };
      nodes.push(node); byId.set(id, node);
    }
    const rawEdges = Array.isArray(args.edges) ? args.edges : [];
    for (const raw of rawEdges.slice(0, MAX_EDGES * 3)) {
      if (edges.length === MAX_EDGES) break;
      if (!ownObject(raw)) continue;
      const source = tidy(raw.source, 400), target = tidy(raw.target, 400);
      if (!byId.has(source) || !byId.has(target) || source === target) continue;
      const kind = tidy(raw.kind || raw.relation, 80), key = JSON.stringify([source, target, kind]);
      if (edgeKeys.has(key)) continue;
      edgeKeys.add(key);
      edges.push({source, target, kind, label: tidy(raw.label, 180)});
      byId.get(source).degree += 1; byId.get(target).degree += 1;
    }
    return {nodes, edges, byId, truncated: rawNodes.length > MAX_NODES || rawEdges.length > MAX_EDGES};
  }

  function arrange(nodes, edges, byId) {
    if (nodes.length === 1) return;
    const kinds = [...new Set(nodes.map((node) => node.kind))].sort();
    const kindIndex = new Map(kinds.map((kind, i) => [kind, i]));
    const velocities = new Map();
    for (const node of nodes) {
      const rng = random(hash(node.id));
      const angle = kindIndex.get(node.kind) / Math.max(kinds.length, 1) * Math.PI * 2;
      node.x = Math.cos(angle) * 90 + (rng() - 0.5) * 220;
      node.y = (rng() - 0.5) * 230;
      node.z = Math.sin(angle) * 90 + (rng() - 0.5) * 220;
      velocities.set(node.id, {x: 0, y: 0, z: 0});
    }
    // Repulsion and springs act in all three dimensions. A deterministic seed
    // keeps the constellation stable when Streamlit reruns to show details.
    const steps = nodes.length > 240 ? 90 : 150;
    for (let step = 0; step < steps; step += 1) {
      const cooling = 1 - step / (steps * 1.33);
      for (let a = 0; a < nodes.length; a += 1) {
        const first = nodes[a], va = velocities.get(first.id);
        for (let b = a + 1; b < nodes.length; b += 1) {
          const second = nodes[b], vb = velocities.get(second.id);
          const dx = first.x - second.x, dy = first.y - second.y, dz = first.z - second.z;
          const squared = dx * dx + dy * dy + dz * dz + 35;
          const factor = Math.min(1.8, 420 / squared) / Math.sqrt(squared);
          va.x += dx * factor; va.y += dy * factor; va.z += dz * factor;
          vb.x -= dx * factor; vb.y -= dy * factor; vb.z -= dz * factor;
        }
      }
      for (const edge of edges) {
        const a = byId.get(edge.source), b = byId.get(edge.target);
        const va = velocities.get(a.id), vb = velocities.get(b.id);
        const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
        const distance = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
        const force = (distance - 70) * 0.008 / distance;
        va.x += dx * force; va.y += dy * force; va.z += dz * force;
        vb.x -= dx * force; vb.y -= dy * force; vb.z -= dz * force;
      }
      for (const node of nodes) {
        const velocity = velocities.get(node.id);
        velocity.x = (velocity.x - node.x * 0.002) * 0.76;
        velocity.y = (velocity.y - node.y * 0.002) * 0.76;
        velocity.z = (velocity.z - node.z * 0.002) * 0.76;
        node.x += Math.max(-5, Math.min(5, velocity.x)) * cooling;
        node.y += Math.max(-5, Math.min(5, velocity.y)) * cooling;
        node.z += Math.max(-5, Math.min(5, velocity.z)) * cooling;
      }
    }
    let mx = 0, my = 0, mz = 0;
    for (const node of nodes) { mx += node.x; my += node.y; mz += node.z; }
    mx /= nodes.length; my /= nodes.length; mz /= nodes.length;
    let extent = 1;
    for (const node of nodes) {
      node.x -= mx; node.y -= my; node.z -= mz;
      extent = Math.max(extent, Math.hypot(node.x, node.y, node.z));
    }
    const scale = 208 / extent;
    for (const node of nodes) { node.x *= scale; node.y *= scale; node.z *= scale; }
  }

  function notifySelection() {
    send("streamlit:setComponentValue", {
      value: {selected_id: state.selected, focus: state.focus, nonce: `${state.nonceSession}:${++state.nonce}`},
      dataType: "json"
    });
  }
  function selectNode(id, notify = true) {
    const next = typeof id === "string" && state.byId.has(id) ? id : null;
    const changed = next !== state.selected;
    state.selected = next;
    if (!next) state.focus = false;
    state.hover = null; hideTooltip();
    updateSelection(); state.dirty = true;
    if (next) {
      const node = state.byId.get(next), count = state.neighbors.get(next).size;
      announce(`${node.label}. ${PALETTE[node.kind].label}. ${count} connected ${count === 1 ? "record" : "records"}. Details are shown below the map.`);
    } else if (changed) announce("Selection cleared. Showing the full knowledge web.");
    if (notify && changed) notifySelection();
  }
  function updateSelection() {
    const node = state.byId.get(state.selected);
    $("selection-card").hidden = !node;
    $("node-picker").value = node ? node.id : "";
    if (!node) return;
    const status = statusLabel(node);
    $("selection-kind").textContent = `${PALETTE[node.kind].label}${status ? ` · ${status}` : ""}`;
    $("selection-title").textContent = node.label;
    const count = state.neighbors.get(node.id).size;
    $("selection-neighbors").textContent = `${count} connected ${count === 1 ? "record" : "records"}`;
    $("focus-button").setAttribute("aria-pressed", String(state.focus));
    $("focus-button").textContent = state.focus ? "Show full web" : "Focus connections";
    $("focus-button").disabled = count === 0 || state.disabled;
  }
  function toggleFocus() {
    if (!state.selected || state.disabled) return;
    state.focus = !state.focus; updateSelection(); state.dirty = true;
    announce(state.focus ? `Highlighting the connections around ${state.byId.get(state.selected).label}.` : "Showing the full knowledge web.");
    notifySelection();
  }
  function updateMotion() {
    $("motion-button").disabled = !state.motionEnabled || state.disabled;
    if (!state.motionEnabled) {
      $("motion-button").setAttribute("aria-pressed", "true");
      $("motion-label").textContent = "Motion off";
      $("motion-button").title = "Enable Gentle motion in the sidebar";
      $("motion-button").querySelector(".button-symbol").textContent = "Ⅱ";
      return;
    }
    $("motion-button").setAttribute("aria-pressed", String(state.paused));
    $("motion-label").textContent = state.paused ? "Rotate slowly" : "Pause rotation";
    $("motion-button").title = state.paused ? "Start slow automatic rotation (Space)" : "Pause automatic rotation (Space)";
    $("motion-button").querySelector(".button-symbol").textContent = state.paused ? "▷" : "Ⅱ";
  }
  function toggleMotion() {
    if (!state.motionEnabled || state.disabled) return;
    state.paused = !state.paused; state.motionChosen = true; state.lastMotion = 0;
    updateMotion(); state.dirty = true;
    announce(state.paused ? "Automatic rotation paused." : "Automatic rotation started.");
  }
  function resetView() {
    const wasFocused = state.focus;
    state.yaw = -0.45; state.pitch = 0.22; state.zoom = 1; state.focus = false;
    updateZoom(); updateSelection(); hideTooltip(); state.dirty = true;
    announce("View reset. Showing the full knowledge web.");
    if (wasFocused) notifySelection();
  }
  function updateZoom() { $("zoom-level").textContent = `${Math.round(state.zoom * 100)}%`; }
  function zoomBy(amount) {
    state.zoom = Math.max(0.45, Math.min(2.6, state.zoom * amount));
    updateZoom(); hideTooltip(); state.dirty = true;
  }

  function render(args, disabled) {
    const graph = sanitizeGraph(args);
    const signature = JSON.stringify([graph.nodes.map((n) => n.id).sort(), graph.edges.map((e) => [e.source, e.target, e.kind]).sort()]);
    const previous = state.byId;
    state.nodes = graph.nodes; state.edges = graph.edges; state.byId = graph.byId;
    if (signature !== state.signature) {
      arrange(state.nodes, state.edges, state.byId);
      state.signature = signature;
    } else {
      for (const node of state.nodes) {
        const old = previous.get(node.id);
        if (old) { node.x = old.x; node.y = old.y; node.z = old.z; }
      }
    }
    state.neighbors = new Map(state.nodes.map((n) => [n.id, new Set()]));
    for (const edge of state.edges) {
      state.neighbors.get(edge.source).add(edge.target);
      state.neighbors.get(edge.target).add(edge.source);
    }
    state.disabled = disabled;
    const motionEnabled = args.motion_enabled !== false;
    if (motionEnabled !== state.motionEnabled) {
      state.lastMotion = 0;
      if (motionEnabled && !state.motionChosen) state.paused = reducedMotion.matches;
      state.motionEnabled = motionEnabled;
    }
    const count = state.nodes.length, edgeCount = state.edges.length;
    $("graph-count").textContent = `${count} ${count === 1 ? "record" : "records"} · ${edgeCount} ${edgeCount === 1 ? "connection" : "connections"}${graph.truncated ? " · view limited for clarity" : ""}`;
    $("empty-state").hidden = count > 0;
    $("empty-text").textContent = tidy(args.empty_message, 350) || "Add documents, investigate an event, or save a wiki entry to begin building your knowledge web.";
    $("node-picker").replaceChildren(new Option("Choose a node…", ""));
    for (const node of [...state.nodes].sort((a, b) => a.label.localeCompare(b.label))) {
      $("node-picker").add(new Option(`${PALETTE[node.kind].label} · ${node.label}`, node.id));
    }
    $("node-picker").disabled = count === 0 || disabled;
    $("legend").replaceChildren();
    for (const kind of Object.keys(PALETTE)) {
      if (!state.nodes.some((node) => node.kind === kind)) continue;
      const item = document.createElement("span"), dot = document.createElement("span"), label = document.createElement("span");
      item.className = "legend-item"; dot.className = "legend-dot";
      dot.style.backgroundColor = kind === "draft" ? "transparent" : PALETTE[kind].color;
      if (kind === "draft") dot.style.borderColor = PALETTE[kind].color;
      label.textContent = PALETTE[kind].label;
      item.append(dot, label); $("legend").append(item);
    }
    const selected = Object.prototype.hasOwnProperty.call(args, "selected_id") ? args.selected_id : state.selected;
    selectNode(selected, false);
    const focus = tidy(args.focus_id, 400);
    if (focus && focus !== state.incomingFocus && state.byId.has(focus)) {
      selectNode(focus, false); state.focus = true; updateSelection();
    }
    state.incomingFocus = focus || null;
    if (typeof args.focus_enabled === "boolean") {
      state.focus = args.focus_enabled && Boolean(state.selected);
    }
    for (const button of document.querySelectorAll("button")) button.disabled = disabled;
    updateMotion(); updateSelection(); state.dirty = true; resize(); frameHeight();
  }

  function projectNodes() {
    const cy = Math.cos(state.yaw), sy = Math.sin(state.yaw), cp = Math.cos(state.pitch), sp = Math.sin(state.pitch);
    const fov = Math.min(state.width * 0.86, state.height * 1.19) * state.zoom;
    const centerX = state.width * 0.5, centerY = state.height * 0.47;
    return state.nodes.map((node) => {
      const ax = node.x * cy + node.z * sy, az = node.z * cy - node.x * sy;
      const ay = node.y * cp - az * sp, z = node.y * sp + az * cp;
      const perspective = fov / (525 - z);
      return {node, x: centerX + ax * perspective, y: centerY + ay * perspective, z,
        radius: Math.max(4.8, Math.min(12, (6.4 + Math.min(4, Math.sqrt(node.degree) * 0.7)) * perspective)),
        depth: Math.max(0.2, Math.min(1, (z + 260) / 480))};
    });
  }
  function rgba(hex, alpha) {
    return `rgba(${parseInt(hex.slice(1, 3), 16)},${parseInt(hex.slice(3, 5), 16)},${parseInt(hex.slice(5, 7), 16)},${alpha})`;
  }
  function draw() {
    ctx.clearRect(0, 0, state.width, state.height);
    if (!state.nodes.length) { state.projected = []; return; }
    const points = projectNodes(), pointMap = new Map(points.map((point) => [point.node.id, point]));
    state.projected = points;
    const focusId = state.hover || state.selected;
    const neighborIds = state.neighbors.get(focusId) || new Set();
    const dim = state.focus && state.selected;
    // A very faint equatorial ring makes the depth and orbit visible without
    // adding synthetic records or drawing attention away from real evidence.
    ctx.strokeStyle = "rgba(108,143,89,0.065)"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.ellipse(state.width * 0.5, state.height * 0.49, Math.min(state.width * 0.38, 260) * state.zoom, 74 * state.zoom, -0.12, 0, Math.PI * 2); ctx.stroke();
    for (const edge of state.edges) {
      const a = pointMap.get(edge.source), b = pointMap.get(edge.target);
      const active = focusId && (edge.source === focusId || edge.target === focusId);
      const inFocus = !dim || edge.source === state.selected || edge.target === state.selected;
      const depth = (a.depth + b.depth) / 2;
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
      ctx.lineWidth = active ? 1.8 : 1.05;
      ctx.strokeStyle = active ? rgba(PALETTE[state.byId.get(focusId).kind].color, 0.72) : `rgba(106,133,92,${(0.26 + depth * 0.17) * (inFocus ? 1 : 0.16) * (focusId ? 0.65 : 1)})`;
      if (a.node.kind === "draft" || b.node.kind === "draft") ctx.setLineDash([3, 4]);
      ctx.stroke(); ctx.setLineDash([]);
    }
    const sorted = [...points].sort((a, b) => a.z - b.z);
    for (const point of sorted) {
      const {node, x, y, radius, depth} = point;
      const active = node.id === focusId, selected = node.id === state.selected;
      const related = active || neighborIds.has(node.id);
      const inFocus = !dim || node.id === state.selected || state.neighbors.get(state.selected).has(node.id);
      const opacity = (0.72 + depth * 0.28) * (inFocus ? 1 : 0.14) * (focusId && !related ? 0.58 : 1);
      const color = PALETTE[node.kind].color;
      if (active || selected) {
        const glow = ctx.createRadialGradient(x, y, radius, x, y, radius * 4.5);
        glow.addColorStop(0, rgba(color, 0.16)); glow.addColorStop(1, rgba(color, 0));
        ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(x, y, radius * 4.5, 0, Math.PI * 2); ctx.fill();
        ctx.beginPath(); ctx.arc(x, y, radius + 4, 0, Math.PI * 2);
        ctx.strokeStyle = rgba(color, selected ? 0.62 : 0.35); ctx.lineWidth = 1; ctx.stroke();
      }
      ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fillStyle = node.kind === "draft" ? rgba("#fbfef7", opacity) : rgba(color, opacity);
      ctx.fill(); ctx.lineWidth = node.kind === "draft" ? 1.5 : 1.2;
      ctx.strokeStyle = node.kind === "draft" ? rgba(color, opacity) : rgba("#ffffff", opacity * 0.85); ctx.stroke();
      if (node.kind !== "draft" && radius > 4.5) {
        ctx.beginPath(); ctx.arc(x - radius * 0.23, y - radius * 0.26, radius * 0.23, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255,255,255,${0.2 * opacity})`; ctx.fill();
      }
    }
    // Labels are prioritized, collision checked, and drawn in screen space so
    // they stay readable while the underlying network rotates in 3D.
    const labels = [...points].sort((a, b) => {
      const priority = (point) => (point.node.id === focusId ? 1000 : 0) + (neighborIds.has(point.node.id) ? 100 : 0) + point.node.degree * 3 + point.depth;
      return priority(b) - priority(a);
    });
    const boxes = [], maxLabels = state.width < 500 ? 16 : 30;
    let drawn = 0;
    for (const point of labels) {
      const {node, x, y, radius, depth} = point;
      const active = node.id === focusId, related = active || neighborIds.has(node.id);
      const inFocus = !dim || node.id === state.selected || state.neighbors.get(state.selected).has(node.id);
      if (!inFocus || (drawn >= maxLabels && !related) || (focusId && !related && depth < 0.55)) continue;
      const max = state.width < 500 ? 23 : 30;
      const label = node.label.length > max ? `${node.label.slice(0, max - 1)}…` : node.label;
      ctx.font = `${active ? "500 " : ""}${active ? 13 : 11}px ${active ? "Georgia, serif" : "-apple-system, BlinkMacSystemFont, sans-serif"}`;
      const width = ctx.measureText(label).width, lx = x + radius + 7, ly = y + 3;
      const box = {x: lx - 3, y: ly - 12, w: width + 6, h: 16};
      if (lx + width > state.width - 12 || lx < 8 || ly < 48 || ly > state.height - (state.selected ? 100 : 32)) continue;
      if (!active && boxes.some((old) => box.x < old.x + old.w && box.x + box.w > old.x && box.y < old.y + old.h && box.y + box.h > old.y)) continue;
      boxes.push(box); drawn += 1;
      ctx.lineWidth = 4; ctx.lineJoin = "round"; ctx.strokeStyle = "rgba(247,251,242,0.94)"; ctx.strokeText(label, lx, ly);
      ctx.fillStyle = active ? "#2a4b29" : `rgba(71,96,58,${(0.78 + depth * 0.2) * (focusId && !related ? 0.5 : 1)})`;
      ctx.fillText(label, lx, ly);
    }
  }

  function pointAt(x, y) {
    let closest = null, minimum = Infinity;
    for (const point of state.projected) {
      if (state.focus && state.selected && point.node.id !== state.selected && !state.neighbors.get(state.selected).has(point.node.id)) continue;
      const distance = Math.hypot(point.x - x, point.y - y);
      if (distance < point.radius + 9 && distance < minimum) { closest = point; minimum = distance; }
    }
    return closest;
  }
  function hideTooltip() { $("node-tooltip").hidden = true; canvas.classList.remove("is-hovering"); }
  function hoverAt(x, y) {
    const point = pointAt(x, y), id = point ? point.node.id : null;
    if (id !== state.hover) { state.hover = id; state.dirty = true; }
    if (!point) { hideTooltip(); return; }
    const node = point.node, tooltip = $("node-tooltip");
    const status = statusLabel(node);
    $("tooltip-kind").textContent = `${PALETTE[node.kind].label}${status ? ` · ${status}` : ""}`;
    $("tooltip-title").textContent = node.label;
    const summary = node.summary.length > 170 ? `${node.summary.slice(0, 167)}…` : node.summary;
    $("tooltip-summary").textContent = summary;
    $("tooltip-summary").hidden = !summary;
    tooltip.hidden = false; canvas.classList.add("is-hovering");
    tooltip.style.left = `${Math.max(10, Math.min(state.width - tooltip.offsetWidth - 10, x + 18))}px`;
    tooltip.style.top = `${Math.max(10, Math.min(state.height - tooltip.offsetHeight - 95, y - tooltip.offsetHeight - 12))}px`;
  }
  function resize() {
    const bounds = stage.getBoundingClientRect(), ratio = Math.min(window.devicePixelRatio || 1, 2.5);
    const width = Math.max(1, Math.round(bounds.width)), height = Math.max(1, Math.round(bounds.height));
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      state.width = width; state.height = height;
      canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0); state.dirty = true;
    }
  }
  let lastHeight = 0;
  function frameHeight() {
    const height = Math.ceil(document.querySelector(".web-shell").getBoundingClientRect().height) + 2;
    if (height !== lastHeight) { lastHeight = height; send("streamlit:setFrameHeight", {height}); }
  }
  function tick(time) {
    window.requestAnimationFrame(tick);
    if (document.hidden || time - state.lastFrame < 30) return;
    state.lastFrame = time;
    const moving = state.motionEnabled && !state.paused && !state.dragging && !state.hover && state.nodes.length > 1;
    if (moving) {
      const elapsed = state.lastMotion ? Math.min(60, time - state.lastMotion) : 0;
      state.yaw += elapsed * 0.000035; state.dirty = true;
    }
    state.lastMotion = time;
    if (state.dirty) { draw(); state.dirty = false; }
  }

  canvas.addEventListener("pointerdown", (event) => {
    if (state.disabled || (event.pointerType === "mouse" && event.button !== 0)) return;
    const rect = canvas.getBoundingClientRect();
    state.pointer = {id: event.pointerId, x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY, moved: false, localX: event.clientX - rect.left, localY: event.clientY - rect.top};
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    const rect = canvas.getBoundingClientRect(), x = event.clientX - rect.left, y = event.clientY - rect.top;
    const pointer = state.pointer;
    if (pointer && pointer.id === event.pointerId) {
      if (Math.hypot(event.clientX - pointer.startX, event.clientY - pointer.startY) > 4) pointer.moved = true;
      if (pointer.moved) {
        state.dragging = true; canvas.classList.add("is-dragging"); hideTooltip(); state.hover = null;
        state.yaw += (event.clientX - pointer.x) * 0.006;
        state.pitch = Math.max(-1.35, Math.min(1.35, state.pitch + (event.clientY - pointer.y) * 0.006));
        state.dirty = true;
      }
      pointer.x = event.clientX; pointer.y = event.clientY;
    } else if (!state.disabled) hoverAt(x, y);
  });
  function releasePointer(event, cancelled) {
    const pointer = state.pointer;
    if (!pointer || pointer.id !== event.pointerId) return;
    if (!pointer.moved && !cancelled && !state.disabled) {
      const point = pointAt(pointer.localX, pointer.localY);
      if (point) selectNode(point.node.id);
    }
    state.pointer = null; state.dragging = false; canvas.classList.remove("is-dragging");
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    state.dirty = true;
  }
  canvas.addEventListener("pointerup", (event) => releasePointer(event, false));
  canvas.addEventListener("pointercancel", (event) => releasePointer(event, true));
  canvas.addEventListener("lostpointercapture", () => { state.pointer = null; state.dragging = false; canvas.classList.remove("is-dragging"); });
  canvas.addEventListener("pointerleave", () => { if (!state.dragging) { state.hover = null; hideTooltip(); state.dirty = true; } });
  canvas.addEventListener("wheel", (event) => {
    if (state.disabled) return;
    event.preventDefault(); zoomBy(Math.exp(-Math.max(-90, Math.min(90, event.deltaY)) * 0.002));
  }, {passive: false});
  canvas.addEventListener("keydown", (event) => {
    if (state.disabled) return;
    let handled = true;
    if (event.key === "ArrowLeft") state.yaw -= 0.12;
    else if (event.key === "ArrowRight") state.yaw += 0.12;
    else if (event.key === "ArrowUp") state.pitch = Math.max(-1.35, state.pitch - 0.12);
    else if (event.key === "ArrowDown") state.pitch = Math.min(1.35, state.pitch + 0.12);
    else if (["+", "="].includes(event.key)) zoomBy(1.15);
    else if (["-", "_"].includes(event.key)) zoomBy(1 / 1.15);
    else if (event.key === "Home") resetView();
    else if (event.key === " ") toggleMotion();
    else if (event.key === "Escape") selectNode(null);
    else handled = false;
    if (handled) { event.preventDefault(); hideTooltip(); state.dirty = true; }
  });
  $("motion-button").addEventListener("click", toggleMotion);
  $("reset-button").addEventListener("click", resetView);
  $("zoom-in").addEventListener("click", () => zoomBy(1.2));
  $("zoom-out").addEventListener("click", () => zoomBy(1 / 1.2));
  $("focus-button").addEventListener("click", toggleFocus);
  $("clear-button").addEventListener("click", () => selectNode(null));
  $("node-picker").addEventListener("change", (event) => selectNode(event.target.value));
  $("keyboard-hint").addEventListener("click", () => canvas.focus());
  reducedMotion.addEventListener("change", (event) => {
    if (!state.motionChosen) { state.paused = event.matches; updateMotion(); state.dirty = true; }
  });
  new ResizeObserver(() => { resize(); frameHeight(); }).observe(document.querySelector(".web-shell"));
  window.addEventListener("message", (event) => {
    if (event.source !== window.parent || !ownObject(event.data) || event.data.type !== "streamlit:render" || !ownObject(event.data.args)) return;
    // Only the containing Streamlit page can supply records. Origin is learned
    // from that parent; sandboxed opaque origins retain postMessage's wildcard.
    state.parentOrigin = event.origin && event.origin !== "null" ? event.origin : "*";
    render(event.data.args, event.data.disabled === true);
    state.ready = true;
  });
  updateMotion(); resize();
  send("streamlit:componentReady", {apiVersion: 1});
  frameHeight();
  window.requestAnimationFrame(tick);
})();
