import { api } from "../api.js";
import { showModal, refreshIcons } from "../utils/dom.js";

function countBySplit(images) {
  const counts = { train: 0, valid: 0, test: 0 };
  for (const image of images) {
    if (image.status !== "VERIFIED") continue;
    const key = String(image.split || "").toLowerCase();
    if (key in counts) counts[key] += 1;
  }
  return counts;
}

function pendingReviewCount(images) {
  return (images || []).filter((image) => image.status === "REQUIRES_REVIEW").length;
}

function updatePreview() {
  const images = window.__datasetModalImages || [];
  const counts = countBySplit(images);
  const multiplier = Number(document.getElementById("ds-multiplier")?.value || 3);
  document.getElementById("ds-summary").textContent =
    `Будет включено: ${counts.train} кадров Train, ${counts.valid} Valid, ${counts.test} Test`;
  document.getElementById("ds-multiplier-label").textContent = `${multiplier}×`;
  document.getElementById("ds-aug-forecast").textContent =
    `Обучающая выборка будет расширена с ${counts.train} до ${counts.train * multiplier} изображений`;
}

export function initDatasetVersionModal({ onCreated, onError, getImages, getProject }) {
  const modal = document.getElementById("dataset-modal");
  const banner = document.getElementById("dataset-gate-banner");
  const buildBtn = document.getElementById("btn-submit-dataset");
  const spinner = document.getElementById("dataset-building");

  function close() {
    showModal(modal, false);
    spinner.classList.add("hidden");
    buildBtn.disabled = false;
  }

  function open() {
    const images = getImages() || [];
    const project = getProject();
    window.__datasetModalImages = images;
    const pending = pendingReviewCount(images);
    const counts = countBySplit(images);
    const totalVerified = counts.train + counts.valid + counts.test;

    if (!project) {
      onError?.("Нет выбранного проекта");
      return;
    }

    if (pending > 0) {
      banner.classList.remove("hidden");
      banner.textContent =
        `Нельзя создать версию датасета: ${pending} кадра содержат неподтвержденную разметку. ` +
        "Подтвердите или отклоните их перед сборкой";
      buildBtn.disabled = true;
    } else if (totalVerified < 1) {
      banner.classList.remove("hidden");
      banner.textContent = "Нет подтвержденных кадров для сборки версии датасета.";
      buildBtn.disabled = true;
    } else {
      banner.classList.add("hidden");
      buildBtn.disabled = false;
    }

    const nextVersion =
      (window.__datasetVersionCount || 0) + 1;
    document.getElementById("ds-name").value = `v${nextVersion}`;
    document.getElementById("ds-flip").checked = true;
    document.getElementById("ds-brightness").checked = true;
    document.getElementById("ds-blur").checked = false;
    document.getElementById("ds-multiplier").value = "3";
    updatePreview();
    showModal(modal, true);
    refreshIcons(modal);
  }

  document.getElementById("btn-close-dataset")?.addEventListener("click", close);
  document.getElementById("btn-cancel-dataset")?.addEventListener("click", close);
  document.getElementById("ds-multiplier")?.addEventListener("input", updatePreview);

  buildBtn?.addEventListener("click", async () => {
    const project = getProject();
    if (!project || buildBtn.disabled) return;
    spinner.classList.remove("hidden");
    buildBtn.disabled = true;
    try {
      const version = await api.createDatasetVersion(project.id, {
        name: document.getElementById("ds-name").value.trim() || null,
        augmentation: {
          horizontal_flip: document.getElementById("ds-flip").checked,
          brightness_contrast: document.getElementById("ds-brightness").checked,
          blur: document.getElementById("ds-blur").checked,
          shift_scale_rotate: true,
          multiplier: Number(document.getElementById("ds-multiplier").value || 3),
        },
      });
      window.__datasetVersionCount = version.version_number;
      close();
      onCreated?.(version);
    } catch (err) {
      spinner.classList.add("hidden");
      buildBtn.disabled = false;
      onError?.(err.message || String(err));
    }
  });

  return {
    open,
    syncVersions(count) {
      window.__datasetVersionCount = count || 0;
    },
    pendingReviewCount: () => pendingReviewCount(getImages() || []),
  };
}
