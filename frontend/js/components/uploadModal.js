import { store } from "../store.js";
import { api } from "../api.js";

const ACCEPT = new Set(["image/jpeg", "image/png", "image/webp", "image/jpg"]);

function isImageFile(file) {
  if (ACCEPT.has(file.type)) return true;
  return /\.(jpe?g|png|webp)$/i.test(file.name);
}

function showModal(el, visible) {
  el.classList.toggle("hidden", !visible);
  el.classList.toggle("flex", visible);
}

export function initUploadModal({ onUploaded, onError }) {
  const modal = document.getElementById("upload-modal");
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const fileCount = document.getElementById("file-count");
  const progress = document.getElementById("upload-progress");
  const submit = document.getElementById("btn-submit-upload");
  const splits = { train: 70, valid: 20, test: 10 };
  let files = [];

  function renderSplitLabels() {
    document.getElementById("split-train-val").textContent = `${Math.round(splits.train)}%`;
    document.getElementById("split-valid-val").textContent = `${Math.round(splits.valid)}%`;
    document.getElementById("split-test-val").textContent = `${Math.round(splits.test)}%`;
    document.getElementById("split-train").value = String(Math.round(splits.train));
    document.getElementById("split-valid").value = String(Math.round(splits.valid));
    document.getElementById("split-test").value = String(Math.round(splits.test));
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
  }

  function setFiles(list) {
    files = [...list].filter(isImageFile);
    fileCount.textContent = files.length
      ? `Выбрано файлов: ${files.length}`
      : "Подходящие файлы не выбраны";
  }

  function open() {
    if (!store.get("currentProject")) {
      onError("Сначала создайте или выберите проект");
      return;
    }
    progress.style.width = "0%";
    showModal(modal, true);
  }

  function close() {
    showModal(modal, false);
    dropzone.classList.remove("dropzone-active");
  }

  ["train", "valid", "test"].forEach((key) => {
    document.getElementById(`split-${key}`).addEventListener("input", (event) => {
      setSplit(key, event.target.value);
    });
  });

  dropzone.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => setFiles(fileInput.files));

  ["dragenter", "dragover"].forEach((type) => {
    dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      dropzone.classList.add("dropzone-active");
    });
  });
  ["dragleave", "drop"].forEach((type) => {
    dropzone.addEventListener(type, (event) => {
      event.preventDefault();
      dropzone.classList.remove("dropzone-active");
    });
  });
  dropzone.addEventListener("drop", (event) => {
    setFiles(event.dataTransfer.files);
  });

  document.getElementById("btn-open-upload").addEventListener("click", open);
  document.getElementById("btn-close-upload").addEventListener("click", close);
  document.getElementById("btn-cancel-upload").addEventListener("click", close);

  submit.addEventListener("click", async () => {
    const project = store.get("currentProject");
    if (!project || !files.length) {
      onError("Выберите файлы для загрузки");
      return;
    }
    submit.disabled = true;
    try {
      const ratios = {
        train: Number((splits.train / 100).toFixed(4)),
        valid: Number((splits.valid / 100).toFixed(4)),
        test: Number((splits.test / 100).toFixed(4)),
      };
      const drift = 1 - (ratios.train + ratios.valid + ratios.test);
      ratios.test = Number((ratios.test + drift).toFixed(4));
      const uploaded = await api.uploadImages(project.id, files, ratios, (ratio) => {
        progress.style.width = `${Math.round(ratio * 100)}%`;
      });
      progress.style.width = "100%";
      files = [];
      fileInput.value = "";
      fileCount.textContent = "";
      close();
      onUploaded(uploaded);
    } catch (err) {
      onError(err.message);
    } finally {
      submit.disabled = false;
    }
  });

  renderSplitLabels();
  return { open, close };
}
