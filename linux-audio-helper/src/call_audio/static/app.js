(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const elements = Object.fromEntries([
    "connection-status", "connection-notice", "connection-message", "reconnect-button",
    "state-badge", "state-label", "notice", "capture-form",
    "output-device", "refresh-devices", "isolate-app", "app-picker", "playback-app",
    "isolation-help", "engine-help", "level-label", "level-meter", "level-fill",
    "start-button", "start-label", "stop-button", "stop-label", "capture-status",
    "copy-transcript", "export-transcript", "clear-transcript", "elapsed-value",
    "cost-value", "queue-value", "processing-value", "processing-label", "empty-state",
    "transcript-scroll", "transcript-list", "jump-latest", "segment-count", "mode-footer",
    "action-status",
  ].map((id) => [id, $(id)]));
  const engineInputs = [...document.querySelectorAll('input[name="engine"]')];
  const activeStates = new Set(["loading", "listening", "stopping"]);
  const segments = new Map();
  const segmentNodes = new Map();
  const state = {
    state: "idle", session_id: null, engine: "local", cloud_configured: false,
    outputs: [], streams: [], elapsed_seconds: 0, estimated_cost_usd: 0,
    queue_ms: null, processing_ms: null, level: 0,
  };
  let connected = false;
  let busy = false;
  let refreshing = false;
  let followLatest = true;
  let metricReceivedAt = performance.now();
  let eventSource;
  let rendering = false;

  const isActive = () => activeStates.has(state.state);
  const selectedEngine = () => engineInputs.find((input) => input.checked)?.value || "local";
  const hasText = () => [...segments.values()].some((segment) => segment.text?.trim());
  const numeric = (value) => typeof value === "number" && Number.isFinite(value);

  function formatTime(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60).toString().padStart(2, "0");
    const remainder = (total % 60).toString().padStart(2, "0");
    return hours ? `${hours}:${minutes}:${remainder}` : `${minutes}:${remainder}`;
  }

  function showNotice(message) {
    elements.notice.textContent = message || "";
    elements.notice.hidden = !message;
  }

  function announce(message) {
    elements["action-status"].textContent = message;
  }

  async function request(path, payload) {
    const response = await fetch(path, payload === undefined ? {
      cache: "no-store",
    } : {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Call-Audio": "1" },
      body: JSON.stringify(payload),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || `Request failed (${response.status}).`);
    return body;
  }

  function updateSelect(select, items, placeholder, describe, preferred) {
    const previous = preferred ?? select.value;
    const options = items.map((item) => {
      const option = document.createElement("option");
      option.value = String(item.id);
      option.textContent = describe(item);
      return option;
    });
    if (!options.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = placeholder;
      options.push(option);
    }
    select.replaceChildren(...options);
    if (items.some((item) => String(item.id) === String(previous))) {
      select.value = String(previous);
    } else if (items.some((item) => item.is_default)) {
      select.value = String(items.find((item) => item.is_default).id);
    }
  }

  function updateDevices(data) {
    if (Array.isArray(data.outputs)) state.outputs = data.outputs;
    if (Array.isArray(data.streams)) state.streams = data.streams;
    updateSelect(elements["output-device"], state.outputs, "No audio outputs found", (item) =>
      `${item.name || item.id}${item.is_default ? " · Default" : ""}`);
    updateSelect(elements["playback-app"], state.streams, "No playing apps found", (item) => {
      const app = item.application || item.name || `App ${item.id}`;
      return item.name && item.name !== app ? `${app} · ${item.name}` : app;
    });
    updateControls();
  }

  function updateControls() {
    const active = isActive();
    const engine = selectedEngine();
    const isolated = elements["isolate-app"].checked;
    const cloudUnavailable = engine === "cloud" && !state.cloud_configured;
    elements["app-picker"].hidden = !isolated;
    elements["isolation-help"].hidden = isolated;
    elements["output-device"].disabled = active || busy || !state.outputs.length;
    elements["playback-app"].disabled = active || busy || !state.streams.length;
    elements["isolate-app"].disabled = active || busy;
    elements["refresh-devices"].disabled = active || busy || refreshing;
    elements["refresh-devices"].textContent = refreshing ? "Refreshing…" : "Refresh";
    engineInputs.forEach((input) => { input.disabled = active || busy; });
    elements["engine-help"].textContent = engine === "local"
      ? "Runs on this computer. No transcription API charge."
      : cloudUnavailable
        ? "Cloud transcription isn’t configured on this device. On-device transcription is available."
        : "Audio is sent to AssemblyAI. Estimated $0.15 per connected hour, including silence.";
    elements["start-button"].hidden = active;
    elements["stop-button"].hidden = !active;
    elements["start-button"].disabled = busy || !connected || !elements["output-device"].value
      || cloudUnavailable || (isolated && !elements["playback-app"].value);
    elements["start-label"].textContent = busy && !active ? "Starting…" : "Start listening";
    // The event stream can fail while HTTP requests still work. Keep Stop usable.
    elements["stop-button"].disabled = busy || state.state === "stopping";
    elements["stop-label"].textContent = state.state === "stopping" ? "Stopping…" : "Stop listening";
    const labels = { idle: "Ready", loading: "Preparing", listening: "Listening", stopping: "Stopping", error: "Needs attention" };
    elements["state-badge"].dataset.state = state.state;
    elements["state-label"].textContent = labels[state.state] || "Ready";
    const descriptions = {
      idle: "Capture is off. Start when your call is ready.",
      loading: "Preparing transcription. The first start may take a moment.",
      listening: "Listening to playback. Closing this tab does not stop capture.",
      stopping: "Finishing the remaining transcript…",
      error: "Capture stopped. Check the message above.",
    };
    elements["capture-status"].textContent = connected
      ? descriptions[state.state] || descriptions.idle
      : active
        ? "Audio capture may still be running. You can try Stop listening."
        : "Connection lost. Reconnecting to your audio helper…";
    elements["connection-message"].textContent = active
      ? "Live updates disconnected. Audio capture may still be running; use Stop listening to end it. Reconnecting automatically."
      : "Live updates disconnected. Reconnecting to your audio helper automatically.";
    const textAvailable = hasText();
    elements["copy-transcript"].disabled = !textAvailable;
    elements["export-transcript"].disabled = !textAvailable;
    elements["clear-transcript"].disabled = active || busy || !textAvailable || !connected;
    elements["mode-footer"].textContent = engine === "local" ? "ON-DEVICE TRANSCRIPTION" : "CLOUD TRANSCRIPTION";
    elements["processing-label"].textContent = (active ? state.engine : engine) === "cloud" ? "Audio send time" : "Local processing";
  }

  function setDelay(element, value) {
    element.replaceChildren(document.createTextNode(numeric(value) ? Math.round(value).toString() : "—"));
    const unit = document.createElement("span");
    unit.textContent = " ms";
    element.append(unit);
  }

  function updateMetrics(data) {
    ["elapsed_seconds", "estimated_cost_usd", "queue_ms", "processing_ms", "level"].forEach((key) => {
      if (key in data) state[key] = data[key];
    });
    if ("elapsed_seconds" in data) metricReceivedAt = performance.now();
    elements["cost-value"].textContent = `$${Math.max(0, Number(state.estimated_cost_usd) || 0).toFixed(4)}`;
    setDelay(elements["queue-value"], state.queue_ms);
    setDelay(elements["processing-value"], state.processing_ms);
    const level = Math.max(0, Math.min(1, Number(state.level) || 0));
    elements["level-fill"].style.transform = `scaleX(${level})`;
    elements["level-meter"].setAttribute("aria-valuenow", String(Math.round(level * 100)));
    elements["level-label"].textContent = level > 0.015 ? "Audio detected" : "Silent";
    updateElapsed();
  }

  function updateElapsed() {
    const additional = connected && state.state === "listening" ? (performance.now() - metricReceivedAt) / 1000 : 0;
    elements["elapsed-value"].textContent = formatTime((Number(state.elapsed_seconds) || 0) + additional);
  }

  function resetTranscript() {
    segments.clear();
    segmentNodes.clear();
    elements["transcript-list"].replaceChildren();
    followLatest = true;
    scheduleTranscriptRender();
  }

  function upsertTranscript(event) {
    if (!event || event.segment_id === undefined || event.segment_id === null) return;
    if (!state.session_id || String(event.session_id) !== String(state.session_id)) return;
    const key = String(event.segment_id);
    const previous = segments.get(key);
    if (previous?.is_final && !event.is_final) return;
    segments.set(key, { ...previous, ...event });
    scheduleTranscriptRender();
  }

  function orderedSegments() {
    return [...segments.values()].sort((left, right) => (Number(left.start_ms) || 0) - (Number(right.start_ms) || 0));
  }

  function scheduleTranscriptRender() {
    if (rendering) return;
    rendering = true;
    requestAnimationFrame(() => {
      rendering = false;
      const ordered = orderedSegments();
      const list = elements["transcript-list"];
      let previousNode = null;
      ordered.forEach((segment) => {
        const key = String(segment.segment_id);
        let node = segmentNodes.get(key);
        if (!node) {
          const root = document.createElement("article");
          root.className = "transcript-segment";
          const time = document.createElement("span");
          time.className = "segment-time";
          const text = document.createElement("p");
          text.className = "segment-text";
          root.append(time, text);
          node = { root, time, text };
          segmentNodes.set(key, node);
        }
        const timestamp = formatTime((Number(segment.start_ms) || 0) / 1000);
        if (node.time.textContent !== timestamp) node.time.textContent = timestamp;
        if (node.text.textContent !== (segment.text || "")) node.text.textContent = segment.text || "";
        node.root.classList.toggle("is-partial", !segment.is_final);
        node.root.setAttribute("aria-label", `${segment.is_final ? "Final" : "Partial"} transcript at ${timestamp}`);
        const expected = previousNode ? previousNode.nextSibling : list.firstChild;
        if (expected !== node.root) list.insertBefore(node.root, expected);
        previousNode = node.root;
      });
      elements["empty-state"].hidden = ordered.length > 0;
      elements["segment-count"].textContent = `${ordered.length} segment${ordered.length === 1 ? "" : "s"}`;
      if (followLatest && ordered.length) elements["transcript-scroll"].scrollTop = elements["transcript-scroll"].scrollHeight;
      elements["jump-latest"].hidden = followLatest || !ordered.length;
      updateControls();
    });
  }

  function applySnapshot(snapshot) {
    if (!snapshot || typeof snapshot !== "object") return;
    const newSession = snapshot.session_id != null && String(snapshot.session_id) !== String(state.session_id);
    if (newSession || (Array.isArray(snapshot.segments) && !snapshot.segments.length)) resetTranscript();
    ["state", "session_id", "engine", "cloud_configured", "error"].forEach((key) => {
      if (key in snapshot) state[key] = snapshot[key];
    });
    if (isActive()) engineInputs.forEach((input) => { input.checked = input.value === state.engine; });
    if (snapshot.outputs || snapshot.streams) updateDevices(snapshot);
    if (Array.isArray(snapshot.segments)) snapshot.segments.forEach(upsertTranscript);
    updateMetrics(snapshot);
    if (snapshot.error) showNotice(snapshot.error);
    updateControls();
  }

  function connectEvents() {
    eventSource?.close();
    eventSource = new EventSource("/api/events");
    eventSource.onopen = () => {
      connected = true;
      elements["connection-notice"].hidden = true;
      elements["connection-status"].textContent = "Helper connected";
      updateControls();
    };
    eventSource.onmessage = ({ data }) => {
      let event;
      try { event = JSON.parse(data); } catch { return; }
      switch (event.type) {
        case "state": applySnapshot(event); break;
        case "transcript": upsertTranscript(event); break;
        case "metrics":
          if (event.session_id != null && String(event.session_id) !== String(state.session_id)) return;
          updateMetrics(event);
          break;
        case "error": showNotice(event.message || "Audio capture encountered an error."); break;
        case "warning": showNotice(event.message || "The transcript may be incomplete."); break;
        default: break;
      }
    };
    eventSource.onerror = () => {
      connected = false;
      elements["connection-notice"].hidden = false;
      elements["connection-status"].textContent = "Reconnecting";
      updateControls();
    };
  }

  elements["reconnect-button"].addEventListener("click", () => {
    connected = false;
    elements["connection-status"].textContent = "Reconnecting";
    updateControls();
    connectEvents();
  });

  elements["capture-form"].addEventListener("submit", async (event) => {
    event.preventDefault();
    if (elements["start-button"].disabled || isActive()) return;
    busy = true;
    showNotice("");
    updateControls();
    const payload = {
      sink_id: state.outputs.find((output) => String(output.id) === elements["output-device"].value)?.id
        ?? elements["output-device"].value,
      engine: selectedEngine(),
      isolate: elements["isolate-app"].checked,
    };
    if (payload.isolate) payload.stream_id = Number(elements["playback-app"].value);
    try {
      const result = await request("/api/start", payload);
      applySnapshot(result.state && typeof result.state === "object" ? result.state : result);
    } catch (error) {
      showNotice(error.message);
    } finally {
      busy = false;
      updateControls();
    }
  });

  elements["stop-button"].addEventListener("click", async () => {
    if (elements["stop-button"].disabled) return;
    busy = true;
    updateControls();
    try {
      const result = await request("/api/stop", {});
      applySnapshot(result.state && typeof result.state === "object" ? result.state : result);
    } catch (error) {
      showNotice(error.message);
    } finally {
      busy = false;
      updateControls();
    }
  });

  elements["refresh-devices"].addEventListener("click", async () => {
    if (refreshing || isActive()) return;
    refreshing = true;
    updateControls();
    try {
      updateDevices(await request("/api/devices"));
      announce("Audio outputs and playing apps refreshed.");
    } catch (error) {
      showNotice(error.message);
    } finally {
      refreshing = false;
      updateControls();
    }
  });

  elements["clear-transcript"].addEventListener("click", async () => {
    if (elements["clear-transcript"].disabled || isActive()) return;
    busy = true;
    updateControls();
    try {
      const result = await request("/api/clear", {});
      resetTranscript();
      applySnapshot(result.state && typeof result.state === "object" ? result.state : result);
      announce("Transcript cleared.");
    } catch (error) {
      showNotice(error.message);
    } finally {
      busy = false;
      updateControls();
    }
  });

  function exportText() {
    return orderedSegments().filter((segment) => segment.text?.trim()).map((segment) =>
      `[${formatTime((Number(segment.start_ms) || 0) / 1000)}] ${segment.text}${segment.is_final ? "" : " [provisional]"}`
    ).join("\n\n");
  }

  elements["copy-transcript"].addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(exportText());
      announce("Transcript copied.");
      elements["copy-transcript"].textContent = "Copied";
      window.setTimeout(() => { elements["copy-transcript"].textContent = "Copy"; }, 1600);
    } catch {
      showNotice("Couldn’t copy to the clipboard. Use Download to save the transcript.");
    }
  });

  elements["export-transcript"].addEventListener("click", () => {
    const blob = new Blob([`Call Audio transcript\n\n${exportText()}\n`], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `call-transcript-${new Date().toISOString().slice(0, 19).replaceAll(":", "-")}.txt`;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    announce("Transcript downloaded.");
  });

  elements["transcript-scroll"].addEventListener("scroll", () => {
    const viewport = elements["transcript-scroll"];
    followLatest = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 70;
    elements["jump-latest"].hidden = followLatest || !segments.size;
  }, { passive: true });
  elements["jump-latest"].addEventListener("click", () => {
    followLatest = true;
    elements["transcript-scroll"].scrollTop = elements["transcript-scroll"].scrollHeight;
    elements["jump-latest"].hidden = true;
  });
  [elements["output-device"], elements["playback-app"], elements["isolate-app"], ...engineInputs]
    .forEach((input) => input.addEventListener("change", updateControls));
  window.setInterval(updateElapsed, 250);
  window.addEventListener("pagehide", () => eventSource?.close());
  window.addEventListener("pageshow", (event) => { if (event.persisted) connectEvents(); });

  async function initialize() {
    try {
      applySnapshot(await request("/api/state"));
    } catch (error) {
      showNotice(`Couldn’t load the audio helper: ${error.message}`);
    }
    connectEvents();
  }
  initialize();
})();
