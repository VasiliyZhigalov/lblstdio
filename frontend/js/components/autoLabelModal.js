import { api } from "../api.js";
import { showModal, refreshIcons } from "../utils/dom.js";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForAutoLabelJob(jobId, { onProgress } = {}) {
  let job = await api.getAutoLabelJob(jobId);
  const deadline = Date.now() + 10 * 60 * 1000;
  while (job.status === "PENDING" || job.status === "RUNNING") {
    if (Date.now() > deadline) {
      throw new Error("Авторазметка превысила время ожидания");
    }
    onProgress?.(job);
    await sleep(400);
    job = await api.getAutoLabelJob(jobId);
  }
  return job;
}

export function initAutoLabelModal({
  getProject,
  getImages,
  getCurrentImage,
  onError,
  onStarted,
  onDone,
}) {
  const modal = document.getElementById("autolabel-modal");
  let preferredModelId = null;

  function close() {
    showModal(modal, false);
    document.getElementById("autolabel-progress")?.classList.add("hidden");
  }

  async function open(modelId = null) {
    const project = getProject();
    if (!project) {
      onError?.("Сначала откройте проект");
      return;
    }
    preferredModelId = modelId;
    const classification = project.task_type === "CLASSIFICATION";
    document.getElementById("autolabel-iou-fields")?.classList.toggle("hidden", classification);
    showModal(modal, true);
    refreshIcons();
    try {
      const models = await api.listModels(project.id);
      const select = document.getElementById("autolabel-model");
      if (!models.length) {
        select.innerHTML = `<option value="">Нет обученных моделей</option>`;
        return;
      }
      select.innerHTML = models
        .map((item) => `<option value="${item.id}">${item.display_name}</option>`)
        .join("");
      if (preferredModelId) select.value = preferredModelId;
    } catch (err) {
      onError?.(err.message);
    }
  }

  document.getElementById("autolabel-conf")?.addEventListener("input", (event) => {
    document.getElementById("autolabel-conf-label").textContent = Number(
      event.target.value
    ).toFixed(2);
  });
  document.getElementById("autolabel-iou")?.addEventListener("input", (event) => {
    document.getElementById("autolabel-iou-label").textContent = Number(
      event.target.value
    ).toFixed(2);
  });
  document
    .getElementById("autolabel-consistency-iou")
    ?.addEventListener("input", (event) => {
      document.getElementById("autolabel-consistency-iou-label").textContent =
        Number(event.target.value).toFixed(2);
    });
  document.getElementById("btn-close-autolabel")?.addEventListener("click", close);
  document.getElementById("btn-cancel-autolabel")?.addEventListener("click", close);
  document.getElementById("btn-submit-autolabel")?.addEventListener("click", async () => {
    const project = getProject();
    const modelId = document.getElementById("autolabel-model")?.value;
    const conf = Number(document.getElementById("autolabel-conf")?.value || 0.05);
    const iou = Number(document.getElementById("autolabel-iou")?.value || 0.7);
    const consistencyIou = Number(
      document.getElementById("autolabel-consistency-iou")?.value || 0.8
    );
    const allUnannotated = Boolean(
      document.getElementById("autolabel-all-unannotated")?.checked
    );
    const targetImageCount = allUnannotated
      ? (getImages?.() || []).filter((image) => image.status === "UNANNOTATED").length
      : 1;
    if (!project || !modelId) {
      onError?.("Выберите модель");
      return;
    }
    const progress = document.getElementById("autolabel-progress");
    const progressText = document.getElementById("autolabel-progress-text");
    progress?.classList.remove("hidden");
    progressText.textContent = "Постановка в очередь…";
    try {
      onStarted?.();
      const classification = project.task_type === "CLASSIFICATION";
      const body = {
        confidence_threshold: conf,
        all_unannotated: allUnannotated,
      };
      if (!classification) {
        body.iou_threshold = iou;
        body.consistency_iou_threshold = consistencyIou;
      }
      if (!allUnannotated) {
        const current = getCurrentImage?.();
        if (!current?.id) {
          progress?.classList.add("hidden");
          onError?.("Нет текущего кадра для авторазметки");
          return;
        }
        body.image_ids = [current.id];
        body.all_unannotated = false;
      }
      const queued = await api.autoLabel(project.id, modelId, body);
      progressText.textContent = `Обработка кадров: 0/${targetImageCount}`;
      const job = await waitForAutoLabelJob(queued.id, {
        onProgress: (current) => {
          const processed = current.total_images_processed || 0;
          progressText.textContent = `Обработка кадров: ${processed}/${targetImageCount}`;
        },
      });
      if (job.status === "FAILED") {
        progress?.classList.add("hidden");
        onError?.(job.error_message || "Авторазметка завершилась с ошибкой");
        return;
      }
      const preds = job.total_predictions_generated || 0;
      const unit = classification ? "меток" : "объектов";
      if (preds === 0) {
        progressText.textContent = `Готово: ${job.total_images_processed} кадров, 0 ${unit}. Попробуйте снизить порог (сейчас ${conf.toFixed(2)}).`;
        onDone?.(job, {
          empty: true,
          message: classification
            ? `Модель не присвоила класс при пороге ${conf.toFixed(2)}. Снизьте Confidence.`
            : `Модель не нашла объектов при пороге ${conf.toFixed(2)}. Снизьте Confidence (для текущей модели часто нужно ≤0.05).`,
        });
        progress?.classList.add("hidden");
        return;
      }
      progressText.textContent = `Готово: ${job.total_images_processed} кадров, ${preds} ${unit}`;
      onDone?.(job);
      setTimeout(close, 700);
    } catch (err) {
      progress?.classList.add("hidden");
      onError?.(err.message);
    }
  });

  return { open, close };
}
