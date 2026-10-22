import { api } from "../api.js?v=collection-center-20261022c";
import { store } from "../store.js";
import { escapeHtml, refreshIcons } from "../utils/dom.js";
import { firstReviewImage } from "../utils/activeLearning.js";

export function initStreamHub({ toast, navigate, projectPath }) {
  let streams = [];
  let projects = [];
  let models = [];
  let classes = [];
  const statuses = new Map();
  let selectedId = null;
  let pollTimer = null;
  let pollInFlight = false;
  let lastCaptured = 0;
  let liveBoundId = null;
  let drawMode = false;
  let pendingPoint = null;
  let line = null;
  let dragEndpoint = null;
  let saveTimer = null;
  const ui = { page: "overview", query: "", project: "", state: "all", cameraPage: 1, wizardSourcePage: 1, modelPage: 1, wizardStep: 0, selectedCameras: new Set(), collectionName: "", mode: "stable", timerSeconds: 5, confidence: 0.25, maxConfidence: 1, minFrames: 12, sizeVariation: 0.35, cooldown: 5, modelByProject: new Map(), classByProject: new Map(), classIds: new Set(), modelQuery: "", diagnostic: false };
  let refreshTimer = null;

  const els = {
    list: () => document.getElementById("stream-source-list"),
    img: () => document.getElementById(ui.page === "detail" ? "stream-detail-live" : "stream-live-img"),
    canvas: () => document.getElementById(ui.page === "detail" ? "stream-detail-canvas" : "stream-tripwire-canvas"),
    placeholder: () => document.getElementById("stream-live-placeholder"),
    frame: () => document.getElementById("stream-player-frame"),
    fps: () => document.getElementById("stream-fps-label"),
    captured: () => document.getElementById("stream-captured-count"),
    modelSelect: () => document.getElementById("stream-model-select"),
    captureMode: () => document.getElementById("stream-capture-mode"),
    timerSettings: () => document.getElementById("stream-timer-settings"),
  };

  function selected() {
    return streams.find((s) => s.id === selectedId) || null;
  }

  function selectedProject() {
    return projects.find((project) => project.id === selected()?.project_id) || null;
  }

  function destinationProjectId() {
    return document.getElementById("stream-destination-project")?.value || currentProjectId();
  }

  function stopPoll() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function ensurePoll(running) {
    if (running) {
      if (!pollTimer) pollTimer = setInterval(pollStatus, 2500);
    } else {
      stopPoll();
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
    const center = document.getElementById("view-stream-center");
    const centerVisible = center && !center.classList.contains("hidden");
    if (ui.page === "detail") {
      if (!centerVisible && img.hasAttribute("src")) img.removeAttribute("src");
      return;
    }
    if (centerVisible) {
      const legacyImage = document.getElementById("stream-live-img");
      if (legacyImage?.hasAttribute("src")) legacyImage.removeAttribute("src");
      liveBoundId = null;
      return;
    }
    if (running && selectedId) {
      if (liveBoundId !== selectedId) {
        img.src = api.streamLiveUrl(selectedId);
        liveBoundId = selectedId;
      }
      img.classList.remove("hidden");
      placeholder?.classList.add("hidden");
    } else if (liveBoundId !== null) {
      img.removeAttribute("src");
      liveBoundId = null;
      img.classList.add("hidden");
      placeholder?.classList.remove("hidden");
    } else {
      img.classList.add("hidden");
      placeholder?.classList.remove("hidden");
    }
  }

  function contentRect(canvas, img) {
    const cw = canvas.width;
    const ch = canvas.height;
    const iw = img?.naturalWidth || 0;
    const ih = img?.naturalHeight || 0;
    if (!iw || !ih || img.classList.contains("hidden")) {
      return { x: 0, y: 0, w: cw, h: ch };
    }
    const scale = Math.min(cw / iw, ch / ih);
    const w = iw * scale;
    const h = ih * scale;
    return { x: (cw - w) / 2, y: (ch - h) / 2, w, h };
  }

  function normFromClient(ev) {
    const canvas = els.canvas();
    const img = els.img();
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
    const content = contentRect(canvas, img);
    const px = ev.clientX - rect.left;
    const py = ev.clientY - rect.top;
    const x = (px - content.x) / content.w;
    const y = (py - content.y) / content.h;
    return [
      Math.min(1, Math.max(0, x)),
      Math.min(1, Math.max(0, y)),
    ];
  }

  function endpointHits(ev) {
    if (!line) return null;
    const canvas = els.canvas();
    const img = els.img();
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
    const content = contentRect(canvas, img);
    const px = ev.clientX - rect.left;
    const py = ev.clientY - rect.top;
    const pts = [
      [content.x + line[0] * content.w, content.y + line[1] * content.h],
      [content.x + line[2] * content.w, content.y + line[3] * content.h],
    ];
    for (let i = 0; i < pts.length; i += 1) {
      const dx = pts[i][0] - px;
      const dy = pts[i][1] - py;
      if (dx * dx + dy * dy <= 100) return i;
    }
    return null;
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
    const active = line;
    const content = contentRect(canvas, img);
    if (active) {
      const [x1, y1, x2, y2] = active;
      const p1 = [content.x + x1 * content.w, content.y + y1 * content.h];
      const p2 = [content.x + x2 * content.w, content.y + y2 * content.h];
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
    if (pendingPoint) {
      ctx.fillStyle = "#fbbf24";
      ctx.beginPath();
      ctx.arc(content.x + pendingPoint[0] * content.w, content.y + pendingPoint[1] * content.h, 7, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function renderList() {
    const root = els.list();
    if (!root) return;
    if (!streams.length) {
      root.innerHTML = `<div class="col-span-full rounded-xl border border-dashed border-zinc-800 p-5 text-center text-xs text-zinc-500">Источников пока нет. Выберите проект назначения выше и добавьте камеру, видео или папку.</div>`;
      return;
    }
    root.innerHTML = streams
      .map((s) => {
        const active = s.id === selectedId;
        const status = statuses.get(s.id);
        const running = Boolean(s.is_active || status?.is_running);
        const state = status?.state || (running ? "running" : "stopped");
        const label = state === "running" ? "Собирает" : state === "starting" ? "Подключение" : state === "reconnecting" ? "Переподключение" : state === "error" ? "Ошибка" : "Остановлен";
        const project = projects.find((item) => item.id === s.project_id);
        const type = ({ RTSP: "RTSP камера", DEVICE: "Веб-камера", VIDEO_FILE: "Видеофайл", IMAGE_FOLDER: "Папка изображений" })[s.source_type] || s.source_type;
        return `<article class="rounded-xl border ${active ? "border-cyan-700 bg-cyan-950/20" : "border-zinc-800 bg-zinc-900/70"} p-3">
          <button type="button" data-stream-id="${s.id}" class="w-full text-left">
            <div class="flex items-center justify-between gap-2"><span class="font-medium text-sm text-zinc-100 truncate">${escapeHtml(s.name)}</span><span class="text-[10px] rounded-full px-2 py-1 ${running ? "bg-emerald-950 text-emerald-300" : state === "error" ? "bg-rose-950 text-rose-300" : "bg-zinc-800 text-zinc-400"}">${escapeHtml(label)}</span></div>
            <div class="text-[11px] text-indigo-300 mt-1 truncate">${escapeHtml(project?.name || "Проект удалён")}</div>
            <div class="text-[10px] text-zinc-500 mt-1 truncate">${escapeHtml(type)} · ${escapeHtml(s.config?.timer_enabled ? `каждые ${s.config.timer_interval_seconds} с` : "по событиям модели")} · ${Number(status?.captured_count ?? s.captured_frames_count ?? 0)} кадров</div>
            ${status?.error_message ? `<div class="text-[10px] text-rose-300 mt-1 truncate" title="${escapeHtml(status.error_message)}">${escapeHtml(status.error_message)}</div>` : ""}
          </button>
          <div class="flex items-center gap-2 mt-3">
            <button type="button" data-${running ? "stop" : "start"}-stream="${s.id}" class="px-3 py-1.5 rounded-lg text-xs ${running ? "border border-zinc-700 text-zinc-200 hover:bg-zinc-800" : "bg-emerald-700 text-white hover:bg-emerald-600"}">${running ? "Остановить сбор" : "Начать сбор"}</button>
            <span class="text-[10px] text-zinc-500">${status?.fps ? `${Number(status.fps).toFixed(1)} кадр/с` : ""}</span>
            <button type="button" data-delete-stream="${s.id}" class="ml-auto text-[10px] text-zinc-500 hover:text-rose-300" title="Удалить источник" ${running ? "disabled" : ""}>Удалить</button>
          </div>
        </article>`;
      })
      .join("");
    root.querySelectorAll("[data-stream-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        selectedId = btn.getAttribute("data-stream-id");
        const s = selected();
        line = s?.config?.tripwire_line || null;
        await loadSelectedProject();
        fillFormFromSelected();
        renderList();
        drawLineOverlay();
        syncLiveImage(Boolean(s?.is_active || statuses.get(s?.id)?.is_running));
        ensurePoll(streams.some((item) => item.is_active || statuses.get(item.id)?.is_running));
      });
    });
    root.querySelectorAll("[data-start-stream]").forEach((btn) => btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const id = btn.getAttribute("data-start-stream");
      try {
        if (id === selectedId) await saveTriggers({ quiet: true });
        await api.startStream(id);
        await refresh();
        toast("Сбор запущен");
      }
      catch (err) { toast(err.message); }
    }));
    root.querySelectorAll("[data-stop-stream]").forEach((btn) => btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const id = btn.getAttribute("data-stop-stream");
      try { await api.stopStream(id); await refresh(); toast("Сбор остановлен"); }
      catch (err) { toast(err.message); }
    }));
    root.querySelectorAll("[data-delete-stream]").forEach((btn) => {
      btn.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        const id = btn.getAttribute("data-delete-stream");
        try {
          await api.deleteStream(id);
          if (selectedId === id) selectedId = null;
          await refresh();
          toast("Источник удалён");
        } catch (err) {
          toast(err.message);
        }
      });
    });
  }

  function fillFormFromSelected() {
    const s = selected();
    const cfg = s?.config || {};
    const isRunning = Boolean(s?.is_active || statuses.get(s?.id)?.is_running);
    const startButton = document.getElementById("btn-stream-start");
    const stopButton = document.getElementById("btn-stream-stop");
    if (startButton) {
      startButton.textContent = isRunning ? "Сбор идёт" : "Начать сбор";
      startButton.disabled = isRunning || !s;
    }
    if (stopButton) stopButton.disabled = !isRunning || !s;
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
    const trackEn = document.getElementById("stream-track-stable-enabled");
    const trackN = document.getElementById("stream-track-stable-n");
    const trackSize = document.getElementById("stream-track-stable-size");
    const trackIv = document.getElementById("stream-track-stable-interval");
    const timerIv = document.getElementById("stream-timer-interval");
    const tripEn = document.getElementById("stream-tripwire-enabled");
    const tripDir = document.getElementById("stream-tripwire-direction");
    
    if (cfg.tripwire_enabled) {
      if (tripEn) tripEn.checked = true;
    } else {
      if (trackEn) trackEn.checked = true;
    }
    
    if (trackN) trackN.value = cfg.track_stable_min_frames ?? 12;
    if (trackSize) trackSize.value = cfg.track_stable_max_size_variation ?? 0.35;
    if (trackIv) trackIv.value = cfg.track_stable_interval_seconds ?? 5;
    if (timerIv) timerIv.value = cfg.timer_interval_seconds ?? 5;
    
    const confMin = document.getElementById("stream-conf-min");
    const confMax = document.getElementById("stream-conf-max");
    const minLabel = document.getElementById("stream-conf-min-label");
    const maxLabel = document.getElementById("stream-conf-max-label");
    
    if (confMin) {
      confMin.value = cfg.confidence_min ?? 0.25;
      if (minLabel) minLabel.textContent = Math.round(confMin.value * 100);
    }
    if (confMax) {
      confMax.value = cfg.confidence_max ?? 1;
      if (maxLabel) maxLabel.textContent = Math.round(confMax.value * 100);
    }
    
    if (tripDir) tripDir.value = cfg.tripwire_direction || "ANY";
    if (els.captureMode()) {
      els.captureMode().value = cfg.timer_enabled ? "TIMER" : "AI";
    }
    syncCaptureMode();
    renderClassChecks();
    const captured = els.captured();
    if (captured) captured.textContent = String(s?.captured_frames_count ?? 0);
    lastCaptured = s?.captured_frames_count ?? 0;
  }

  function isImageFolder() {
    return selected()?.source_type === "IMAGE_FOLDER";
  }

  function syncCaptureMode() {
    const timer = els.captureMode()?.value === "TIMER";
    const folder = isImageFolder();
    
    els.timerSettings()?.classList.toggle("hidden", !timer);
    
    const aiSettings = document.getElementById("stream-ai-settings");
    if (aiSettings) aiSettings.classList.toggle("hidden", timer);

    document.getElementById("stream-folder-capture-note")?.classList.toggle("hidden", timer || !folder);

    const isStable = document.getElementById("stream-track-stable-enabled")?.checked;
    const isLine = document.getElementById("stream-tripwire-enabled")?.checked;
    
    document.getElementById("stream-trigger-stable-params")?.classList.toggle("hidden", !isStable || folder);
    document.getElementById("stream-trigger-line-params")?.classList.toggle("hidden", !isLine || folder);

    const model = els.modelSelect();
    if (model) {
      model.disabled = timer;
      model.classList.toggle("opacity-50", timer);
    }
    const goto = document.getElementById("btn-stream-goto-review");
    if (goto) {
      goto.textContent = timer
        ? "Перейти к неразмеченным в Студию →"
        : "Перейти к верификации в Студию →";
    }
  }

  function readConfigPayload() {
    const classBoxes = [
      ...document.querySelectorAll("#stream-tripwire-classes input[type=checkbox]:checked"),
    ];
    const s = selected();
    const timerEnabled = els.captureMode()?.value === "TIMER";
    const triggerRadio = document.querySelector('input[name="stream_trigger"]:checked')?.value;
    const isStable = triggerRadio === "stable";
    const isLine = triggerRadio === "line";
    
    return {
      track_stable_enabled:
        !isImageFolder() && isStable,
      track_stable_min_frames: Number(
        document.getElementById("stream-track-stable-n")?.value || 12
      ),
      track_stable_max_size_variation: Number(
        document.getElementById("stream-track-stable-size")?.value || 0.35
      ),
      track_stable_interval_seconds: Number(
        document.getElementById("stream-track-stable-interval")?.value || 5
      ),
      confidence_min: Number(document.getElementById("stream-conf-min")?.value ?? 0.25),
      confidence_max: Number(document.getElementById("stream-conf-max")?.value ?? 1),
      timer_enabled: timerEnabled,
      timer_interval_seconds: Number(
        document.getElementById("stream-timer-interval")?.value || 5
      ),
      tripwire_enabled:
        !isImageFolder() && isLine,
      tripwire_line: line,
      tripwire_classes: classBoxes.map((el) => el.value),
      tripwire_direction: document.getElementById("stream-tripwire-direction")?.value || "ANY",
      tripwire_debounce_seconds: Number(s?.config?.tripwire_debounce_seconds ?? 3),
      cooldown_seconds: Number(s?.config?.cooldown_seconds ?? 3),
    };
  }

  function renderClassChecks() {
    const root = document.getElementById("stream-tripwire-classes");
    if (!root) return;
    const checkedClasses = new Set(selected()?.config?.tripwire_classes || []);
    if (!classes.length) {
      root.innerHTML = `<p class="text-[10px] text-zinc-600">Нет классов проекта</p>`;
      return;
    }
    root.innerHTML = classes
      .map(
        (c) => `<label class="flex items-center gap-1.5 text-[11px] text-zinc-300">
          <input type="checkbox" value="${c.id}" ${checkedClasses.has(c.id) ? "checked" : ""} class="rounded border-zinc-600" />
          ${escapeHtml(c.name)}
        </label>`
      )
      .join("");
    root.querySelectorAll("input").forEach((el) => {
      el.addEventListener("change", scheduleSaveTriggers);
    });
  }

  async function saveTriggers({ quiet = false } = {}) {
    if (!selectedId) throw new Error("Сначала выберите источник");
    const modelId =
      els.captureMode()?.value === "TIMER" ? null : els.modelSelect()?.value || null;
    const updated = await api.putStreamTriggers(selectedId, {
      config: readConfigPayload(),
      model_version_id: modelId || null,
    });
    const idx = streams.findIndex((s) => s.id === selectedId);
    if (idx >= 0) streams[idx] = updated;
    fillFormFromSelected();
    line = updated.config?.tripwire_line || null;
    if (ui.page === "detail") {
      refreshDetailStatus();
      drawLineOverlay();
    } else {
      await loadCatalogs();
      renderCenter();
    }
    if (!quiet) toast("Настройки стрима сохранены");
  }

  function scheduleSaveTriggers() {
    if (!selectedId) return;
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      saveTriggers({ quiet: true }).catch((err) => toast(err.message));
    }, 400);
  }

  function currentProjectId() {
    return store.get("currentProject")?.id || null;
  }

  function escapeAttribute(value) { return escapeHtml(value).replace(/`/g, "&#96;"); }

  function configSummary(stream) {
    const cfg = stream.config || {};
    if (cfg.timer_enabled) return `Каждые ${Number(cfg.timer_interval_seconds || 5)} с · без модели`;
    if (cfg.tripwire_enabled) return "Пересечение линии";
    return `Стабильный объект · ${Number(cfg.track_stable_min_frames || 12)} кадров`;
  }

  function stateFor(stream) {
    const status = statuses.get(stream.id);
    if (status?.state) return status.state;
    return stream.is_active ? "running" : "stopped";
  }

  function stateLabel(state) {
    return ({ running: "Собирает", starting: "Подключается", reconnecting: "Переподключение", error: "Нет сигнала", stopped: "Остановлен" })[state] || state;
  }

  function badgeClass(state) {
    return state === "running" ? "border-emerald-800 bg-emerald-950/50 text-emerald-300" : state === "error" ? "border-rose-800 bg-rose-950/50 text-rose-300" : state === "starting" || state === "reconnecting" ? "border-amber-800 bg-amber-950/50 text-amber-200" : "border-zinc-700 bg-zinc-900 text-zinc-400";
  }

  function projectOptions(selected = "", all = false) {
    return `${all ? '<option value="">Все проекты</option>' : ""}${projects.map((project) => `<option value="${escapeAttribute(project.id)}" ${project.id === selected ? "selected" : ""}>${escapeHtml(project.name)}</option>`).join("")}`;
  }

  function allModels() {
    return [...ui.modelByProject.entries()].flatMap(([projectId, items]) => items.map((model) => ({ ...model, project_id: projectId })));
  }

  function modelById(id) { return allModels().find((model) => model.id === id) || null; }

  function allClasses(projectId) { return ui.classByProject.get(projectId) || []; }

  function setPage(page) {
    ui.page = page;
    ui.query = "";
    ui.project = "";
    ui.state = "all";
    renderCenter();
  }

  function renderCenter() {
    const host = document.getElementById("stream-center-content");
    if (!host) return;
    document.querySelectorAll(".collection-nav").forEach((button) => {
      const active = button.dataset.collectionPage === ui.page;
      button.classList.toggle("bg-indigo-600/15", active);
      button.classList.toggle("text-indigo-200", active);
      button.classList.toggle("text-zinc-400", !active);
    });
    const activeCount = streams.filter((stream) => ["running", "starting", "reconnecting"].includes(stateFor(stream))).length;
    const cameraCount = document.getElementById("collection-camera-count");
    const modelCount = document.getElementById("collection-model-count");
    const navCount = document.getElementById("collection-nav-count");
    if (cameraCount) cameraCount.textContent = String(streams.length);
    if (modelCount) modelCount.textContent = String(allModels().length);
    if (navCount) navCount.textContent = String(activeCount);
    if (ui.page === "new") renderWizard();
    else if (ui.page === "cameras") renderCameras();
    else if (ui.page === "models") renderModels();
    else if (ui.page === "detail") renderDetail();
    else renderOverview();
  }

  function renderOverview() {
    const host = document.getElementById("stream-center-content");
    const active = streams.filter((stream) => ["running", "starting", "reconnecting"].includes(stateFor(stream)));
    const attention = streams.filter((stream) => stateFor(stream) === "error");
    const saved = streams.reduce((sum, stream) => sum + Number(statuses.get(stream.id)?.captured_count ?? stream.captured_frames_count ?? 0), 0);
    const projectsUsed = new Set(active.map((stream) => stream.project_id)).size;
    host.innerHTML = `<div class="p-5 md:p-7 max-w-[1600px] mx-auto space-y-5">
      <div class="flex flex-wrap items-start justify-between gap-3"><div><div class="text-[11px] text-zinc-500">РАБОЧЕЕ ПРОСТРАНСТВО / ЦЕНТР СБОРА</div><h1 class="text-2xl font-semibold mt-1">Обзор сборов</h1><p id="stream-summary" class="text-sm text-zinc-400 mt-1">Состояние источников, обработки и записи по всем проектам.</p></div><button data-center-new class="rounded-lg bg-indigo-600 hover:bg-indigo-500 px-4 py-2.5 text-sm font-medium">＋ Новый сбор</button></div>
      <div class="grid grid-cols-2 xl:grid-cols-4 gap-3">
        <div class="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4"><div class="text-xs text-zinc-500">Работают сейчас</div><div class="text-2xl font-semibold text-emerald-300 mt-1">${active.length}<span class="text-xs text-zinc-500 ml-2 font-normal">сборов / ${new Set(active.map((stream) => stream.id)).size} камер</span></div><div class="text-[11px] text-zinc-500 mt-1">В ${projectsUsed} проектах</div></div>
        <div class="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4"><div class="text-xs text-zinc-500">Сохранено всего</div><div class="text-2xl font-semibold mt-1">${saved.toLocaleString("ru-RU")}<span class="text-xs text-zinc-500 ml-2 font-normal">кадров</span></div><div class="text-[11px] text-zinc-500 mt-1">Сумма по доступной истории источников</div></div>
        <div class="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4"><div class="text-xs text-zinc-500">Требуют внимания</div><div class="text-2xl font-semibold ${attention.length ? "text-rose-300" : "text-emerald-300"} mt-1">${attention.length}<span class="text-xs text-zinc-500 ml-2 font-normal">ошибок подключения</span></div><div class="text-[11px] text-zinc-500 mt-1">Ошибки не останавливают соседние сборы</div></div>
        <div class="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4"><div class="text-xs text-zinc-500">Доступные ресурсы</div><div class="text-2xl font-semibold mt-1">${projects.length}<span class="text-xs text-zinc-500 ml-2 font-normal">проектов</span></div><div class="text-[11px] text-zinc-500 mt-1">${streams.length} источников · ${allModels().length} моделей</div></div>
      </div>
      <div class="flex flex-wrap gap-2 items-center"><input id="center-search" type="search" placeholder="Найти сбор, камеру или проект…" value="${escapeAttribute(ui.query)}" class="w-full sm:w-72 bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-xs"><select id="center-project-filter" class="bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-xs">${projectOptions(ui.project, true)}</select><div class="flex flex-wrap gap-1">${[["all","Все"],["running","Работают"],["error","Ошибка"],["stopped","Остановлены"]].map(([key,label]) => `<button data-center-state="${key}" class="px-2.5 py-1.5 rounded-md text-xs border ${ui.state === key ? "border-indigo-500/50 bg-indigo-950/50 text-indigo-200" : "border-zinc-800 text-zinc-400 hover:bg-zinc-900"}">${label}${key === "all" ? ` ${streams.length}` : key === "running" ? ` ${active.length}` : key === "error" ? ` ${attention.length}` : ""}</button>`).join("")}</div>
      <div class="rounded-xl border border-zinc-800 overflow-hidden bg-zinc-900/40"><div class="overflow-x-auto"><table class="w-full text-left text-xs"><thead class="bg-zinc-900 text-zinc-500 uppercase text-[10px]"><tr><th class="px-4 py-3">Сбор · проект назначения</th><th class="px-4 py-3">Камера · модель</th><th class="px-4 py-3">Состояние</th><th class="px-4 py-3">Настроено</th><th class="px-4 py-3">Сохранено</th><th class="px-4 py-3">Управление</th></tr></thead><tbody id="center-jobs"></tbody></table></div><div id="center-empty" class="hidden p-12 text-center text-sm text-zinc-500">Сборы не найдены. Добавьте источник или создайте первый сбор.</div></div>
      <p class="text-[11px] text-zinc-600">«Кадры сохранены» показывают накопленное число для источника; источник можно использовать повторно в нескольких запусках.</p>
    </div>`;
    const filtered = streams.filter((stream) => {
      const query = ui.query.trim().toLowerCase();
      const project = projects.find((item) => item.id === stream.project_id);
      const matchQuery = !query || `${stream.name} ${project?.name || ""} ${stream.source_type || ""}`.toLowerCase().includes(query);
      const matchProject = !ui.project || stream.project_id === ui.project;
      const state = stateFor(stream);
      const matchState = ui.state === "all" || ui.state === "running" && ["running", "starting", "reconnecting"].includes(state) || state === ui.state;
      return matchQuery && matchProject && matchState;
    });
    const body = host.querySelector("#center-jobs");
    body.innerHTML = filtered.map((stream) => {
      const project = projects.find((item) => item.id === stream.project_id);
      const model = modelById(stream.model_version_id);
      const status = statuses.get(stream.id);
      const state = stateFor(stream);
      const running = stream.is_active || status?.is_running;
      const isTimer = stream.config?.timer_enabled;
      const modelName = isTimer ? "Без модели · таймер" : model?.display_name || model?.name || (stream.model_version_id ? "Модель" : "Модель не выбрана");
      const error = status?.error_message;
      return `<tr class="border-t border-zinc-800 hover:bg-zinc-800/30"><td class="px-4 py-3"><button data-center-detail="${stream.id}" class="text-left font-medium text-zinc-100 hover:text-indigo-300">${escapeHtml(stream.name)}</button><div class="text-[11px] text-indigo-300 mt-1">${escapeHtml(project?.name || "Проект удалён")}</div></td><td class="px-4 py-3"><div>${escapeHtml(stream.name)}</div><div class="text-[11px] text-zinc-500 mt-1">${escapeHtml(modelName)}</div></td><td class="px-4 py-3"><span class="inline-flex border rounded-full px-2 py-1 text-[10px] ${badgeClass(state)}">● ${escapeHtml(stateLabel(state))}</span>${error ? `<div class="max-w-40 truncate text-[10px] text-rose-300 mt-1" title="${escapeAttribute(error)}">${escapeHtml(error)}</div>` : ""}<div class="text-[10px] text-zinc-500 mt-1">${running && status?.fps ? `${Number(status.fps).toFixed(1)} FPS` : running ? "Источник подключён" : ""}</div></td><td class="px-4 py-3 text-zinc-300">${escapeHtml(configSummary(stream))}</td><td class="px-4 py-3"><span class="font-mono">${Number(status?.captured_count ?? stream.captured_frames_count ?? 0).toLocaleString("ru-RU")}</span><div class="text-[10px] text-zinc-500 mt-1">кадров</div></td><td class="px-4 py-3"><div class="flex gap-1.5">${running ? `<button data-hub-stop="${stream.id}" class="rounded-md border border-zinc-700 px-2 py-1.5 hover:bg-zinc-800">Стоп</button>` : `<button data-hub-start="${stream.id}" class="rounded-md bg-emerald-700 px-2 py-1.5 text-white hover:bg-emerald-600">Запустить</button>`}<button data-center-detail="${stream.id}" class="rounded-md border border-zinc-700 px-2 py-1.5 hover:bg-zinc-800">Условия</button></div></td></tr>`;
    }).join("");
    host.querySelector("#center-empty").classList.toggle("hidden", filtered.length > 0);
    bindOverviewEvents(host);
  }

  function bindOverviewEvents(host) {
    host.querySelector("#center-search")?.addEventListener("input", (event) => { ui.query = event.target.value; renderOverview(); const input = document.getElementById("center-search"); input?.focus(); input?.setSelectionRange(ui.query.length, ui.query.length); });
    host.querySelector("#center-project-filter")?.addEventListener("change", (event) => { ui.project = event.target.value; renderOverview(); });
    host.querySelectorAll("[data-center-state]").forEach((button) => button.addEventListener("click", () => { ui.state = button.dataset.centerState; renderOverview(); }));
    host.querySelectorAll("[data-center-new]").forEach((button) => button.addEventListener("click", () => { ui.page = "new"; ui.wizardStep = 0; renderCenter(); }));
    host.querySelectorAll("[data-center-detail]").forEach((button) => button.addEventListener("click", () => { selectedId = button.dataset.centerDetail; ui.page = "detail"; renderCenter(); }));
    host.querySelectorAll("[data-hub-start]").forEach((button) => button.addEventListener("click", () => runStreamAction(button, true)));
    host.querySelectorAll("[data-hub-stop]").forEach((button) => button.addEventListener("click", () => runStreamAction(button, false)));
  }

  async function runStreamAction(button, start) {
    const id = button.getAttribute(start ? "data-hub-start" : "data-hub-stop") || selectedId;
    button.disabled = true;
    try {
      if (start) {
        const stream = streams.find((item) => item.id === id);
        if (!stream) return;
        if (!stream.config?.timer_enabled && !stream.model_version_id) throw new Error("Выберите модель для этого проекта перед запуском.");
        if (selectedId === id) await saveTriggers({ quiet: true });
        await api.startStream(id);
        toast("Сбор запущен");
      } else {
        await api.stopStream(id);
        toast("Сбор остановлен");
      }
      await refresh();
    } catch (error) { toast(error.message || String(error)); button.disabled = false; }
  }

  async function loadCatalogs() {
    const results = await Promise.all(projects.map(async (project) => {
      const [models, classes] = await Promise.all([api.listModels(project.id).catch(() => []), api.listClasses(project.id).catch(() => [])]);
      return [project.id, models || [], classes || []];
    }));
    ui.modelByProject = new Map(results.map(([id, models]) => [id, models]));
    ui.classByProject = new Map(results.map(([id, , classes]) => [id, classes]));
  }

  function modeText() {
    if (ui.mode === "timer") return `Сохранять один кадр с каждой камеры каждые ${Number(ui.timerSeconds)} секунд.`;
    if (ui.mode === "line") return `Сохранять кадр, когда объект выбранного класса пересекает линию. Минимальная уверенность ${Math.round(Number(ui.confidence) * 100)}%.`;
    return `Сохранять лучший кадр после ${Number(ui.minFrames)} последовательных кадров объекта. Минимальная уверенность ${Math.round(Number(ui.confidence) * 100)}%.`;
  }

  function setWizardStep(step) {
    ui.wizardStep = Math.max(0, Math.min(3, step));
    renderWizard();
  }

  function wizardSourceRows() {
    const query = ui.query.trim().toLowerCase();
    return streams.filter((stream) => {
      const project = projects.find((item) => item.id === stream.project_id);
      const matchesText = !query || `${stream.name} ${project?.name || ""} ${stream.source_type}`.toLowerCase().includes(query);
      const state = stateFor(stream);
      return matchesText && state !== "error";
    });
  }

  function updateWizardSummary() {
    const root = document.getElementById("wizard-summary");
    if (!root) return;
    const cameraNames = [...ui.selectedCameras].map((id) => streams.find((stream) => stream.id === id)?.name).filter(Boolean);
    const project = projects.find((item) => item.id === ui.project);
    const model = modelById(ui.modelByProject.get(ui.project)?.find((item) => item.id === ui.selectedModel)?.id);
    root.innerHTML = `<div class="divide-y divide-zinc-800"><div class="py-3 flex justify-between gap-3"><span class="text-zinc-500">Источники</span><strong class="text-right">${ui.selectedCameras.size} выбрано</strong></div><div class="py-3 flex justify-between gap-3"><span class="text-zinc-500">Куда сохранять</span><strong class="text-right">${escapeHtml(project?.name || "Не выбран")}</strong></div><div class="py-3 flex justify-between gap-3"><span class="text-zinc-500">Модель</span><strong class="text-right">${ui.mode === "timer" ? "Не требуется" : escapeHtml(model?.display_name || model?.name || "Не выбрана")}</strong></div></div><div class="mt-3 rounded-lg border border-indigo-900 bg-indigo-950/40 p-3"><div class="text-[10px] uppercase tracking-wider text-indigo-300 mb-2">Правило простыми словами</div><p class="text-xs leading-5 text-zinc-200">${escapeHtml(modeText())}</p></div><div class="mt-3 text-[11px] leading-5 text-zinc-500">Будет создано ${ui.selectedCameras.size} независимых сборов. Кадры сохраняются в выбранный проект назначения.</div>${ui.selectedCameras.size > 1 ? `<div class="mt-2 text-[10px] text-zinc-600 break-words">${cameraNames.map(escapeHtml).join(" · ")}</div>` : ""}`;
  }

  function renderWizard() {
    const host = document.getElementById("stream-center-content");
    const stepNames = ["Камеры", "Проект и сценарий", "Условия и модель", "Проверка и запуск"];
    const content = ui.wizardStep === 0 ? renderWizardCameras() : ui.wizardStep === 1 ? renderWizardProject() : ui.wizardStep === 2 ? renderWizardConditions() : renderWizardCheck();
    host.innerHTML = `<div class="p-5 md:p-7 max-w-[1400px] mx-auto space-y-5"><div class="flex flex-wrap items-start justify-between gap-3"><div><button data-wizard-cancel class="text-xs text-zinc-500 hover:text-white">← К обзору сборов</button><h1 class="text-2xl font-semibold mt-2">Новый сбор</h1><p class="text-sm text-zinc-400 mt-1">Камеры → проект и сценарий → условия и модель → проверка.</p></div></div><div class="grid grid-cols-2 xl:grid-cols-4 gap-2">${stepNames.map((name, index) => `<button data-wizard-step="${index}" class="rounded-lg border px-3 py-2 text-left text-xs ${index === ui.wizardStep ? "border-indigo-500 bg-indigo-950/30 text-indigo-200" : index < ui.wizardStep ? "border-emerald-900 text-emerald-300" : "border-zinc-800 text-zinc-500"}"><span class="mr-2">${index < ui.wizardStep ? "✓" : index + 1}</span>${name}</button>`).join("")}</div><div class="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_320px] gap-4"><section class="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 md:p-6 min-w-0">${content}<div class="mt-6 pt-4 border-t border-zinc-800 flex justify-between"><button id="wizard-back" class="rounded-md border border-zinc-700 px-3 py-2 text-xs ${ui.wizardStep === 0 ? "invisible" : ""}">← Назад</button><button id="wizard-next" class="rounded-md bg-indigo-600 px-4 py-2 text-xs font-medium text-white hover:bg-indigo-500">${ui.wizardStep === 3 ? `Запустить ${ui.selectedCameras.size} сбора` : "Продолжить →"}</button></div></section><aside class="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4 h-fit"><h2 class="text-sm font-semibold">Ваш сбор</h2><div id="wizard-summary"></div></aside></div></div>`;
    updateWizardSummary();
    bindWizardEvents();
    host.querySelector("[data-wizard-cancel]").addEventListener("click", () => setPage("overview"));
    host.querySelectorAll("[data-wizard-step]").forEach((button) => button.addEventListener("click", () => setWizardStep(Number(button.dataset.wizardStep))));
    host.querySelector("#wizard-back").addEventListener("click", () => setWizardStep(ui.wizardStep - 1));
    host.querySelector("#wizard-next").addEventListener("click", () => {
      if (ui.wizardStep === 3) launchCollection();
      else if (ui.wizardStep === 0 && !ui.selectedCameras.size) toast("Сначала выберите хотя бы один источник");
      else if (ui.wizardStep === 2 && ui.mode !== "timer" && !ui.selectedModel) toast("В проекте назначения нет модели. Выберите другой проект или режим по интервалу.");
      else setWizardStep(ui.wizardStep + 1);
    });
  }

  function renderWizardCameras() {
    const rows = wizardSourceRows();
    const pageSize = 12;
    const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
    ui.wizardSourcePage = Math.min(ui.wizardSourcePage, pageCount);
    const start = (ui.wizardSourcePage - 1) * pageSize;
    const visible = rows.slice(start, start + pageSize);
    return `<h2 class="text-lg font-semibold">Выберите источники</h2><p class="text-xs text-zinc-400 mt-1">Можно выбрать камеры из разных проектов. Для каждой будет создан отдельный сбор.</p><div class="flex flex-wrap gap-2 mt-4"><input id="wizard-search" type="search" value="${escapeAttribute(ui.query)}" placeholder="Поиск по камерам и проектам…" class="w-full sm:w-72 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-xs"><button id="wizard-select-visible" class="rounded-lg border border-zinc-700 px-3 py-2 text-xs">Выбрать доступные на странице</button><span class="ml-auto self-center text-xs text-zinc-400">Выбрано: ${ui.selectedCameras.size}</span></div><div class="mt-3 rounded-lg border border-zinc-800 overflow-hidden">${visible.map((stream) => { const project = projects.find((item) => item.id === stream.project_id); const state = stateFor(stream); const checked = ui.selectedCameras.has(stream.id); return `<label class="flex items-center gap-3 p-3 border-b border-zinc-800 last:border-0 cursor-pointer hover:bg-zinc-800/40 ${checked ? "bg-indigo-950/20" : ""}"><input data-wizard-camera="${stream.id}" type="checkbox" class="accent-indigo-500" ${checked ? "checked" : ""}><span class="min-w-0 flex-1"><strong class="text-xs font-medium">${escapeHtml(stream.name)}</strong><span class="block text-[10px] text-zinc-500 mt-1">${escapeHtml(project?.name || "Проект удалён")} · ${escapeHtml(({RTSP:"RTSP",DEVICE:"Веб-камера",VIDEO_FILE:"Видеофайл",IMAGE_FOLDER:"Папка кадров"})[stream.source_type] || stream.source_type)}</span></span><span class="rounded-full border px-2 py-1 text-[10px] ${badgeClass(state)}">${escapeHtml(stateLabel(state))}</span><span class="text-[10px] text-zinc-500">${Number(stream.captured_frames_count || 0)} кадров</span></label>`; }).join("") || `<div class="p-9 text-center text-sm text-zinc-500">Нет доступных источников. Создайте RTSP источник, добавьте веб-камеру, видео или папку кадров.</div>`}</div><div class="flex items-center justify-between mt-3 text-[11px] text-zinc-500"><span>${rows.length ? `${start + 1}–${Math.min(start + pageSize, rows.length)} из ${rows.length} источников` : "0 источников"}</span><div class="flex items-center gap-2"><button id="wizard-source-prev" class="rounded border border-zinc-700 px-2 py-1" ${ui.wizardSourcePage <= 1 ? "disabled" : ""}>←</button><span>${ui.wizardSourcePage} / ${pageCount}</span><button id="wizard-source-next" class="rounded border border-zinc-700 px-2 py-1" ${ui.wizardSourcePage >= pageCount ? "disabled" : ""}>→</button></div></div><p class="mt-2 text-[10px] text-zinc-600">Источники с текущей ошибкой подключения временно недоступны для нового запуска.</p>`;
  }

  function renderWizardProject() {
    const firstSelectedSource = streams.find((stream) => ui.selectedCameras.has(stream.id));
    const selectedProject = projects.find((item) => item.id === ui.project) || projects.find((item) => item.id === firstSelectedSource?.project_id) || projects[0];
    if (!ui.project && selectedProject) ui.project = selectedProject.id;
    return `<h2 class="text-lg font-semibold">Куда складывать кадры?</h2><p class="text-xs text-zinc-400 mt-1">Камера может быть из одного проекта, а кадры — попадать в другой. Проверьте классы при выборе другого проекта.</p><div class="mt-5 max-w-xl"><label class="block text-xs font-medium text-zinc-300 mb-2">Проект назначения для выбранных сборов</label><select id="wizard-project" class="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2.5 text-xs">${projectOptions(ui.project)}</select><label class="block text-xs font-medium text-zinc-300 mt-5 mb-2">Название сбора</label><input id="wizard-name" value="${escapeAttribute(ui.collectionName)}" placeholder="Например: Слежение за паллетами" class="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2.5 text-xs"><h3 class="text-xs font-semibold text-zinc-300 mt-6">Выберите, когда сохранять кадр</h3><div class="grid md:grid-cols-3 gap-2 mt-3">${[["timer","◷","По интервалу","Кадр через заданное число секунд. Для таймлапса, модель не нужна."],["stable","◉","Когда объект стабилен","Модель следит за объектом и сохраняет лучший кадр после нескольких кадров."],["line","↗","При пересечении линии","Кадр сохраняется, когда объект пересекает линию. Линию можно задать после запуска."]].map(([key,icon,title,desc]) => `<button data-wizard-mode="${key}" class="rounded-xl border p-3 text-left ${ui.mode === key ? "border-indigo-500 bg-indigo-950/30" : "border-zinc-800 bg-zinc-950/40"}"><span class="text-lg text-indigo-300">${icon}</span><strong class="block text-xs mt-1">${title}</strong><span class="block text-[10px] text-zinc-500 mt-1 leading-4">${desc}</span></button>`).join("")}</div></div>`;
  }

  function renderWizardConditions() {
    if (ui.mode !== "timer" && !ui.selectedModel) ui.selectedModel = ui.modelByProject.get(ui.project)?.[0]?.id || "";
    const projectModels = ui.modelByProject.get(ui.project) || [];
    const chosen = projectModels.find((model) => model.id === ui.selectedModel);
    const classRows = allClasses(ui.project);
    const modeFields = ui.mode === "timer" ? `<div class="mt-4"><label class="block text-xs text-zinc-300 mb-2">Сохранять один кадр с каждой камеры каждые</label><div class="flex items-center gap-2"><input id="wizard-timer" type="number" min="0.5" step="0.5" value="${Number(ui.timerSeconds)}" class="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-xs"><span class="text-xs text-zinc-500">секунд</span></div><div class="mt-3 rounded-lg border border-zinc-800 p-3 text-[11px] text-zinc-400">За минуту будет до ${Math.round(60 / Math.max(0.5, Number(ui.timerSeconds)) * ui.selectedCameras.size)} кадров с выбранных камер. Модель не используется; кадры появятся среди неразмеченных.</div></div>` : `<div class="mt-4"><label class="block text-xs text-zinc-300 mb-2">Модель этого проекта</label><select id="wizard-model" class="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-xs">${projectModels.map((model) => `<option value="${escapeAttribute(model.id)}" ${model.id === ui.selectedModel ? "selected" : ""}>${escapeHtml(model.display_name || model.name)} · v${model.version_number}${model.is_active_for_stream ? " · активная" : ""}</option>`).join("")}</select>${chosen ? `<div class="mt-2 rounded-lg border border-zinc-800 p-3 text-[11px] text-zinc-400">${escapeHtml(chosen.display_name || chosen.name)} · версия ${chosen.version_number}${chosen.map50 == null ? "" : ` · mAP50 ${(Number(chosen.map50) * 100).toFixed(1)}%`}<p class="text-[10px] text-zinc-500 mt-1">Показаны модели проекта назначения: их классы уже соответствуют проекту. Модели других проектов пока нельзя безопасно применить без сопоставления классов.</p></div>` : `<div class="mt-2 rounded-lg border border-amber-900/70 bg-amber-950/20 p-3 text-[11px] text-amber-200">В проекте нет модели. Переключитесь на «По интервалу» или сначала обучите/загрузите модель.</div>`}<div class="grid sm:grid-cols-2 gap-4 mt-4"><div><label class="block text-xs text-zinc-300 mb-2">Минимальная уверенность модели</label><div class="flex items-center gap-3"><input id="wizard-confidence" type="range" min="0" max="1" step="0.05" value="${Number(ui.confidence)}" class="flex-1"><span id="wizard-confidence-value" class="text-xs">${Math.round(ui.confidence * 100)}%</span></div></div><div><label class="block text-xs text-zinc-300 mb-2">Не собирать выше (сложные кадры)</label><div class="flex items-center gap-3"><input id="wizard-max-confidence" type="range" min="0" max="1" step="0.05" value="${Number(ui.maxConfidence)}" class="flex-1"><span id="wizard-max-confidence-value" class="text-xs">${Math.round(ui.maxConfidence * 100)}%</span></div></div></div><div class="mt-4"><div class="text-xs text-zinc-300 mb-2">Какие классы учитывать</div><div class="flex flex-wrap gap-2">${classRows.map((item) => `<label class="rounded-md border border-zinc-800 bg-zinc-950/40 px-2.5 py-1.5 text-xs"><input data-wizard-class="${escapeAttribute(item.id)}" type="checkbox" class="mr-1.5 accent-indigo-500" ${ui.classIds.has(item.id) ? "checked" : ""}>${escapeHtml(item.name)}</label>`).join("") || `<span class="text-[11px] text-zinc-500">У проекта пока нет классов</span>`}</div><p class="text-[10px] text-zinc-500 mt-1">Если не выбрать ни одного класса, учитываются все классы.</p></div>${ui.mode === "stable" ? `<div class="mt-4 grid sm:grid-cols-3 gap-3"><label class="text-[11px] text-zinc-400">Последовательных кадров<input id="wizard-frames" type="number" min="2" value="${Number(ui.minFrames)}" class="block mt-1 w-full rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-xs"></label><label class="text-[11px] text-zinc-400">Допустимое изменение размера, %<input id="wizard-size" type="number" min="0" value="${Math.round(ui.sizeVariation * 100)}" class="block mt-1 w-full rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-xs"></label><label class="text-[11px] text-zinc-400">Повтор для того же объекта, с<input id="wizard-cooldown" type="number" min="0" step="0.5" value="${Number(ui.cooldown)}" class="block mt-1 w-full rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-xs"></label></div>` : ""}<details class="mt-4 text-xs text-zinc-400"><summary class="cursor-pointer">Подробно про режим «${ui.mode === "line" ? "Пересечение линии" : "Стабильный объект"}»</summary><p class="mt-2 text-[11px] leading-5 text-zinc-500">${ui.mode === "line" ? "Условие запускается после того, как в настройках источника задана линия пересечения. Линия и направление настраиваются в подробностях сбора отдельно для каждой камеры." : "Число кадров определяет длину отслеживания. Допустимое изменение размера помогает дождаться замедления объекта. Повторный захват ограничен интервалом."}</p></details>`;
    return `<h2 class="text-lg font-semibold">Когда считать кадр подходящим?</h2><p class="text-xs text-zinc-400 mt-1">Настройте условие сохранения и посмотрите, как оно звучит простыми словами.</p><div class="mt-5 rounded-xl border border-zinc-800 bg-zinc-950/40 p-4">${modeFields}<div class="mt-4 rounded-lg border border-indigo-900/70 bg-indigo-950/30 p-3"><div class="text-[10px] uppercase tracking-wider text-indigo-300 mb-1">Ваше правило</div><p class="text-xs leading-5">${escapeHtml(modeText())}</p></div></div>`;
  }

  function renderWizardCheck() {
    const selected = [...ui.selectedCameras].map((id) => streams.find((stream) => stream.id === id)).filter(Boolean);
    const project = projects.find((item) => item.id === ui.project);
    const model = modelById(ui.selectedModel);
    const ready = selected.length > 0 && selected.every((stream) => stateFor(stream) !== "error") && Boolean(project) && (ui.mode === "timer" || Boolean(model && model.project_id === ui.project));
    const summary = selected.map((stream) => { const state = stateFor(stream); const compatible = stream.project_id === ui.project || ui.mode === "timer"; return `<div class="flex items-center gap-3 py-3 border-b border-zinc-800 last:border-0"><span class="rounded-full border px-2 py-1 text-[10px] ${badgeClass(state)}">${escapeHtml(stateLabel(state))}</span><span class="min-w-0 flex-1"><strong class="text-xs">${escapeHtml(stream.name)}</strong><span class="block text-[10px] text-zinc-500 mt-1">${escapeHtml(projects.find((item) => item.id === stream.project_id)?.name || "Проект удалён")}</span></span><span class="text-[10px] ${compatible ? "text-emerald-300" : "text-amber-300"}">${compatible ? "Назначение выбрано" : "Сверьте классы"}</span></div>`; }).join("");
    return `<h2 class="text-lg font-semibold">Проверьте перед запуском</h2><p class="text-xs text-zinc-400 mt-1">Будет создано ${selected.length} сборов; у каждого свой источник, общий проект назначения и одинаковое правило.</p><div class="mt-5 rounded-xl border border-zinc-800 p-4"><h3 class="text-xs font-semibold">Источники и доступность</h3>${summary || `<p class="mt-3 text-xs text-rose-300">Не выбраны источники.</p>`}</div><div class="grid md:grid-cols-2 gap-3 mt-3"><div class="rounded-xl border border-zinc-800 p-4"><div class="text-[10px] uppercase text-zinc-500">Проект назначения</div><div class="text-sm font-medium mt-2">${escapeHtml(project?.name || "Не выбран")}</div></div><div class="rounded-xl border border-zinc-800 p-4"><div class="text-[10px] uppercase text-zinc-500">Модель и правило</div><div class="text-sm font-medium mt-2">${ui.mode === "timer" ? "Без модели · таймер" : escapeHtml(model?.display_name || "Модель не выбрана")}</div><p class="text-[11px] text-zinc-400 mt-2">${escapeHtml(modeText())}</p></div></div><div class="mt-4 rounded-lg border ${ready ? "border-emerald-900 bg-emerald-950/20 text-emerald-200" : "border-amber-900 bg-amber-950/20 text-amber-200"} p-3 text-xs">${ready ? "Проверки пройдены. Запуск создаст по одному сбору на камеру." : "Нужно выбрать доступные источники, проект назначения и модель для режима с нейросетью."}</div>${!ui.diagnostic ? `<button id="wizard-diagnose" class="mt-4 rounded-lg border border-zinc-700 px-3 py-2 text-xs">Проверить доступность и настройки</button>` : `<div class="mt-4 space-y-1 text-[11px] text-emerald-300">✓ Конфигурация проверена в браузере<br>✓ Модель и проект назначения совпадают<br>✓ Каждый сбор будет сохранять кадры в свой проект</div>`}<p class="mt-3 text-[10px] text-zinc-600">Фактическое подключение камеры проверяется сервером при запуске. Здесь заранее проверяются выбранные параметры и совместимость.</p>`;
  }

  async function launchCollection() {
    const next = document.getElementById("wizard-next");
    const ids = [...ui.selectedCameras];
    if (!ids.length) { toast("Выберите хотя бы одну камеру"); return; }
    if (!ui.diagnostic) { toast("Сначала проверьте параметры на шаге проверки"); return; }
    if (ui.mode !== "timer" && !ui.selectedModel) { toast("Выберите модель для проекта назначения"); return; }
    next.disabled = true;
    next.textContent = "Создаём сборы…";
    const config = {
      timer_enabled: ui.mode === "timer",
      timer_interval_seconds: Math.max(0.5, Number(ui.timerSeconds) || 5),
      track_stable_enabled: ui.mode === "stable",
      track_stable_min_frames: Math.max(2, Number(ui.minFrames) || 12),
      track_stable_max_size_variation: Math.max(0, Number(ui.sizeVariation) || 0.35),
      track_stable_min_avg_conf: 0.75,
      track_stable_interval_seconds: Math.max(0.1, Number(ui.cooldown) || 5),
      confidence_min: Math.max(0, Math.min(1, Number(ui.confidence))),
      confidence_max: Math.max(Number(ui.confidence), Math.min(1, Number(ui.maxConfidence))),
      tripwire_enabled: ui.mode === "line",
      tripwire_line: null,
      tripwire_classes: [...ui.classIds],
      tripwire_direction: "ANY",
      tripwire_debounce_seconds: 3,
      cooldown_seconds: Math.max(0, Number(ui.cooldown) || 3),
    };
    const sourceById = new Map(streams.map((stream) => [stream.id, stream]));
    const created = [];
    try {
      for (const id of ids) {
        const original = sourceById.get(id);
        if (!original) continue;
        const destinationProject = projects.find((item) => item.id === ui.project);
        const source = await duplicateSourceForProject(original, destinationProject);
        const configured = await api.putStreamTriggers(source.id, {
          model_version_id: ui.mode === "timer" ? null : ui.selectedModel,
          config,
        });
        if (ui.mode === "line") { created.push(configured); continue; }
        await api.startStream(configured.id);
        created.push(configured);
      }
      selectedId = created[0]?.id || null;
      await refresh();
      ui.page = "overview";
      ui.wizardStep = 0;
      ui.diagnostic = false;
      renderCenter();
      toast(ui.mode === "line" ? `Создано ${created.length} сборов. Задайте линию в условиях каждого источника и запустите его.` : `Запущено ${created.length} сборов`);
    } catch (error) {
      await refresh().catch(() => {});
      renderWizard();
      toast(`${created.length ? `Успели запустить ${created.length}. ` : ""}${error.message || String(error)}`);
    } finally {
      const current = document.getElementById("wizard-next");
      if (current) current.disabled = false;
    }
  }

  async function duplicateSourceForProject(source, project) {
    if (!project) throw new Error("Выберите проект назначения");
    const label = ui.collectionName.trim();
    const name = label ? `${label} · ${source.name}` : `${source.name} · сбор`;
    return api.copyStreamToProject(source.id, project.id, name);
  }

  function renderDetail() {
    const host = document.getElementById("stream-center-content");
    const stream = selected();
    if (!stream) { ui.page = "overview"; renderOverview(); return; }
    const project = projects.find((item) => item.id === stream.project_id);
    const model = modelById(stream.model_version_id);
    const status = statuses.get(stream.id) || {};
    const running = Boolean(stream.is_active || status.is_running);
    const error = status.error_message;
    host.innerHTML = `<div class="p-5 md:p-7 max-w-[1500px] mx-auto space-y-5"><button data-detail-back class="text-xs text-zinc-500 hover:text-white">← Все сборы</button><div class="flex flex-wrap items-start justify-between gap-3"><div><div class="text-[11px] text-indigo-300">${escapeHtml(project?.name || "Проект удалён")}</div><h1 class="text-2xl font-semibold mt-1">${escapeHtml(stream.name)}</h1><p class="text-sm text-zinc-400 mt-1">${escapeHtml(configSummary(stream))}</p></div><div class="flex gap-2"><button data-detail-action="start" class="rounded-lg bg-emerald-700 px-3 py-2 text-xs text-white ${running ? "hidden" : ""}">Подключить для настройки</button><button data-detail-action="stop" class="rounded-lg border border-zinc-700 px-3 py-2 text-xs ${running ? "" : "hidden"}">Остановить этот сбор</button><button data-detail-action="remove" class="rounded-lg border border-rose-900 px-3 py-2 text-xs text-rose-300">Удалить источник</button></div></div>${error ? `<div class="rounded-lg border border-rose-900 bg-rose-950/30 p-3 text-xs text-rose-200">Нет кадров от источника. ${escapeHtml(error)}</div>` : ""}<div class="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_350px] gap-4"><section class="space-y-3"><div id="stream-detail-frame" class="relative aspect-video max-h-[65vh] rounded-xl border border-zinc-800 bg-black flex items-center justify-center overflow-hidden"><img id="stream-detail-live" class="max-h-full max-w-full object-contain ${running ? "" : "hidden"}" alt="Прямой поток"><div id="stream-detail-empty" class="text-center text-zinc-500 text-xs ${running ? "hidden" : ""}">${stream.config?.tripwire_enabled ? "Сначала подключите источник для предпросмотра" : "Источник остановлен"}<br><span class="text-[10px]">${stream.config?.tripwire_enabled ? "Без линии кадры пока не сохраняются" : "Запустите сбор, чтобы проверить изображение"}</span></div><canvas id="stream-detail-canvas" class="absolute inset-0 h-full w-full ${stream.config?.tripwire_enabled ? "pointer-events-auto cursor-crosshair" : "pointer-events-none"}"></canvas></div><div class="flex flex-wrap items-center gap-2 ${stream.config?.tripwire_enabled ? "" : "hidden"}"><button id="detail-draw-line" class="rounded-lg border border-cyan-800 px-3 py-2 text-xs text-cyan-200 ${running ? "" : "opacity-50"}" ${running ? "" : "disabled"}>${line ? "Нарисовать линию заново" : "Нарисовать линию на кадре"}</button><span id="detail-line-hint" class="text-[11px] text-zinc-400">${line ? "Линия задана · перетащите её концы, чтобы изменить" : running ? "Нажмите кнопку и укажите на кадре точки A и B" : "Сначала подключите источник для предпросмотра; без линии сбор не сохраняет кадры"}</span></div><div id="stream-detail-stats" class="grid md:grid-cols-3 gap-2">${[["Видео",running ? `Поступает · ${Number(status.fps || 0).toFixed(1)} FPS` : "Остановлено",error], ["Обработка",stream.config?.timer_enabled ? "Таймер активен" : model?.display_name || "Модель не выбрана",!stream.config?.timer_enabled && !model], ["Запись",`${Number(status.captured_count ?? stream.captured_frames_count ?? 0).toLocaleString("ru-RU")} кадров сохранено`,false]].map(([title,text,bad]) => `<div class="rounded-xl border ${bad ? "border-rose-900 bg-rose-950/20" : "border-zinc-800 bg-zinc-900/50"} p-3"><div class="text-[10px] uppercase text-zinc-500">${title}</div><div class="detail-stat-value mt-2 text-xs ${bad ? "text-rose-300" : "text-zinc-200"}">${escapeHtml(text)}</div></div>`).join("")}</div><div class="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4"><h2 class="text-sm font-semibold">Что происходит?</h2><p id="stream-detail-explanation" class="mt-2 text-xs leading-5 text-zinc-400">${error ? `Источник сообщил ошибку: ${escapeHtml(error)}. Другие потоки продолжают работать.` : stream.config?.tripwire_enabled && !line ? running ? "Поток подключён, но линия ещё не задана. Нажмите «Нарисовать линию на кадре»: до этого кадры не сохраняются." : "Условие пересечения выбрано, но линия не задана. Подключите источник для предпросмотра и отметьте на кадре точки A и B." : running ? status.last_capture_at ? `Последний сохранённый кадр: ${escapeHtml(new Date(status.last_capture_at).toLocaleString("ru-RU"))}. Если кадры не появляются, проверьте условие и классы модели.` : "Поток получает кадры. Если подходящий объект ещё не появился, сохранений может пока не быть." : "Сбор приостановлен. Чтобы начать, нажмите «Запустить сбор»."}</p></div></section><aside class="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4 h-fit"><h2 class="text-sm font-semibold">Условия этого сбора</h2><div class="mt-3 space-y-3 text-xs"><div><div class="text-[10px] text-zinc-500">Источник</div><div class="mt-1">${escapeHtml(({RTSP:"RTSP-камера",DEVICE:"Веб-камера",VIDEO_FILE:"Видеофайл",IMAGE_FOLDER:"Папка кадров"})[stream.source_type] || stream.source_type)} · ${escapeHtml(project?.name || "")}</div></div><div><div class="text-[10px] text-zinc-500">Модель</div><div class="mt-1">${escapeHtml(stream.config?.timer_enabled ? "Не используется" : model?.display_name || "Не выбрана")}</div></div><div><div class="text-[10px] text-zinc-500">Правило</div><div class="mt-1 leading-5">${escapeHtml(configSummary(stream))}<br>Уверенность от ${Math.round(Number(stream.config?.confidence_min ?? 0.25) * 100)}%</div></div><div class="border-t border-zinc-800 pt-3"><button id="detail-edit-rules" class="w-full rounded-lg border border-zinc-700 px-3 py-2 text-xs hover:bg-zinc-800">Изменить условия</button></div><div><button id="detail-open-review" class="w-full text-left text-xs text-emerald-300">Перейти в проект назначения →</button></div></div></aside></div></div>`;
    if (running) { const img = host.querySelector("#stream-detail-live"); if (!img.getAttribute("src")) img.src = api.streamLiveUrl(stream.id); }
    host.querySelector("[data-detail-back]").addEventListener("click", () => setPage("overview"));
    host.querySelector("[data-detail-action='start']")?.addEventListener("click", (event) => runStreamAction(event.currentTarget, true));
    host.querySelector("[data-detail-action='stop']")?.addEventListener("click", (event) => runStreamAction(event.currentTarget, false));
    host.querySelector("#detail-draw-line")?.addEventListener("click", () => { drawMode = true; pendingPoint = null; toast("На кадре укажите точку A, затем точку B"); });
    const detailCanvas = host.querySelector("#stream-detail-canvas");
    detailCanvas?.addEventListener("click", handleLineCanvasClick);
    detailCanvas?.addEventListener("mousedown", handleLineCanvasMouseDown);
    detailCanvas?.addEventListener("mousemove", handleLineCanvasMouseMove);
    detailCanvas?.addEventListener("mouseup", handleLineCanvasMouseUp);
    detailCanvas?.addEventListener("mouseleave", handleLineCanvasMouseUp);
    host.querySelector("#stream-detail-live")?.addEventListener("load", drawLineOverlay);
    drawLineOverlay();
    host.querySelector("[data-detail-action='remove']")?.addEventListener("click", async (event) => { if (!window.confirm(`Удалить источник «${stream.name}»?`)) return; event.currentTarget.disabled = true; try { await api.deleteStream(stream.id); selectedId = null; await refresh(); setPage("overview"); toast("Источник удалён"); } catch (error) { toast(error.message); event.currentTarget.disabled = false; } });
    host.querySelector("#detail-edit-rules").addEventListener("click", () => { ui.page = "new"; ui.wizardStep = 0; ui.selectedCameras = new Set([stream.id]); ui.project = stream.project_id; ui.mode = stream.config?.timer_enabled ? "timer" : stream.config?.tripwire_enabled ? "line" : "stable"; ui.selectedModel = stream.model_version_id || ""; renderCenter(); });
    host.querySelector("#detail-open-review").addEventListener("click", () => { if (!project) return; const path = projectPath(project.id, "data"); navigate(path); });
  }

  function refreshDetailStatus() {
    if (ui.page !== "detail") return;
    const stream = selected();
    if (!stream) return;
    const status = statuses.get(stream.id) || {};
    const running = Boolean(stream.is_active || status.is_running);
    const root = document.getElementById("stream-center-content");
    const center = document.getElementById("view-stream-center");
    const centerVisible = center && !center.classList.contains("hidden");
    root.querySelector("[data-detail-action='start']")?.classList.toggle("hidden", running);
    root.querySelector("[data-detail-action='stop']")?.classList.toggle("hidden", !running);
    const image = root.querySelector("#stream-detail-live");
    const empty = root.querySelector("#stream-detail-empty");
    if ((!centerVisible || !running) && image?.hasAttribute("src")) image.removeAttribute("src");
    if (centerVisible && running && image && !image.getAttribute("src")) image.src = api.streamLiveUrl(stream.id);
    image?.classList.toggle("hidden", !running);
    empty?.classList.toggle("hidden", running);
    const drawButton = root.querySelector("#detail-draw-line");
    if (drawButton) {
      drawButton.disabled = !running;
      drawButton.classList.toggle("opacity-50", !running);
    }
    const hint = root.querySelector("#detail-line-hint");
    if (hint && stream.config?.tripwire_enabled && !drawMode) {
      hint.textContent = line ? "Линия задана · перетащите её концы, чтобы изменить" : running ? "Нажмите кнопку и укажите на кадре точки A и B" : "Сначала подключите источник для предпросмотра; без линии сбор не сохраняет кадры";
    }
    const explanation = root.querySelector("#stream-detail-explanation");
    if (explanation && stream.config?.tripwire_enabled && !line && !status.error_message) {
      explanation.textContent = running
        ? "Поток подключён, но линия ещё не задана. Нажмите «Нарисовать линию на кадре»: до этого кадры не сохраняются."
        : "Условие пересечения выбрано, но линия не задана. Подключите источник для предпросмотра и отметьте на кадре точки A и B.";
    }
    const values = root.querySelectorAll("#stream-detail-stats .detail-stat-value");
    if (values.length >= 3) {
      values[0].textContent = running ? `Поступает · ${Number(status.fps || 0).toFixed(1)} FPS` : "Остановлено";
      values[2].textContent = `${Number(status.captured_count ?? stream.captured_frames_count ?? 0).toLocaleString("ru-RU")} кадров сохранено`;
    }
    drawLineOverlay();
  }

  function handleLineCanvasClick(event) {
    if (!drawMode) return;
    const [x, y] = normFromClient(event);
    if (!pendingPoint) {
      pendingPoint = [x, y];
      drawLineOverlay();
      toast("Точка A задана. Теперь укажите точку B");
      return;
    }
    line = [pendingPoint[0], pendingPoint[1], x, y];
    pendingPoint = null;
    drawMode = false;
    drawLineOverlay();
    saveTriggers({ quiet: true }).then(() => {
      const hint = document.getElementById("detail-line-hint");
      if (hint) hint.textContent = "Линия сохранена · перетащите её концы, чтобы изменить";
      toast("Линия сохранена. Сбор будет фиксировать пересечения");
    }).catch((error) => toast(error.message));
  }

  function handleLineCanvasMouseDown(event) {
    if (drawMode) return;
    const hit = endpointHits(event);
    if (hit === null) return;
    dragEndpoint = hit;
    event.preventDefault();
  }

  function handleLineCanvasMouseMove(event) {
    if (dragEndpoint === null || !line) return;
    const [x, y] = normFromClient(event);
    const next = [...line];
    next[dragEndpoint * 2] = x;
    next[dragEndpoint * 2 + 1] = y;
    line = next;
    drawLineOverlay();
  }

  function handleLineCanvasMouseUp() {
    if (dragEndpoint === null) return;
    dragEndpoint = null;
    saveTriggers({ quiet: true }).then(() => toast("Положение линии сохранено")).catch((error) => toast(error.message));
  }

  function bindWizardEvents() {
    const host = document.getElementById("stream-center-content");
    host.querySelector("#wizard-search")?.addEventListener("input", (event) => { ui.query = event.target.value; ui.wizardSourcePage = 1; renderWizard(); const input = host.querySelector("#wizard-search"); input?.focus(); input?.setSelectionRange(ui.query.length, ui.query.length); });
    host.querySelector("#wizard-select-visible")?.addEventListener("click", () => { const start = (ui.wizardSourcePage - 1) * 12; wizardSourceRows().slice(start, start + 12).forEach((stream) => ui.selectedCameras.add(stream.id)); renderWizard(); });
    host.querySelector("#wizard-source-prev")?.addEventListener("click", () => { ui.wizardSourcePage -= 1; renderWizard(); });
    host.querySelector("#wizard-source-next")?.addEventListener("click", () => { ui.wizardSourcePage += 1; renderWizard(); });
    host.querySelectorAll("[data-wizard-camera]").forEach((input) => input.addEventListener("change", () => { input.checked ? ui.selectedCameras.add(input.dataset.wizardCamera) : ui.selectedCameras.delete(input.dataset.wizardCamera); renderWizard(); }));
    host.querySelector("#wizard-project")?.addEventListener("change", (event) => { ui.project = event.target.value; ui.selectedModel = ui.modelByProject.get(ui.project)?.[0]?.id || ""; ui.classIds.clear(); ui.diagnostic = false; renderWizard(); });
    host.querySelector("#wizard-name")?.addEventListener("input", (event) => { ui.collectionName = event.target.value; });
    host.querySelectorAll("[data-wizard-mode]").forEach((button) => button.addEventListener("click", () => { ui.mode = button.dataset.wizardMode; ui.diagnostic = false; renderWizard(); }));
    host.querySelector("#wizard-model")?.addEventListener("change", (event) => { ui.selectedModel = event.target.value; ui.diagnostic = false; updateWizardSummary(); });
    host.querySelector("#wizard-timer")?.addEventListener("input", (event) => { ui.timerSeconds = Number(event.target.value); ui.diagnostic = false; renderWizard(); });
    host.querySelector("#wizard-confidence")?.addEventListener("input", (event) => { ui.confidence = Number(event.target.value); ui.diagnostic = false; host.querySelector("#wizard-confidence-value").textContent = `${Math.round(ui.confidence * 100)}%`; updateWizardSummary(); });
    host.querySelector("#wizard-max-confidence")?.addEventListener("input", (event) => { ui.maxConfidence = Math.max(Number(event.target.value), ui.confidence); ui.diagnostic = false; host.querySelector("#wizard-max-confidence-value").textContent = `${Math.round(ui.maxConfidence * 100)}%`; });
    host.querySelectorAll("[data-wizard-class]").forEach((input) => input.addEventListener("change", () => { input.checked ? ui.classIds.add(input.dataset.wizardClass) : ui.classIds.delete(input.dataset.wizardClass); ui.diagnostic = false; }));
    for (const [id, key, convert = Number] of [["wizard-frames","minFrames"],["wizard-size","sizeVariation",(v) => Number(v) / 100],["wizard-cooldown","cooldown"]]) host.querySelector(`#${id}`)?.addEventListener("input", (event) => { ui[key] = convert(event.target.value); ui.diagnostic = false; updateWizardSummary(); });
    host.querySelector("#wizard-diagnose")?.addEventListener("click", () => { const valid = ui.selectedCameras.size > 0 && projects.some((project) => project.id === ui.project) && [...ui.selectedCameras].every((id) => { const stream = streams.find((item) => item.id === id); return stream && stateFor(stream) !== "error"; }) && (ui.mode === "timer" || Boolean(modelById(ui.selectedModel)?.project_id === ui.project)); if (!valid) { toast("Проверьте источники, проект назначения и модель"); return; } ui.diagnostic = true; renderWizard(); });
  }

  function renderCameras() {
    const host = document.getElementById("stream-center-content");
    const list = streams.filter((stream) => {
      const project = projects.find((item) => item.id === stream.project_id);
      const query = ui.query.trim().toLowerCase();
      return (!ui.project || stream.project_id === ui.project) && (!query || `${stream.name} ${project?.name || ""} ${stream.source_type} ${stream.source_uri}`.toLowerCase().includes(query));
    });
    host.innerHTML = `<div class="p-5 md:p-7 max-w-[1500px] mx-auto space-y-5"><div class="flex flex-wrap items-start justify-between gap-3"><div><h1 class="text-2xl font-semibold">Камеры и источники</h1><p class="text-sm text-zinc-400 mt-1">Каждый источник привязан к проекту и может участвовать в нескольких сборах.</p></div><button id="camera-add-source" class="rounded-lg bg-indigo-600 px-3 py-2 text-xs">＋ Добавить источник</button></div><div class="grid grid-cols-2 xl:grid-cols-4 gap-3"><div class="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4"><div class="text-xs text-zinc-500">Всего источников</div><div class="text-2xl mt-1">${streams.length}</div><div class="text-[11px] text-zinc-500">Во всех проектах</div></div><div class="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4"><div class="text-xs text-zinc-500">Подключены</div><div class="text-2xl text-emerald-300 mt-1">${streams.filter((stream) => ["running", "starting", "reconnecting"].includes(stateFor(stream))).length}</div><div class="text-[11px] text-zinc-500">Активность обновляется каждую секунду</div></div><div class="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4"><div class="text-xs text-zinc-500">Недоступны</div><div class="text-2xl ${streams.filter((stream) => stateFor(stream) === "error").length ? "text-rose-300" : "text-zinc-300"} mt-1">${streams.filter((stream) => stateFor(stream) === "error").length}</div><div class="text-[11px] text-zinc-500">Ошибки активных потоков</div></div><div class="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4"><div class="text-xs text-zinc-500">Проекты</div><div class="text-2xl mt-1">${projects.length}</div><div class="text-[11px] text-zinc-500">Кадры пишутся в проект сбора</div></div></div><div class="flex flex-wrap gap-2"><input id="camera-search" type="search" class="w-full sm:w-72 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs" value="${escapeAttribute(ui.query)}" placeholder="Название, тип источника…"><select id="camera-project" class="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs">${projectOptions(ui.project, true)}</select></div><div class="rounded-xl border border-zinc-800 overflow-x-auto"><table class="w-full text-left text-xs"><thead class="bg-zinc-900 text-[10px] uppercase text-zinc-500"><tr><th class="px-4 py-3">Источник</th><th class="px-4 py-3">Проект</th><th class="px-4 py-3">Тип</th><th class="px-4 py-3">Состояние</th><th class="px-4 py-3">Использование</th><th class="px-4 py-3">Действие</th></tr></thead><tbody>${list.slice((ui.cameraPage - 1) * 12, ui.cameraPage * 12).map((stream) => { const project = projects.find((item) => item.id === stream.project_id); const state = stateFor(stream); return `<tr class="border-t border-zinc-800"><td class="px-4 py-3"><div class="font-medium">${escapeHtml(stream.name)}</div><div class="text-[10px] text-zinc-500 mt-1 max-w-64 truncate">${escapeHtml(stream.source_uri || "")}</div></td><td class="px-4 py-3 text-indigo-300">${escapeHtml(project?.name || "Проект удалён")}</td><td class="px-4 py-3 text-zinc-400">${escapeHtml(({RTSP:"RTSP-камера",DEVICE:"Веб-камера",VIDEO_FILE:"Видеофайл",IMAGE_FOLDER:"Папка изображений"})[stream.source_type] || stream.source_type)}</td><td class="px-4 py-3"><span class="inline-flex rounded-full border px-2 py-1 text-[10px] ${badgeClass(state)}">● ${escapeHtml(stateLabel(state))}</span></td><td class="px-4 py-3 text-zinc-400">${escapeHtml(configSummary(stream))}</td><td class="px-4 py-3"><button data-camera-use="${stream.id}" class="rounded-md bg-indigo-600 px-2.5 py-1.5 text-[11px] text-white">Новый сбор</button></td></tr>`; }).join("") || `<tr><td colspan="6" class="p-10 text-center text-zinc-500">Источников пока нет. Добавьте камеру, видео или папку кадров.</td></tr>`}</tbody></table><div class="flex justify-between items-center border-t border-zinc-800 px-4 py-3 text-[11px] text-zinc-500"><span>${list.length ? (ui.cameraPage - 1) * 12 + 1 : 0}–${Math.min(ui.cameraPage * 12, list.length)} из ${list.length}</span><div class="flex items-center gap-2"><button id="camera-prev" class="rounded border border-zinc-700 px-2 py-1" ${ui.cameraPage <= 1 ? "disabled" : ""}>←</button><span>${ui.cameraPage} / ${Math.max(1, Math.ceil(list.length / 12))}</span><button id="camera-next" class="rounded border border-zinc-700 px-2 py-1" ${ui.cameraPage >= Math.ceil(list.length / 12) ? "disabled" : ""}>→</button></div></div></div></div>`;
    host.querySelector("#camera-search")?.addEventListener("input", (event) => { ui.query = event.target.value; ui.cameraPage = 1; renderCameras(); });
    host.querySelector("#camera-project")?.addEventListener("change", (event) => { ui.project = event.target.value; ui.cameraPage = 1; renderCameras(); });
    host.querySelector("#camera-prev")?.addEventListener("click", () => { ui.cameraPage -= 1; renderCameras(); });
    host.querySelector("#camera-next")?.addEventListener("click", () => { ui.cameraPage += 1; renderCameras(); });
    host.querySelectorAll("[data-camera-use]").forEach((button) => button.addEventListener("click", () => { ui.selectedCameras = new Set([button.dataset.cameraUse]); ui.wizardStep = 0; ui.page = "new"; renderCenter(); }));
    host.querySelector("#camera-add-source")?.addEventListener("click", () => openAddSource());
  }

  function openAddSource() {
    const host = document.getElementById("stream-center-content");
    host.innerHTML = `<div class="p-5 md:p-7 max-w-3xl mx-auto"><button id="add-source-back" class="text-xs text-zinc-500 hover:text-white">← К каталогу</button><h1 class="text-2xl font-semibold mt-3">Добавить источник</h1><p class="text-sm text-zinc-400 mt-1">Источник появится в каталоге проекта. Сбор запускается отдельно.</p><div class="mt-5 rounded-xl border border-zinc-800 bg-zinc-900/50 p-5 space-y-4"><label class="block text-xs">Проект<select id="add-source-project" class="mt-2 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2">${projectOptions(ui.project || projects[0]?.id)}</select></label><label class="block text-xs">Тип источника<select id="add-source-type" class="mt-2 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2"><option value="RTSP">RTSP-камера</option><option value="DEVICE">Веб-камера устройства</option><option value="VIDEO_FILE">Видеофайл</option><option value="IMAGE_FOLDER">Папка с изображениями</option></select></label><label class="block text-xs">Название<input id="add-source-name" placeholder="Например: Ворота / Север" class="mt-2 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2"></label><div id="add-source-rtsp-fields"><label class="block text-xs">RTSP адрес<input id="add-source-url" placeholder="rtsp://пользователь:пароль@камера/live" class="mt-2 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 font-mono"></label></div><div id="add-source-device-fields" class="hidden"><label class="block text-xs">Индекс устройства<input id="add-source-device" type="number" min="0" value="0" class="mt-2 w-28 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2"></label></div><div id="add-source-folder-fields" class="hidden"><label class="block text-xs">Путь к папке<input id="add-source-folder" placeholder="C:\\images" class="mt-2 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2"></label><button id="add-source-pick-folder" class="mt-2 rounded-lg border border-zinc-700 px-3 py-2 text-xs">Выбрать папку…</button></div><div id="add-source-video-fields" class="hidden"><label class="block text-xs">Видеофайл<input id="add-source-video" type="file" accept=".mp4,.avi,.mov,.mkv,video/*" class="mt-2 block w-full text-xs text-zinc-400"></label></div><div class="flex justify-end"><button id="add-source-save" class="rounded-lg bg-indigo-600 px-4 py-2 text-xs text-white">Добавить источник</button></div></div></div>`;
    host.querySelector("#add-source-back").onclick = () => setPage("cameras");
    host.querySelector("#add-source-type").onchange = (event) => {
      const type = event.target.value;
      host.querySelector("#add-source-rtsp-fields").classList.toggle("hidden", type !== "RTSP");
      host.querySelector("#add-source-device-fields").classList.toggle("hidden", type !== "DEVICE");
      host.querySelector("#add-source-folder-fields").classList.toggle("hidden", type !== "IMAGE_FOLDER");
      host.querySelector("#add-source-video-fields").classList.toggle("hidden", type !== "VIDEO_FILE");
    };
    host.querySelector("#add-source-pick-folder").onclick = async () => {
      const projectId = host.querySelector("#add-source-project").value;
      const button = host.querySelector("#add-source-pick-folder");
      button.disabled = true;
      try {
        const stream = await api.pickImageFolderStream(projectId);
        if (stream) { await refresh(); setPage("cameras"); toast("Папка добавлена"); }
      } catch (error) { toast(error.message); }
      finally { button.disabled = false; }
    };
    host.querySelector("#add-source-save").onclick = async (event) => {
      const button = event.currentTarget;
      const type = host.querySelector("#add-source-type").value;
      const projectId = host.querySelector("#add-source-project").value;
      const name = host.querySelector("#add-source-name").value.trim();
      if (!name) { toast("Введите название источника"); return; }
      button.disabled = true;
      try {
        if (type === "RTSP") {
          const url = host.querySelector("#add-source-url").value.trim();
          if (!url) throw new Error("Укажите RTSP адрес");
          await api.createRtspStream(projectId, { name, rtsp_url: url });
        } else if (type === "DEVICE") {
          await api.createDeviceStream(projectId, { name, device_index: Number(host.querySelector("#add-source-device").value || 0) });
        } else if (type === "VIDEO_FILE") {
          const file = host.querySelector("#add-source-video").files?.[0];
          if (!file) throw new Error("Выберите видеофайл");
          await api.uploadStreamVideo(projectId, file, name);
        } else {
          const folder = host.querySelector("#add-source-folder").value.trim();
          if (!folder) throw new Error("Укажите путь к папке или нажмите «Выбрать папку»");
          await api.createImageFolderStream(projectId, { name, folder_path: folder });
        }
        ui.project = projectId;
        await refresh();
        setPage("cameras");
        toast("Источник добавлен. Запуск сбора — отдельно в мастере.");
      } catch (error) { toast(error.message); button.disabled = false; }
    };
  }

  function renderModels() {
    const host = document.getElementById("stream-center-content");
    const all = allModels().filter((model) => { const project = projects.find((item) => item.id === model.project_id); const query = ui.query.trim().toLowerCase(); return (!ui.project || model.project_id === ui.project) && (!query || `${model.name} ${model.display_name} ${project?.name || ""} ${model.version_number}`.toLowerCase().includes(query)); });
    host.innerHTML = `<div class="p-5 md:p-7 max-w-[1500px] mx-auto space-y-5"><div><h1 class="text-2xl font-semibold">Модели</h1><p class="text-sm text-zinc-400 mt-1">Каталог версий моделей из всех проектов. Сбор использует модель проекта назначения.</p></div><div class="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4"><div class="text-xs text-zinc-500">Доступно моделей</div><div class="text-2xl mt-1">${allModels().length}</div><div class="text-[11px] text-zinc-500">${projects.length} проектов · выбор и проверка совместимости доступны в мастере</div></div><div class="flex flex-wrap gap-2"><input id="model-search" class="w-full sm:w-72 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs" value="${escapeAttribute(ui.query)}" placeholder="Название модели или версия…"><select id="model-project-filter" class="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs">${projectOptions(ui.project, true)}</select></div><div class="rounded-xl border border-zinc-800 overflow-x-auto"><table class="w-full text-left text-xs"><thead class="bg-zinc-900 text-[10px] uppercase text-zinc-500"><tr><th class="px-4 py-3">Модель</th><th class="px-4 py-3">Проект</th><th class="px-4 py-3">Версия</th><th class="px-4 py-3">mAP50</th><th class="px-4 py-3">Используется в сборах</th></tr></thead><tbody>${all.slice((ui.modelPage - 1) * 15, ui.modelPage * 15).map((model) => { const project = projects.find((item) => item.id === model.project_id); const used = streams.filter((stream) => stream.model_version_id === model.id).length; return `<tr class="border-t border-zinc-800"><td class="px-4 py-3 font-medium">${escapeHtml(model.display_name || model.name)}${model.is_active_for_stream ? '<span class="ml-2 rounded bg-indigo-950 px-1.5 py-0.5 text-[10px] text-indigo-200">Активная</span>' : ""}</td><td class="px-4 py-3 text-indigo-300">${escapeHtml(project?.name || "Проект удалён")}</td><td class="px-4 py-3">v${Number(model.version_number)}</td><td class="px-4 py-3">${model.map50 == null ? "—" : `${(Number(model.map50) * 100).toFixed(1)}%`}</td><td class="px-4 py-3">${used || "—"}</td></tr>`; }).join("") || `<tr><td colspan="5" class="p-10 text-center text-zinc-500">Модели не найдены</td></tr>`}</tbody></table><div class="flex justify-between items-center border-t border-zinc-800 px-4 py-3 text-[11px] text-zinc-500"><span>${all.length} моделей · ${ui.modelPage} / ${Math.max(1, Math.ceil(all.length / 15))}</span><div class="flex items-center gap-2"><button id="model-prev" class="rounded border border-zinc-700 px-2 py-1" ${ui.modelPage <= 1 ? "disabled" : ""}>←</button><button id="model-next" class="rounded border border-zinc-700 px-2 py-1" ${ui.modelPage >= Math.ceil(all.length / 15) ? "disabled" : ""}>→</button></div></div></div></div>`;
    host.querySelector("#model-search")?.addEventListener("input", (event) => { ui.query = event.target.value; ui.modelPage = 1; renderModels(); });
    host.querySelector("#model-project-filter")?.addEventListener("change", (event) => { ui.project = event.target.value; ui.modelPage = 1; renderModels(); });
    host.querySelector("#model-prev")?.addEventListener("click", () => { ui.modelPage -= 1; renderModels(); });
    host.querySelector("#model-next")?.addEventListener("click", () => { ui.modelPage += 1; renderModels(); });
  }

  async function loadSelectedProject() {
    const project = selectedProject();
    if (!project) { models = []; classes = []; return; }
    const [modelList, classList] = await Promise.all([
      api.listModels(project.id).catch(() => []),
      api.listClasses(project.id).catch(() => []),
    ]);
    models = modelList || [];
    classes = classList || [];
    fillFormFromSelected();
  }

  async function refresh({ light = false } = {}) {
    let centerPage = ui.page;
    if (!light) {
      const query = new URLSearchParams(location.hash.split("?")[1] || "");
      if (query.get("source") && query.get("project")) {
        ui.project = query.get("project");
        ui.selectedCameras = new Set([query.get("source")]);
        ui.page = "new"; ui.wizardStep = 1; centerPage = "new";
        history.replaceState(null, "", `${location.pathname}${location.search}#/streams`);
      }
    }
    if (!light || !projects.length) projects = await api.listProjects();
    const destination = document.getElementById("stream-destination-project");
    if (destination) {
      const previous = destination.value;
      destination.innerHTML = projects.map((project) => `<option value="${project.id}">${escapeHtml(project.name)}</option>`).join("");
      destination.value = projects.some((project) => project.id === previous) ? previous : (projects.some((project) => project.id === currentProjectId()) ? currentProjectId() : projects[0]?.id || "");
      destination.disabled = projects.length === 0;
    }
    const streamLists = await Promise.all(projects.map((project) => api.listStreams(project.id).catch(() => [])));
    streams = streamLists.flat().sort((left, right) => {
      const currentId = currentProjectId();
      const currentRank = (stream) => stream.project_id === currentId ? 0 : 1;
      return currentRank(left) - currentRank(right) || Number(right.is_active) - Number(left.is_active);
    });
    const summary = document.getElementById("stream-summary");
    const activeCount = streams.filter((stream) => stream.is_active).length;
    if (summary) summary.textContent = `${activeCount} источников собирают кадры · ${streams.length} всего · потоки могут работать в разных проектах одновременно.`;
    if (!selectedId && streams[0]) selectedId = streams[0].id;
    if (selectedId && !streams.some((s) => s.id === selectedId)) {
      selectedId = streams[0]?.id || null;
    }
    if (!light) await loadSelectedProject();
    const s = selected();
    line = s?.config?.tripwire_line || null;
    renderList();
    fillFormFromSelected();
    drawLineOverlay();
    const running = Boolean(s?.is_active);
    const capturedLabel = document.getElementById("stream-captured-count");
    if (capturedLabel) capturedLabel.textContent = String(statuses.get(s?.id)?.captured_count ?? s?.captured_frames_count ?? 0);
    syncLiveImage(running);
    ensurePoll(streams.some((item) => item.is_active));
    if (!light) await loadCatalogs();
    if (ui.page === centerPage && ui.page !== "detail" && !document.activeElement?.closest("#stream-center-content input, #stream-center-content select, #stream-center-content textarea")) renderCenter();
    else if (ui.page === "detail") refreshDetailStatus();
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(() => { if (ui.page !== "new") refresh({ light: true }).catch(() => {}); }, 10000);
    refreshIcons();
  }

  async function pollStatus() {
    if (pollInFlight) return;
    pollInFlight = true;
    const monitored = streams.filter((stream) => stream.is_active || stream.id === selectedId);
    await Promise.all(monitored.map(async (stream) => {
      try {
      const st = await api.getStreamStatus(stream.id);
      statuses.set(stream.id, st);
      if (stream.id !== selectedId) return;
      const fpsEl = els.fps();
      if (fpsEl) {
        if (st.state === "error" || st.state === "reconnecting") {
          fpsEl.textContent = st.error_message
            ? `${st.state}: ${st.error_message}`
            : String(st.state);
        } else {
          fpsEl.textContent = `FPS: ${Number(st.fps || 0).toFixed(1)}`;
        }
      }
      if (els.captured()) els.captured().textContent = String(st.captured_count ?? 0);
      if ((st.captured_count || 0) > lastCaptured) {
        flashCapture();
        lastCaptured = st.captured_count || 0;
      }
      const running = Boolean(st.is_running) && st.state !== "error";
      syncLiveImage(running);
      } catch {
        /* ignore transient */
      }
    }));
    const center = document.getElementById("view-stream-center");
    if (!center || center.classList.contains("hidden")) renderList();
    refreshDetailStatus();
    if (center && !center.classList.contains("hidden") && ui.page !== "detail" && ui.page !== "new" && !document.activeElement?.closest("#stream-center-content input, #stream-center-content select, #stream-center-content textarea")) renderCenter();
    ensurePoll(streams.some((stream) => stream.is_active || ["starting", "reconnecting"].includes(statuses.get(stream.id)?.state)));
    pollInFlight = false;
  }

  document.getElementById("stream-destination-project")?.addEventListener("change", () => {
    const projectId = destinationProjectId();
    const project = projects.find((item) => item.id === projectId);
    const name = document.getElementById("stream-rtsp-name");
    if (name && !name.value.trim()) name.placeholder = `Источник · ${project?.name || "проект"}`;
  });

  document.getElementById("btn-stream-add-rtsp")?.addEventListener("click", async () => {
    try {
      const projectId = destinationProjectId();
      if (!projectId) throw new Error("Сначала откройте проект");
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
      const projectId = destinationProjectId();
      if (!projectId) throw new Error("Сначала откройте проект");
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

  async function addImageFolderFromPath(folder_path) {
    const projectId = destinationProjectId();
    if (!projectId) throw new Error("Сначала откройте проект");
    const fallback = folder_path.split(/[\\/]/).filter(Boolean).pop() || "Папка";
    const name = document.getElementById("stream-rtsp-name")?.value?.trim() || fallback;
    const created = await api.createImageFolderStream(projectId, { name, folder_path });
    selectedId = created.id;
    const input = document.getElementById("stream-image-folder-path");
    if (input) input.value = created.source_uri || folder_path;
    await refresh();
    toast("Папка добавлена. Нажмите «Запустить», чтобы показать кадры.", 6000);
  }

  document.getElementById("btn-stream-add-image-folder")?.addEventListener("click", async () => {
    const btn = document.getElementById("btn-stream-add-image-folder");
    if (btn?.disabled) return;
    try {
      const projectId = destinationProjectId();
      if (!projectId) throw new Error("Сначала откройте проект");
      if (btn) btn.disabled = true;
      toast("Откроется окно выбора папки.", 4000);
      const created = await api.pickImageFolderStream(projectId);
      if (!created) {
        toast("Выбор папки отменён");
        return;
      }
      selectedId = created.id;
      const input = document.getElementById("stream-image-folder-path");
      if (input && created.source_uri) input.value = created.source_uri;
      await refresh();
      toast("Папка добавлена. Нажмите «Запустить», чтобы показать кадры.", 6000);
    } catch (err) {
      toast(err.message || "Не удалось добавить папку", 8000);
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  document.getElementById("stream-image-folder-path")?.addEventListener("keydown", async (ev) => {
    if (ev.key !== "Enter") return;
    ev.preventDefault();
    const folder_path = ev.currentTarget.value.trim();
    if (!folder_path) return;
    try {
      await addImageFolderFromPath(folder_path);
    } catch (err) {
      toast(err.message || "Не удалось добавить папку", 8000);
    }
  });

  document.getElementById("stream-video-input")?.addEventListener("change", async (ev) => {
    const file = ev.target.files?.[0];
    if (!file) return;
    try {
      const projectId = destinationProjectId();
      if (!projectId) throw new Error("Сначала откройте проект");
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

  [
    "stream-track-stable-n",
    "stream-track-stable-size",
    "stream-track-stable-interval",
    "stream-conf-min",
    "stream-conf-max",
    "stream-timer-interval",
    "stream-capture-mode",
    "stream-tripwire-direction",
    "stream-model-select",
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (id === "stream-capture-mode") {
      el?.addEventListener("change", () => {
        syncCaptureMode();
        scheduleSaveTriggers();
      });
    } else if (id === "stream-conf-min" || id === "stream-conf-max") {
      el?.addEventListener("input", (e) => {
        const label = document.getElementById(id + "-label");
        if (label) label.textContent = Math.round(e.target.value * 100);
        scheduleSaveTriggers();
      });
    } else {
      el?.addEventListener("change", scheduleSaveTriggers);
      el?.addEventListener("input", scheduleSaveTriggers);
    }
  });

  document.querySelectorAll('input[name="stream_trigger"]').forEach(el => {
    el.addEventListener("change", () => {
      syncCaptureMode();
      scheduleSaveTriggers();
    });
  });

  document.getElementById("btn-stream-start")?.addEventListener("click", async () => {
    const btn = document.getElementById("btn-stream-start");
    if (btn?.disabled) return;
    try {
      if (!selectedId) throw new Error("Выберите источник");
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Запуск…";
      }
      await saveTriggers({ quiet: true });
      await api.startStream(selectedId);
      await refresh();
      toast("Стрим запущен");
    } catch (err) {
      toast(err.message);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Запустить";
      }
    }
  });

  document.getElementById("btn-stream-stop")?.addEventListener("click", async () => {
    try {
      if (!selectedId) return;
      await api.stopStream(selectedId);
      stopPoll();
      syncLiveImage(false);
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
    const project = selectedProject();
    if (!project) return;
    const timer = els.captureMode()?.value === "TIMER";
    const images = store.get("images") || [];
    store.set("filmstripFilter", timer ? "unannotated" : "review");
    const target = timer
      ? images.find((image) => image.status === "UNANNOTATED") || null
      : firstReviewImage(images);
    navigate(projectPath(project.id, "annotate", project.id === currentProjectId() ? target?.id || null : null));
  });

  document.querySelectorAll(".collection-nav").forEach((button) => {
    button.addEventListener("click", () => setPage(button.dataset.collectionPage));
  });
  document.getElementById("collection-new-button")?.addEventListener("click", () => {
    ui.page = "new";
    ui.wizardStep = 0;
    ui.selectedCameras.clear();
    ui.collectionName = "";
    ui.diagnostic = false;
    renderCenter();
  });

  const canvas = els.canvas();
  canvas?.addEventListener("mousedown", (ev) => {
    if (drawMode) return;
    const hit = endpointHits(ev);
    if (hit === null) return;
    dragEndpoint = hit;
    ev.preventDefault();
  });
  canvas?.addEventListener("mousemove", (ev) => {
    if (dragEndpoint === null || !line) return;
    const [x, y] = normFromClient(ev);
    const next = [...line];
    if (dragEndpoint === 0) {
      next[0] = x;
      next[1] = y;
    } else {
      next[2] = x;
      next[3] = y;
    }
    line = next;
    drawLineOverlay();
  });
  const endDrag = () => {
    if (dragEndpoint === null) return;
    dragEndpoint = null;
    saveTriggers({ quiet: true }).catch((err) => toast(err.message));
  };
  canvas?.addEventListener("mouseup", endDrag);
  canvas?.addEventListener("mouseleave", endDrag);

  canvas?.addEventListener("click", (ev) => {
    if (!drawMode) return;
    const [x, y] = normFromClient(ev);
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
    saveTriggers({ quiet: true }).catch((err) => toast(err.message));
  });

  els.img()?.addEventListener("load", () => drawLineOverlay());

  window.addEventListener("resize", () => drawLineOverlay());

  return {
    refresh,
    destroy() {
      stopPoll();
      if (refreshTimer) clearInterval(refreshTimer);
      refreshTimer = null;
      if (saveTimer) clearTimeout(saveTimer);
      syncLiveImage(false);
    },
  };
}
