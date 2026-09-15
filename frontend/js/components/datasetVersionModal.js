import { api } from "../api.js";
import { showModal, refreshIcons } from "../utils/dom.js";

/** Must stay in sync with backend DEFAULT_MIN_VERIFIED_IMAGES. */
export const MIN_VERIFIED_IMAGES = 10;

function pendingReviewCount(images) {
  return (images || []).filter((image) => image.status === "REQUIRES_REVIEW").length;
}

function verifiedCount(images) {
  return (images || []).filter((image) => image.status === "VERIFIED").length;
}

function hamiltonCounts(total, ratios) {
  const weights = [ratios.train, ratios.valid, ratios.test];
  const raw = weights.map((weight) => (total * weight) / 100);
  const floors = raw.map((value) => Math.floor(value));
  let leftover = total - floors.reduce((sum, value) => sum + value, 0);
  const order = raw
    .map((value, index) => ({ index, frac: value - floors[index] }))
    .sort((a, b) => b.frac - a.frac || b.index - a.index);
  for (let step = 0; step < leftover; step += 1) {
    floors[order[step % 3].index] += 1;
  }
  if (total >= 3) {
    for (let index = 0; index < 3; index += 1) {
      if (floors[index] === 0) {
        const donor = floors.indexOf(Math.max(...floors));
        if (floors[donor] > 1) {
          floors[donor] -= 1;
          floors[index] += 1;
        }
      }
    }
  }
  return { train: floors[0], valid: floors[1], test: floors[2] };
}

export function initDatasetVersionModal({ onCreated, onError, getImages, getProject }) {
  const modal = document.getElementById("dataset-modal");
  const banner = document.getElementById("dataset-gate-banner");
  const buildBtn = document.getElementById("btn-submit-dataset");
  const spinner = document.getElementById("dataset-building");
  const formBlock = document.getElementById("dataset-form-block");
  const successCard = document.getElementById("dataset-success-card");

  let previewImages = [];
  let versionCount = 0;
  const splits = { train: 70, valid: 20, test: 10 };

  function renderSplitLabels() {
    document.getElementById("ds-split-train-val").textContent = `${Math.round(splits.train)}%`;
    document.getElementById("ds-split-valid-val").textContent = `${Math.round(splits.valid)}%`;
    document.getElementById("ds-split-test-val").textContent = `${Math.round(splits.test)}%`;
    document.getElementById("ds-split-train").value = String(Math.round(splits.train));
    document.getElementById("ds-split-valid").value = String(Math.round(splits.valid));
    document.getElementById("ds-split-test").value = String(Math.round(splits.test));
  }

  function setSplit(changed, rawValue) {
    const keys = ["train", "valid", "test"];
    const value = Math.max(0, Math.min(100, Number(rawValue)));
    const others = keys.filter((key) => key !== changed);
    const remaining = 100 - value;
    const otherSum = others.reduce((sum, key) => sum + splits[key], 0);
    if (otherSum <= 0) {
      splits[others[0]] = remaining / 2;
      splits[others[1]] = remaining / 2;
    } else {
      const scale = remaining / otherSum;
      splits[others[0]] *= scale;
      splits[others[1]] *= scale;
    }
    splits[changed] = value;
    const total = splits.train + splits.valid + splits.test;
    if (total !== 100 && total > 0) {
      splits.test += 100 - total;
    }
    renderSplitLabels();
    updatePreview();
  }

  function updatePreview() {
    const total = verifiedCount(previewImages);
    const counts = hamiltonCounts(total, splits);
    const multiplier = Number(document.getElementById("ds-multiplier")?.value || 3);
    document.getElementById("ds-summary").textContent =
      `Из ${total} confirmed: ~${counts.train} Train, ${counts.valid} Valid, ${counts.test} Test (случайно)`;
    document.getElementById("ds-multiplier-label").textContent = `${multiplier}×`;
    document.getElementById("ds-aug-forecast").textContent =
      `Обучающая выборка будет расширена с ${counts.train} до ${counts.train * multiplier} изображений`;
  }

  function showForm() {
    formBlock?.classList.remove("hidden");
    successCard?.classList.add("hidden");
  }

  function showSuccess(version) {
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
    if (pending > 0) {
      banner.classList.remove("hidden");
      banner.textContent =
        `Нельзя создать версию датасета: ${pending} кадра содержат неподтвержденную разметку. ` +
        "Подтвердите или отклоните их перед сборкой";
      buildBtn.disabled = true;
    } else if (totalVerified < MIN_VERIFIED_IMAGES) {
      banner.classList.remove("hidden");
      banner.textContent =
        `Нужно минимум ${MIN_VERIFIED_IMAGES} подтвержденных кадров (сейчас ${totalVerified}).`;
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
    splits.train = 70;
    splits.valid = 20;
    splits.test = 10;
    renderSplitLabels();
    updatePreview();
    showModal(modal, true);
    refreshIcons(modal);
  }

  ["train", "valid", "test"].forEach((key) => {
    document.getElementById(`ds-split-${key}`)?.addEventListener("input", (event) => {
      setSplit(key, event.target.value);
    });
  });

  document.getElementById("btn-close-dataset")?.addEventListener("click", close);
  document.getElementById("btn-cancel-dataset")?.addEventListener("click", close);
  document.getElementById("btn-dismiss-dataset-success")?.addEventListener("click", close);
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
        test: Number((splits.test / 100).toFixed(4)),
      };
      const drift = 1 - (ratios.train + ratios.valid + ratios.test);
      ratios.test = Number((ratios.test + drift).toFixed(4));
      const version = await api.createDatasetVersion(project.id, {
        name: document.getElementById("ds-name").value.trim() || null,
        train: ratios.train,
        valid: ratios.valid,
        test: ratios.test,
        augmentation: {
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
