import { api } from "../api.js";
import { showModal, refreshIcons } from "../utils/dom.js";

const PRETRAINED_OPTIONS = [
  { value: "pretrained:yolov8n.pt", label: "YOLOv8n (pretrained)" },
  { value: "pretrained:yolov8s.pt", label: "YOLOv8s (pretrained)" },
  { value: "pretrained:yolov8m.pt", label: "YOLOv8m (pretrained)" },
];

function drawSeries(canvas, values, color) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#18181b";
  ctx.fillRect(0, 0, w, h);
  if (!values.length) return;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = (index / Math.max(values.length - 1, 1)) * (w - 16) + 8;
    const y = h - 8 - ((value - min) / span) * (h - 16);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function parseBaseModelSelection(raw) {
  if (!raw) return { base_weights: "yolov8n.pt" };
  if (raw.startsWith("pretrained:")) {
    return { base_weights: raw.slice("pretrained:".length) };
  }
  if (raw.startsWith("model:")) {
    return { base_model_version_id: raw.slice("model:".length) };
  }
  return { base_weights: "yolov8n.pt" };
}

function deviceBadgeClass(backend) {
  return backend === "gpu"
    ? "rounded-md border border-emerald-700/60 bg-emerald-950/40 px-3 py-2 text-xs text-emerald-200"
    : "rounded-md border border-amber-700/60 bg-amber-950/40 px-3 py-2 text-xs text-amber-100";
}

function applyDeviceBadge(el, info) {
  if (!el || !info) return;
  el.className = deviceBadgeClass(info.backend);
  el.textContent =
    info.backend === "gpu"
      ? `Обучение на GPU · ${info.label}`
      : `Обучение на CPU · ${info.label}`;
}

export function initTrainingDrawer({
  getProject,
  onError,
  onStarted,
  onCompleted,
  onFailed,
  onUseForAutoLabel,
}) {
  const drawer = document.getElementById("training-drawer");
  const setup = document.getElementById("training-setup");
  const live = document.getElementById("training-live");
  let pollTimer = null;
  let lastModelId = null;
  let terminalNotifiedJobId = null;

  function close() {
    // Keep polling after close so completion/failure still surfaces via toast/OS notify.
    showModal(drawer, false);
  }

  async function fillSelectors(projectId, preferredDatasetId = null) {
    const [versions, models, device] = await Promise.all([
      api.listDatasetVersions(projectId),
      api.listModels(projectId).catch(() => []),
      api.getTrainingDevice().catch(() => ({
        backend: "cpu",
        label: "CPU",
        device: "cpu",
      })),
    ]);
    applyDeviceBadge(document.getElementById("train-device-badge"), device);

    const datasetSelect = document.getElementById("train-dataset-version");
    const ready = (versions || []).filter((item) => item.status === "READY");
    datasetSelect.innerHTML = ready.length
      ? ready
          .map(
            (item) =>
              `<option value="${item.id}">${item.name} (v${item.version_number}) · train ${item.train_count}</option>`
          )
          .join("")
      : `<option value="">Нет READY датасетов</option>`;
    if (preferredDatasetId && ready.some((item) => item.id === preferredDatasetId)) {
      datasetSelect.value = preferredDatasetId;
    }

    const baseSelect = document.getElementById("train-base-model");
    const pretrained = PRETRAINED_OPTIONS.map(
      (item) => `<option value="${item.value}">${item.label}</option>`
    ).join("");
    const projectModels = (models || [])
      .map(
        (item) =>
          `<option value="model:${item.id}">${item.display_name} · дообучить</option>`
      )
      .join("");
    baseSelect.innerHTML =
      `<optgroup label="Pretrained">${pretrained}</optgroup>` +
      (projectModels
        ? `<optgroup label="Модели проекта">${projectModels}</optgroup>`
        : `<optgroup label="Модели проекта"><option value="" disabled>Пока нет обученных моделей</option></optgroup>`);
  }

  function open(datasetVersionId = null) {
    const project = getProject();
    if (!project) {
      onError?.("Сначала откройте проект");
      return;
    }
    showModal(drawer, true);
    refreshIcons();
    // Re-open while a job is still polling: keep the live progress view.
    if (pollTimer) {
      setup?.classList.add("hidden");
      live?.classList.remove("hidden");
      return;
    }
    document.getElementById("train-complete-badge")?.classList.add("hidden");
    document.getElementById("train-error")?.classList.add("hidden");
    live?.classList.add("hidden");
    setup?.classList.remove("hidden");
    fillSelectors(project.id, datasetVersionId).catch((err) => onError?.(err.message));
  }

  function renderJob(job) {
    live?.classList.remove("hidden");
    const liveDevice = document.getElementById("train-live-device");
    if (liveDevice) {
      const label = job.device_label || job.device || "—";
      const isGpu = String(job.device || "").toLowerCase() !== "cpu";
      liveDevice.textContent = isGpu
        ? `Идёт обучение на GPU · ${label}`
        : `Идёт обучение на CPU · ${label}`;
      liveDevice.className = isGpu
        ? "inline-flex items-center rounded border border-emerald-700/60 bg-emerald-950/40 px-2 py-1 text-[11px] text-emerald-200"
        : "inline-flex items-center rounded border border-amber-700/60 bg-amber-950/40 px-2 py-1 text-[11px] text-amber-100";
    }
    const epochText = document.getElementById("train-epoch-text");
    const patienceLive = document.getElementById("train-patience-live");
    const bar = document.getElementById("train-progress-bar");
    const patience = job.patience ?? 20;
    if (job.status === "COMPLETED" && job.stopped_early) {
      epochText.textContent = `Остановлено на эпохе ${job.current_epoch} / ${job.epochs} (early stop)`;
    } else {
      epochText.textContent = `Эпоха ${job.current_epoch} / ${job.epochs}`;
    }
    if (patienceLive) {
      patienceLive.textContent =
        patience > 0 ? `patience ${patience}` : "early stop выкл.";
    }
    bar.style.width = `${job.progress_percent || 0}%`;
    const history = job.metrics_history || [];
    drawSeries(
      document.getElementById("chart-loss"),
      history.map((item) => Number(item.train_loss ?? item.val_loss ?? 0)),
      "#a78bfa"
    );
    drawSeries(
      document.getElementById("chart-map"),
      history.map((item) => Number(item.map50 ?? 0)),
      "#34d399"
    );
    if (job.status === "FAILED") {
      const err = document.getElementById("train-error");
      err.classList.remove("hidden");
      err.textContent = job.error_message || "Обучение завершилось с ошибкой";
      if (terminalNotifiedJobId !== job.id) {
        terminalNotifiedJobId = job.id;
        onFailed?.(job);
      }
    }
    if (job.status === "COMPLETED") {
      lastModelId = job.model_version_id;
      const badge = document.getElementById("train-complete-badge");
      badge.classList.remove("hidden");
      const last = history[history.length - 1] || {};
      const map50 = last.map50 != null ? Number(last.map50) : null;
      const score = map50 != null ? `mAP@50: ${map50.toFixed(3)}` : "Метрики сохранены";
      const early = job.stopped_early
        ? ` · early stop на эпохе ${job.current_epoch}`
        : ` · эпох: ${job.current_epoch}/${job.epochs}`;
      document.getElementById("train-final-score").textContent = `${score}${early}`;
      if (terminalNotifiedJobId !== job.id) {
        terminalNotifiedJobId = job.id;
        onCompleted?.(job);
      }
    }
  }

  document.getElementById("train-patience")?.addEventListener("input", (event) => {
    document.getElementById("train-patience-label").textContent = event.target.value;
  });
  document.getElementById("btn-close-training")?.addEventListener("click", close);
  document.getElementById("btn-start-training")?.addEventListener("click", async () => {
    const project = getProject();
    const versionId = document.getElementById("train-dataset-version")?.value;
    const baseRaw = document.getElementById("train-base-model")?.value;
    const epochs = Number(document.getElementById("train-epochs")?.value || 100);
    const patience = Number(document.getElementById("train-patience")?.value || 20);
    if (!Number.isFinite(epochs) || epochs < 1 || epochs > 500) {
      onError?.("Эпохи: целое число от 1 до 500");
      return;
    }
    if (!project || !versionId) {
      onError?.("Выберите READY версию датасета");
      return;
    }
    if (!baseRaw) {
      onError?.("Выберите исходную модель");
      return;
    }
    try {
      onStarted?.();
      const job = await api.startTraining(project.id, {
        dataset_version_id: versionId,
        epochs,
        patience,
        ...parseBaseModelSelection(baseRaw),
      });
      terminalNotifiedJobId = null;
      setup?.classList.add("hidden");
      live?.classList.remove("hidden");
      renderJob(job);
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(async () => {
        try {
          const next = await api.getTrainingJob(job.id);
          renderJob(next);
          if (next.status === "COMPLETED" || next.status === "FAILED") {
            clearInterval(pollTimer);
            pollTimer = null;
          }
        } catch (err) {
          onError?.(err.message);
        }
      }, 1500);
    } catch (err) {
      onError?.(err.message);
    }
  });
  document.getElementById("btn-use-model-autolabel")?.addEventListener("click", () => {
    close();
    onUseForAutoLabel?.(lastModelId);
  });

  return { open, close };
}
