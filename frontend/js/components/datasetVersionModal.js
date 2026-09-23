import { api } from "../api.js";
import { isClassification } from "../store.js";
import { showModal, refreshIcons } from "../utils/dom.js";

/** Must stay in sync with backend DEFAULT_MIN_VERIFIED_IMAGES. */
export const MIN_VERIFIED_IMAGES = 10;

function pendingReviewCount(images) {
  return (images || []).filter((image) => image.status === "REQUIRES_REVIEW").length;
}

function verifiedCount(images) {
  return (images || []).filter(
    (image) => image.status === "VERIFIED" || image.status === "AUTO_VERIFIED"
  ).length;
}

function trainValidCounts(total, ratios) {
  if (total <= 0) return { train: 0, valid: 0 };
  const sum = ratios.train + ratios.valid;
  const raw = [(total * ratios.train) / sum, (total * ratios.valid) / sum];
  const floors = raw.map((value) => Math.floor(value));
  const leftover = total - floors[0] - floors[1];
  if (leftover) {
    if (raw[1] - floors[1] > raw[0] - floors[0]) floors[1] += leftover;
    else floors[0] += leftover;
  }
  if (total >= 2) {
    if (floors[0] === 0) {
      floors[0] = 1;
      floors[1] -= 1;
    } else if (floors[1] === 0) {
      floors[1] = 1;
      floors[0] -= 1;
    }
  }
  return { train: floors[0], valid: floors[1] };
}

function pinnedTestCount(images) {
  return (images || []).filter(
    (image) =>
      (image.status === "VERIFIED" || image.status === "AUTO_VERIFIED") &&
      image.split === "test"
  ).length;
}

export function initDatasetVersionModal({
  onCreated,
  onTrain,
  onError,
  getImages,
  getProject,
}) {
  const modal = document.getElementById("dataset-modal");
  const banner = document.getElementById("dataset-gate-banner");
  const buildBtn = document.getElementById("btn-submit-dataset");
  const spinner = document.getElementById("dataset-building");
  const formBlock = document.getElementById("dataset-form-block");
  const successCard = document.getElementById("dataset-success-card");

  let previewImages = [];
  let versionCount = 0;
  let createdVersionId = null;
  const splits = { train: 80, valid: 20 };

  function renderSplitLabels() {
    document.getElementById("ds-split-train-val").textContent = `${Math.round(splits.train)}%`;
    document.getElementById("ds-split-valid-val").textContent = `${Math.round(splits.valid)}%`;
    document.getElementById("ds-split-train").value = String(Math.round(splits.train));
    document.getElementById("ds-split-valid").value = String(Math.round(splits.valid));
  }

  function setSplit(changed, rawValue) {
    const value = Math.max(5, Math.min(95, Number(rawValue)));
    if (changed === "train") {
      splits.train = value;
      splits.valid = 100 - value;
    } else {
      splits.valid = value;
      splits.train = 100 - value;
    }
    renderSplitLabels();
    updatePreview();
  }

  function updatePreview() {
    const total = verifiedCount(previewImages);
    const pinned = pinnedTestCount(previewImages);
    const pool = Math.max(0, total - pinned);
    const counts = trainValidCounts(pool, splits);
    const multiplier = Number(document.getElementById("ds-multiplier")?.value || 3);
    document.getElementById("ds-summary").textContent =
      `Тест закреплён вручную: ${pinned}. Из остальных ${pool}: ~${counts.train} Train, ${counts.valid} Valid`;
    document.getElementById("ds-multiplier-label").textContent = `${multiplier}×`;
    document.getElementById("ds-aug-forecast").textContent =
      `Обучающая выборка будет расширена с ${counts.train} до ${counts.train * multiplier} изображений`;
  }

  function showForm() {
    formBlock?.classList.remove("hidden");
    successCard?.classList.add("hidden");
  }

  function showSuccess(version) {
    createdVersionId = version.id;
    formBlock?.classList.add("hidden");
    successCard?.classList.remove("hidden");
    document.getElementById("dataset-success-title").textContent =
      `Версия ${version.name} готова`;
    document.getElementById("dataset-success-body").textContent =
      `Кадры: Train ${version.train_count}, Valid ${version.valid_count}, Test ${version.test_count}. ` +
      `Файлы после аугментации: Train ${version.train_file_count}, ` +
      `Valid ${version.valid_file_count}, Test ${version.test_file_count}.`;
    document.getElementById("dataset-success-yaml").textContent = version.yaml_path || "";
  }

  function close() {
    showModal(modal, false);
    spinner.classList.add("hidden");
    showForm();
  }

  function open() {
    const images = getImages() || [];
    const project = getProject();
    previewImages = images;
    const pending = pendingReviewCount(images);
    const totalVerified = verifiedCount(images);

    if (!project) {
      onError?.("Нет выбранного проекта");
      return;
    }

    showForm();
    document.getElementById("dataset-aug-block")?.classList.toggle(
      "hidden",
      isClassification()
    );
    if (pending > 0) {
      banner.classList.remove("hidden");
      banner.textContent =
        `Нельзя создать версию датасета: ${pending} кадра содержат неподтвержденную разметку. ` +
        "Подтвердите или отклоните их перед сборкой";
      buildBtn.disabled = true;
    } else if (totalVerified < MIN_VERIFIED_IMAGES) {
      banner.classList.remove("hidden");
      banner.textContent =
        `Нужно минимум ${MIN_VERIFIED_IMAGES} подтвержденных кадров (сейчас ${totalVerified}). ` +
        "Для более стабильной первой итерации рекомендуется 30+ кадров.";
      buildBtn.disabled = true;
    } else {
      banner.classList.add("hidden");
      buildBtn.disabled = false;
    }

    document.getElementById("ds-name").value = `v${versionCount + 1}`;
    document.getElementById("ds-resize-w").value = "640";
    document.getElementById("ds-resize-h").value = "640";
    document.getElementById("ds-flip").checked = true;
    document.getElementById("ds-vflip").checked = false;
    document.getElementById("ds-rotate").checked = true;
    document.getElementById("ds-shear").checked = true;
    document.getElementById("ds-hue").checked = true;
    document.getElementById("ds-brightness").checked = true;
    document.getElementById("ds-blur").checked = false;
    document.getElementById("ds-noise").checked = false;
    document.getElementById("ds-grayscale").checked = false;
    document.getElementById("ds-cutout").checked = false;
    document.getElementById("ds-multiplier").value = "3";
    splits.train = 80;
    splits.valid = 20;
    renderSplitLabels();
    updatePreview();
    showModal(modal, true);
    refreshIcons(modal);
  }

  ["train", "valid"].forEach((key) => {
    document.getElementById(`ds-split-${key}`)?.addEventListener("input", (event) => {
      setSplit(key, event.target.value);
    });
  });

  document.getElementById("btn-close-dataset")?.addEventListener("click", close);
  document.getElementById("btn-cancel-dataset")?.addEventListener("click", close);
  document.getElementById("btn-dismiss-dataset-success")?.addEventListener("click", close);
  document.getElementById("btn-train-created-dataset")?.addEventListener("click", () => {
    close();
    onTrain?.(createdVersionId);
  });
  document.getElementById("ds-multiplier")?.addEventListener("input", updatePreview);

  buildBtn?.addEventListener("click", async () => {
    const project = getProject();
    if (!project || buildBtn.disabled) return;
    spinner.classList.remove("hidden");
    buildBtn.disabled = true;
    try {
      const ratios = {
        train: Number((splits.train / 100).toFixed(4)),
        valid: Number((splits.valid / 100).toFixed(4)),
        test: 0,
      };
      const drift = 1 - (ratios.train + ratios.valid);
      ratios.valid = Number((ratios.valid + drift).toFixed(4));
      const version = await api.createDatasetVersion(project.id, {
        name: document.getElementById("ds-name").value.trim() || null,
        train: ratios.train,
        valid: ratios.valid,
        test: ratios.test,
        augmentation: isClassification()
          ? {
              resize_width: 640,
              resize_height: 640,
              horizontal_flip: false,
              vertical_flip: false,
              rotate: false,
              shear: false,
              hue_saturation: false,
              brightness_contrast: false,
              blur: false,
              noise: false,
              grayscale: false,
              cutout: false,
              multiplier: 1,
            }
          : {
          resize_width: Number(document.getElementById("ds-resize-w").value || 640),
          resize_height: Number(document.getElementById("ds-resize-h").value || 640),
          horizontal_flip: document.getElementById("ds-flip").checked,
          vertical_flip: document.getElementById("ds-vflip").checked,
          rotate: document.getElementById("ds-rotate").checked,
          shear: document.getElementById("ds-shear").checked,
          hue_saturation: document.getElementById("ds-hue").checked,
          brightness_contrast: document.getElementById("ds-brightness").checked,
          blur: document.getElementById("ds-blur").checked,
          noise: document.getElementById("ds-noise").checked,
          grayscale: document.getElementById("ds-grayscale").checked,
          cutout: document.getElementById("ds-cutout").checked,
          multiplier: Number(document.getElementById("ds-multiplier").value || 3),
        },
      });
      versionCount = version.version_number;
      spinner.classList.add("hidden");
      showSuccess(version);
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
      versionCount = count || 0;
    },
    pendingReviewCount: () => pendingReviewCount(getImages() || []),
  };
}
