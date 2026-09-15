import { api } from "../api.js";
import { store } from "../store.js";
import { escapeHtml, refreshIcons } from "../utils/dom.js";

export function initStreamHub({ toast, setProjectTab }) {
  let streams = [];
  let models = [];
  let selectedId = null;
  let pollTimer = null;
  let lastCaptured = 0;
  let drawMode = false;
  let pendingPoint = null;
  let line = null;

  const els = {
    list: () => document.getElementById("stream-source-list"),
    img: () => document.getElementById("stream-live-img"),
    canvas: () => document.getElementById("stream-tripwire-canvas"),
    placeholder: () => document.getElementById("stream-live-placeholder"),
    frame: () => document.getElementById("stream-player-frame"),
    fps: () => document.getElementById("stream-fps-label"),
    captured: () => document.getElementById("stream-captured-count"),
    modelSelect: () => document.getElementById("stream-model-select"),
  };

  function selected() {
    return streams.find((s) => s.id === selectedId) || null;
  }

  function stopPoll() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function flashCapture() {
    const frame = els.frame();
    if (!frame) return;
    frame.classList.add("ring-2", "ring-emerald-400");
    setTimeout(() => frame.classList.remove("ring-2", "ring-emerald-400"), 350);
  }

  function syncLiveImage(running) {
    const img = els.img();
    const placeholder = els.placeholder();
    if (!img) return;
    if (running && selectedId) {
      img.src = `${api.streamLiveUrl(selectedId)}?t=${Date.now()}`;
      img.classList.remove("hidden");
      placeholder?.classList.add("hidden");
    } else {
      img.removeAttribute("src");
      img.classList.add("hidden");
      placeholder?.classList.remove("hidden");
    }
  }

  function drawLineOverlay() {
    const canvas = els.canvas();
    const img = els.img();
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const active = line || selected()?.config?.tripwire_line;
    if (!active) return;
    const [x1, y1, x2, y2] = active;
    const p1 = [x1 * canvas.width, y1 * canvas.height];
    const p2 = [x2 * canvas.width, y2 * canvas.height];
    ctx.strokeStyle = "#22d3ee";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(p1[0], p1[1]);
    ctx.lineTo(p2[0], p2[1]);
    ctx.stroke();
    for (const p of [p1, p2]) {
      ctx.fillStyle = "#22d3ee";
      ctx.beginPath();
      ctx.arc(p[0], p[1], 6, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function renderList() {
    const root = els.list();
    if (!root) return;
    if (!streams.length) {
      root.innerHTML = `<p class="text-[11px] text-zinc-500">Нет источников</p>`;
      return;
    }
    root.innerHTML = streams
      .map((s) => {
        const active = s.id === selectedId;
        return `<button type="button" data-stream-id="${s.id}" class="w-full text-left px-2 py-1.5 rounded text-xs border ${
          active ? "border-cyan-600 bg-cyan-950/30 text-white" : "border-zinc-800 text-zinc-300 hover:bg-zinc-800/60"
        }">
          <div class="font-medium truncate">${escapeHtml(s.name)}</div>
          <div class="text-[10px] text-zinc-500 truncate">${escapeHtml(s.source_type)} · ${escapeHtml(s.source_uri)}</div>
        </button>`;
      })
      .join("");
    root.querySelectorAll("[data-stream-id]").forEach((btn) => {
      btn.addEventListener("click", () => {
        selectedId = btn.getAttribute("data-stream-id");
        const s = selected();
        if (s?.config?.tripwire_line) line = s.config.tripwire_line;
        else line = null;
        fillFormFromSelected();
        renderList();
        drawLineOverlay();
        syncLiveImage(Boolean(s?.is_active));
      });
    });
  }

  function fillFormFromSelected() {
    const s = selected();
    const cfg = s?.config || {};
    const modelSelect = els.modelSelect();
    if (modelSelect) {
      modelSelect.innerHTML =
        `<option value="">— модель —</option>` +
        models
          .map(
            (m) =>
              `<option value="${m.id}" ${s?.model_version_id === m.id ? "selected" : ""}>${escapeHtml(
                m.display_name || m.name || m.id
              )}</option>`
          )
          .join("");
    }
    const uncMin = document.getElementById("stream-unc-min");
    const uncMax = document.getElementById("stream-unc-max");
    const timerEn = document.getElementById("stream-timer-enabled");
    const timerIv = document.getElementById("stream-timer-interval");
    const tripEn = document.getElementById("stream-tripwire-enabled");
    const tripDir = document.getElementById("stream-tripwire-direction");
    if (uncMin) uncMin.value = cfg.uncertainty_range?.[0] ?? 0.7;
    if (uncMax) uncMax.value = cfg.uncertainty_range?.[1] ?? 0.9;
    if (timerEn) timerEn.checked = Boolean(cfg.timer_enabled);
    if (timerIv) timerIv.value = cfg.timer_interval_seconds ?? 5;
    if (tripEn) tripEn.checked = Boolean(cfg.tripwire_enabled);
    if (tripDir) tripDir.value = cfg.tripwire_direction || "ANY";
    const captured = els.captured();
    if (captured) captured.textContent = String(s?.captured_frames_count ?? 0);
    lastCaptured = s?.captured_frames_count ?? 0;
  }

  function readConfigPayload() {
    return {
      timer_enabled: document.getElementById("stream-timer-enabled")?.checked || false,
      timer_interval_seconds: Number(document.getElementById("stream-timer-interval")?.value || 5),
      tripwire_enabled: document.getElementById("stream-tripwire-enabled")?.checked || false,
      tripwire_line: line,
      tripwire_classes: [],
      tripwire_direction: document.getElementById("stream-tripwire-direction")?.value || "ANY",
      tripwire_debounce_seconds: 3,
      uncertainty_range: [
        Number(document.getElementById("stream-unc-min")?.value || 0.7),
        Number(document.getElementById("stream-unc-max")?.value || 0.9),
      ],
      cooldown_seconds: 3,
    };
  }

  async function saveTriggers() {
    if (!selectedId) throw new Error("Сначала выберите источник");
    const modelId = els.modelSelect()?.value || null;
    const updated = await api.putStreamTriggers(selectedId, {
      config: readConfigPayload(),
      model_version_id: modelId || null,
    });
    const idx = streams.findIndex((s) => s.id === selectedId);
    if (idx >= 0) streams[idx] = updated;
    fillFormFromSelected();
    toast("Настройки стрима сохранены");
  }

  async function refresh() {
    const projectId = store.get("projectId");
    if (!projectId) return;
    const [streamList, modelList] = await Promise.all([
      api.listStreams(projectId),
      api.listModels(projectId).catch(() => []),
    ]);
    streams = streamList || [];
    models = modelList || [];
    if (!selectedId && streams[0]) selectedId = streams[0].id;
    if (selectedId && !streams.some((s) => s.id === selectedId)) {
      selectedId = streams[0]?.id || null;
    }
    const s = selected();
    if (s?.config?.tripwire_line) line = s.config.tripwire_line;
    renderList();
    fillFormFromSelected();
    drawLineOverlay();
    syncLiveImage(Boolean(s?.is_active));
    refreshIcons();
  }

  async function pollStatus() {
    if (!selectedId) return;
    try {
      const st = await api.getStreamStatus(selectedId);
      if (els.fps()) els.fps().textContent = `FPS: ${Number(st.fps || 0).toFixed(1)}`;
      if (els.captured()) els.captured().textContent = String(st.captured_count ?? 0);
      if ((st.captured_count || 0) > lastCaptured) {
        flashCapture();
        lastCaptured = st.captured_count || 0;
      }
      syncLiveImage(Boolean(st.is_running));
    } catch {
      /* ignore transient */
    }
  }

  document.getElementById("btn-stream-add-rtsp")?.addEventListener("click", async () => {
    try {
      const projectId = store.get("projectId");
      const name = document.getElementById("stream-rtsp-name")?.value?.trim() || "RTSP";
      const rtsp_url = document.getElementById("stream-rtsp-url")?.value?.trim();
      if (!rtsp_url) throw new Error("Укажите RTSP URL");
      const created = await api.createRtspStream(projectId, { name, rtsp_url });
      selectedId = created.id;
      await refresh();
    } catch (err) {
      toast(err.message);
    }
  });

  document.getElementById("btn-stream-add-device")?.addEventListener("click", async () => {
    try {
      const projectId = store.get("projectId");
      const device_index = Number(document.getElementById("stream-device-index")?.value || 0);
      const created = await api.createDeviceStream(projectId, {
        name: `Device ${device_index}`,
        device_index,
      });
      selectedId = created.id;
      await refresh();
    } catch (err) {
      toast(err.message);
    }
  });

  document.getElementById("stream-video-input")?.addEventListener("change", async (ev) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    try {
      const projectId = store.get("projectId");
      const created = await api.uploadStreamVideo(projectId, file, file.name);
      selectedId = created.id;
      await refresh();
    } catch (err) {
      toast(err.message);
    } finally {
      ev.target.value = "";
    }
  });

  document.getElementById("btn-stream-save-triggers")?.addEventListener("click", async () => {
    try {
      await saveTriggers();
    } catch (err) {
      toast(err.message);
    }
  });

  document.getElementById("btn-stream-start")?.addEventListener("click", async () => {
    try {
      if (!selectedId) throw new Error("Выберите источник");
      await saveTriggers();
      await api.startStream(selectedId);
      await refresh();
      stopPoll();
      pollTimer = setInterval(pollStatus, 1000);
      toast("Стрим запущен");
    } catch (err) {
      toast(err.message);
    }
  });

  document.getElementById("btn-stream-stop")?.addEventListener("click", async () => {
    try {
      if (!selectedId) return;
      await api.stopStream(selectedId);
      stopPoll();
      await refresh();
      toast("Стрим остановлен");
    } catch (err) {
      toast(err.message);
    }
  });

  document.getElementById("btn-stream-draw-line")?.addEventListener("click", () => {
    drawMode = true;
    pendingPoint = null;
    toast("Кликните точку A, затем точку B на видео");
  });

  document.getElementById("btn-stream-goto-review")?.addEventListener("click", () => {
    setProjectTab("annotate").catch(() => {});
  });

  els.canvas()?.addEventListener("click", (ev) => {
    if (!drawMode) return;
    const canvas = els.canvas();
    const rect = canvas.getBoundingClientRect();
    const x = (ev.clientX - rect.left) / rect.width;
    const y = (ev.clientY - rect.top) / rect.height;
    if (!pendingPoint) {
      pendingPoint = [x, y];
      return;
    }
    line = [pendingPoint[0], pendingPoint[1], x, y];
    pendingPoint = null;
    drawMode = false;
    drawLineOverlay();
    const trip = document.getElementById("stream-tripwire-enabled");
    if (trip) trip.checked = true;
    saveTriggers().catch((err) => toast(err.message));
  });

  window.addEventListener("resize", () => drawLineOverlay());

  return {
    refresh,
    destroy() {
      stopPoll();
    },
  };
}
