import { api } from "../api.js";
import { isClassification } from "../store.js";
import { escapeHtml, formatRelative, refreshIcons, showModal } from "../utils/dom.js";

function pct(value) {
  if (value == null || Number.isNaN(Number(value))) return null;
  return Number(value) * 100;
}

function formatPct(value) {
  const n = pct(value);
  return n == null ? "—" : `${n.toFixed(1)}%`;
}

function weightsLabel(path) {
  if (!path) return "yolov8n";
  const base = String(path).split(/[/\\]/).pop() || path;
  return base;
}

function formatTestLine(model, classification) {
  const metrics = model.test_metrics;
  if (!metrics) return "Тест: —";
  if (classification && metrics.top1 != null) return `Тест Top-1 ${formatPct(metrics.top1)}`;
  if (metrics.map50 != null) {
    return `Тест mAP@50 ${formatPct(metrics.map50)} · P ${formatPct(metrics.precision)} · R ${formatPct(metrics.recall)}`;
  }
  if (metrics.top1 != null) return `Тест Top-1 ${formatPct(metrics.top1)}`;
  return "Тест: —";
}

function metricBar(map50) {
  const n = pct(map50);
  if (n == null) return "";
  const width = Math.max(0, Math.min(100, n));
  return `
    <div class="h-1 rounded-full bg-zinc-950 border border-zinc-800 overflow-hidden mt-0.5">
      <div class="h-full bg-emerald-500 rounded-full" style="width:${width}%"></div>
    </div>`;
}

function statusBadge(status) {
  const value = String(status || "").toUpperCase();
  if (value === "READY") {
    return "bg-emerald-950 text-emerald-400 border-emerald-800/50";
  }
  if (value === "BUILDING" || value === "PENDING" || value === "PREPARING") {
    return "bg-amber-950 text-amber-400 border-amber-800/50";
  }
  if (value === "FAILED" || value === "ERROR") {
    return "bg-red-950 text-red-400 border-red-800/50";
  }
  return "bg-zinc-900 text-zinc-400 border-zinc-700";
}

function datasetRootFromYaml(yamlPath) {
  if (!yamlPath) return "—";
  const normalized = String(yamlPath).replace(/\\/g, "/");
  const idx = normalized.lastIndexOf("/");
  return idx >= 0 ? normalized.slice(0, idx) : normalized;
}

function actionBtn(attrs, label, icon, extraClass = "") {
  return `
    <button type="button" ${attrs}
      class="px-2 py-1 text-[10px] rounded-md border border-zinc-700 hover:bg-zinc-800 text-zinc-200 flex items-center justify-center gap-1 ${extraClass}">
      <i data-lucide="${icon}" class="w-3 h-3"></i>
      ${label}
    </button>`;
}

function downloadBlob({ blob, filename }) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "download.zip";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function renderDatasets(versions, handlers) {
  const grid = document.getElementById("datasets-list-grid");
  const empty = document.getElementById("datasets-empty");
  const countLabel = document.getElementById("datasets-count-label");
  if (!grid || !empty) return;

  if (countLabel) countLabel.textContent = `${versions.length} версий`;

  const has = versions.length > 0;
  empty.classList.toggle("hidden", has);
  grid.classList.toggle("hidden", !has);

  if (!has) {
    grid.innerHTML = "";
    refreshIcons(empty);
    return;
  }

  grid.innerHTML = versions
    .map((version) => {
      const ready = String(version.status || "").toUpperCase() === "READY";
      const root = datasetRootFromYaml(version.yaml_path);
      const aug = version.augmentation || {};
      const augBits = [
        `${aug.resize_width || 640}×${aug.resize_height || 640}`,
        aug.horizontal_flip ? "hflip" : null,
        aug.vertical_flip ? "vflip" : null,
        aug.rotate ? "rot" : null,
        aug.shear ? "shear" : null,
        aug.hue_saturation ? "hsv" : null,
        aug.brightness_contrast ? "bc" : null,
        aug.blur ? "blur" : null,
        aug.noise ? "noise" : null,
        aug.grayscale ? "gray" : null,
        aug.cutout ? "cutout" : null,
        aug.multiplier ? `×${aug.multiplier}` : null,
      ].filter(Boolean);
      return `
        <article class="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 space-y-2">
          <div class="flex items-center justify-between gap-2 min-w-0">
            <div class="flex items-center gap-1.5 min-w-0">
              <h3 class="text-xs font-semibold text-zinc-100 truncate">${escapeHtml(version.name || `v${version.version_number}`)}</h3>
              <span class="px-1 py-0.5 text-[9px] rounded border shrink-0 ${statusBadge(version.status)}">${escapeHtml(version.status || "—")}</span>
              <span class="text-[9px] font-mono text-zinc-500 shrink-0">v${version.version_number}</span>
            </div>
            <span class="text-[9px] text-zinc-500 whitespace-nowrap shrink-0">${escapeHtml(formatRelative(version.created_at))}</span>
          </div>

          <div class="flex items-center gap-2 text-[10px] font-mono text-zinc-300">
            <span title="Train images / files">T ${version.train_count ?? 0}/${version.train_file_count ?? 0}</span>
            <span class="text-zinc-700">·</span>
            <span title="Valid">V ${version.valid_count ?? 0}/${version.valid_file_count ?? 0}</span>
            <span class="text-zinc-700">·</span>
            <span title="Test">Te ${version.test_count ?? 0}/${version.test_file_count ?? 0}</span>
            ${
              augBits.length
                ? `<span class="text-zinc-600 truncate">· ${escapeHtml(augBits.join(" "))}</span>`
                : ""
            }
          </div>

          <div class="rounded border border-zinc-800 bg-zinc-950 px-2 py-1 font-mono text-[10px] text-emerald-300/90 truncate select-text" title="${escapeHtml(root)}">
            ${escapeHtml(root)}
          </div>

          <div class="grid grid-cols-2 gap-1.5">
            ${actionBtn(`data-rename-dataset="${version.id}" data-name="${escapeHtml(version.name || "")}"`, "Переименовать", "pencil")}
            ${actionBtn(
              `data-export-dataset="${version.id}" ${ready ? "" : "disabled"}`,
              "Выгрузить",
              "download",
              ready ? "" : "opacity-40 cursor-not-allowed"
            )}
            ${actionBtn(`data-delete-dataset="${version.id}" data-name="${escapeHtml(version.name || "")}"`, "Удалить", "trash-2", "text-red-300 border-red-900/50 hover:bg-red-950/40")}
            <button type="button" data-train-dataset="${version.id}" ${ready ? "" : "disabled"}
              class="px-2 py-1 text-[10px] rounded-md flex items-center justify-center gap-1 ${
                ready
                  ? "bg-violet-700 hover:bg-violet-600 text-white"
                  : "bg-zinc-800 text-zinc-500 cursor-not-allowed"
              }">
              <i data-lucide="brain" class="w-3 h-3"></i>
              ${ready ? "Обучить" : "Не READY"}
            </button>
          </div>
        </article>`;
    })
    .join("");

  grid.querySelectorAll("[data-train-dataset]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      handlers.onTrainDataset?.(btn.dataset.trainDataset);
    });
  });
  grid.querySelectorAll("[data-rename-dataset]").forEach((btn) => {
    btn.addEventListener("click", () =>
      handlers.onRenameDataset?.(btn.dataset.renameDataset, btn.dataset.name || "")
    );
  });
  grid.querySelectorAll("[data-export-dataset]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      handlers.onExportDataset?.(btn.dataset.exportDataset);
    });
  });
  grid.querySelectorAll("[data-delete-dataset]").forEach((btn) => {
    btn.addEventListener("click", () =>
      handlers.onDeleteDataset?.(btn.dataset.deleteDataset, btn.dataset.name || "")
    );
  });
  refreshIcons(grid);
}

function renderModels(models, handlers) {
  const grid = document.getElementById("models-list-grid");
  const empty = document.getElementById("models-empty");
  const countLabel = document.getElementById("models-count-label");
  if (!grid || !empty) return;

  if (countLabel) countLabel.textContent = `${models.length} моделей`;

  const has = models.length > 0;
  empty.classList.toggle("hidden", has);
  grid.classList.toggle("hidden", !has);
  if (!has) {
    grid.innerHTML = "";
    refreshIcons(empty);
    return;
  }

  grid.innerHTML = models
    .map((model) => {
      const classification = isClassification();
      const metricLabel = classification ? "Top-1" : "mAP@50";
      const metricValue = classification ? formatPct(model.top1) : formatPct(model.map50);
      const metricBarValue = classification ? model.top1 : model.map50;
      return `
        <article class="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 space-y-2">
          <div class="flex items-center justify-between gap-2 min-w-0">
            <div class="min-w-0">
              <h3 class="text-xs font-semibold text-zinc-100 truncate">${escapeHtml(model.display_name || model.name || `Model v${model.version_number}`)}</h3>
              <p class="text-[10px] text-zinc-500 truncate">${escapeHtml(weightsLabel(model.weights_path))}</p>
            </div>
            <span class="text-[9px] text-zinc-500 whitespace-nowrap shrink-0">${escapeHtml(formatRelative(model.created_at))}</span>
          </div>
          <div>
            <div class="flex justify-between text-[10px]">
              <span class="text-zinc-400">${metricLabel}</span>
              <span class="font-mono text-emerald-400">${metricValue}</span>
            </div>
            ${metricBar(metricBarValue)}
          </div>
          <p class="text-[10px] font-mono text-fuchsia-300">${escapeHtml(formatTestLine(model, classification))}</p>
          ${
            classification
              ? ""
              : `<div class="flex items-center gap-2 text-[10px] font-mono text-zinc-400">
            <span>50-95 ${formatPct(model.map50_95)}</span>
            <span class="text-zinc-700">·</span>
            <span>P ${formatPct(model.precision)}</span>
            <span class="text-zinc-700">·</span>
            <span>R ${formatPct(model.recall)}</span>
          </div>`
          }
          <div class="grid grid-cols-2 gap-1.5">
            ${actionBtn(`data-rename-model="${model.id}" data-name="${escapeHtml(model.name || "")}"`, "Переименовать", "pencil")}
            ${actionBtn(`data-export-model="${model.id}"`, "Выгрузить", "download")}
            ${actionBtn(`data-delete-model="${model.id}" data-name="${escapeHtml(model.display_name || model.name || "")}"`, "Удалить", "trash-2", "text-red-300 border-red-900/50 hover:bg-red-950/40")}
            <button type="button" data-use-model="${model.id}"
              class="px-2 py-1 text-[10px] rounded-md bg-amber-700 hover:bg-amber-600 text-white flex items-center justify-center gap-1">
              <i data-lucide="sparkles" class="w-3 h-3"></i>
              Авторазметка
            </button>
            ${
              classification
                ? ""
                : `<button type="button" data-audit-model="${model.id}"
              class="px-2 py-1 text-[10px] rounded-md border border-red-800/60 text-red-300 hover:bg-red-950/40 flex items-center justify-center gap-1">
              <i data-lucide="shield-alert" class="w-3 h-3"></i>
              Аудит разметки
            </button>`
            }
          </div>
        </article>`;
    })
    .join("");

  grid.querySelectorAll("[data-use-model]").forEach((btn) => {
    btn.addEventListener("click", () => handlers.onUseModel?.(btn.dataset.useModel));
  });
  grid.querySelectorAll("[data-audit-model]").forEach((btn) => {
    btn.addEventListener("click", () => handlers.onAuditModel?.(btn.dataset.auditModel));
  });
  grid.querySelectorAll("[data-rename-model]").forEach((btn) => {
    btn.addEventListener("click", () =>
      handlers.onRenameModel?.(btn.dataset.renameModel, btn.dataset.name || "")
    );
  });
  grid.querySelectorAll("[data-export-model]").forEach((btn) => {
    btn.addEventListener("click", () => handlers.onExportModel?.(btn.dataset.exportModel));
  });
  grid.querySelectorAll("[data-delete-model]").forEach((btn) => {
    btn.addEventListener("click", () =>
      handlers.onDeleteModel?.(btn.dataset.deleteModel, btn.dataset.name || "")
    );
  });
  refreshIcons(grid);
}

export function initModelsHub({
  getProject,
  onTrain,
  onTrainDataset,
  onAutoLabel,
  onUseModel,
  onAuditModel,
  onCreateDataset,
  onUploadModel,
  onError,
  onChanged,
}) {
  const openCreate = () => onCreateDataset?.();
  document.getElementById("btn-models-train")?.addEventListener("click", () => onTrain?.());
  document.getElementById("btn-models-autolabel")?.addEventListener("click", () => onAutoLabel?.());
  document.getElementById("btn-models-create-dataset")?.addEventListener("click", openCreate);
  document.getElementById("btn-models-create-dataset-inner")?.addEventListener("click", openCreate);

  const uploadInput = document.getElementById("model-upload-input");
  document.getElementById("btn-models-upload")?.addEventListener("click", () => {
    uploadInput?.click();
  });
  uploadInput?.addEventListener("change", async () => {
    const file = uploadInput.files?.[0];
    uploadInput.value = "";
    if (!file) return;
    try {
      await onUploadModel?.(file);
    } catch (err) {
      onError?.(err.message || String(err));
    }
  });

  const renameModal = document.getElementById("rename-asset-modal");
  const renameForm = document.getElementById("rename-asset-form");
  const renameInput = document.getElementById("rename-asset-input");
  const renameTitle = document.getElementById("rename-asset-title");
  const deleteModal = document.getElementById("delete-asset-modal");
  const deleteTitle = document.getElementById("delete-asset-title");
  const deleteText = document.getElementById("delete-asset-text");

  let pendingRename = null;
  let pendingDelete = null;
  let hub = null;

  function closeRename() {
    pendingRename = null;
    showModal(renameModal, false);
  }

  function closeDelete() {
    pendingDelete = null;
    showModal(deleteModal, false);
  }

  async function refresh() {
    const project = getProject?.();
    if (!project) {
      renderDatasets([], {});
      renderModels([], {});
      return;
    }
    try {
      const [versions, models] = await Promise.all([
        api.listDatasetVersions(project.id),
        api.listModels(project.id),
      ]);
      const sortedVersions = [...(versions || [])].sort(
        (a, b) => (b.version_number || 0) - (a.version_number || 0)
      );
      const handlers = {
        onTrainDataset,
        onUseModel,
        onAuditModel,
        onRenameDataset: (id, name) => {
          pendingRename = { kind: "dataset", id };
          renameTitle.textContent = "Переименовать датасет";
          renameInput.value = name || "";
          showModal(renameModal, true);
          renameInput.focus();
          renameInput.select();
        },
        onExportDataset: async (id) => {
          try {
            downloadBlob(await api.exportDatasetVersion(id));
          } catch (err) {
            onError?.(err.message);
          }
        },
        onDeleteDataset: (id, name) => {
          pendingDelete = { kind: "dataset", id };
          deleteTitle.textContent = "Удалить датасет?";
          deleteText.textContent =
            `Удалить «${name || id}»? Связанные модели останутся. Это действие нельзя отменить.`;
          showModal(deleteModal, true);
        },
        onRenameModel: (id, name) => {
          pendingRename = { kind: "model", id };
          renameTitle.textContent = "Переименовать модель";
          renameInput.value = name || "";
          showModal(renameModal, true);
          renameInput.focus();
          renameInput.select();
        },
        onExportModel: async (id) => {
          const projectId = getProject?.()?.id;
          if (!projectId) return;
          try {
            downloadBlob(await api.exportModel(projectId, id));
          } catch (err) {
            onError?.(err.message);
          }
        },
        onDeleteModel: (id, name) => {
          pendingDelete = { kind: "model", id };
          deleteTitle.textContent = "Удалить модель?";
          deleteText.textContent =
            `Удалить «${name || id}» и её веса? Это действие нельзя отменить.`;
          showModal(deleteModal, true);
        },
      };
      renderDatasets(sortedVersions, handlers);
      renderModels(models || [], handlers);
      refreshIcons(document.getElementById("tab-view-models"));
    } catch (err) {
      onError?.(err.message);
      renderDatasets([], {});
      renderModels([], {});
    }
  }

  document.getElementById("btn-cancel-rename-asset")?.addEventListener("click", closeRename);
  document.getElementById("btn-cancel-delete-asset")?.addEventListener("click", closeDelete);

  renameForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!pendingRename) return;
    const name = renameInput.value.trim();
    if (!name) return;
    const project = getProject?.();
    try {
      if (pendingRename.kind === "dataset") {
        await api.renameDatasetVersion(pendingRename.id, name);
      } else if (project) {
        await api.renameModel(project.id, pendingRename.id, name);
      }
      closeRename();
      await refresh();
      onChanged?.();
    } catch (err) {
      onError?.(err.message);
    }
  });

  document.getElementById("btn-confirm-delete-asset")?.addEventListener("click", async () => {
    if (!pendingDelete) return;
    const project = getProject?.();
    try {
      if (pendingDelete.kind === "dataset") {
        await api.deleteDatasetVersion(pendingDelete.id);
      } else if (project) {
        await api.deleteModel(project.id, pendingDelete.id);
      }
      closeDelete();
      await refresh();
      onChanged?.();
    } catch (err) {
      onError?.(err.message);
    }
  });

  hub = { refresh };
  return hub;
}
