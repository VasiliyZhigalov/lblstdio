import { store } from "../store.js";
import { api } from "../api.js";

const IMAGE_RE = /\.(jpe?g|png|webp)$/i;
const LABEL_RE = /\.txt$/i;
const META_RE = /(^|\/)(data\.ya?ml|classes\.txt)$/i;
const ZIP_RE = /\.zip$/i;

function showModal(el, visible) {
  el.classList.toggle("hidden", !visible);
  el.classList.toggle("flex", visible);
}

function isAcceptedFile(file) {
  const name = file.webkitRelativePath || file.name;
  if (IMAGE_RE.test(name) || ZIP_RE.test(name) || META_RE.test(name)) return true;
  if (LABEL_RE.test(name) && !META_RE.test(name)) return true;
  return false;
}

function summarize(files) {
  let images = 0;
  let labels = 0;
  let zips = 0;
  let meta = 0;
  for (const file of files) {
    const name = file.webkitRelativePath || file.name;
    if (ZIP_RE.test(name)) zips += 1;
    else if (META_RE.test(name)) meta += 1;
    else if (IMAGE_RE.test(name)) images += 1;
    else if (LABEL_RE.test(name)) labels += 1;
  }
  const parts = [];
  if (images) parts.push(`${images} изображений`);
  if (labels) parts.push(`${labels} label`);
  if (meta) parts.push(`${meta} meta`);
  if (zips) parts.push(`${zips} zip`);
  return parts.length ? `Выбрано: ${parts.join(", ")}` : "Подходящие файлы не выбраны";
}

export function initUploadModal({ onUploaded, onError }) {
  const modal = document.getElementById("upload-modal");
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const folderInput = document.getElementById("folder-input");
  const fileCount = document.getElementById("file-count");
  const progress = document.getElementById("upload-progress");
  const submit = document.getElementById("btn-submit-upload");
  let files = [];

  function setFiles(list) {
    files = [...list].filter(isAcceptedFile);
    fileCount.textContent = summarize(files);
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

  dropzone.addEventListener("click", (event) => {
    if (event.target.closest("[data-upload-folder]")) return;
    fileInput.click();
  });
  document.getElementById("btn-upload-files")?.addEventListener("click", (event) => {
    event.stopPropagation();
    fileInput.click();
  });
  document.getElementById("btn-upload-folder")?.addEventListener("click", (event) => {
    event.stopPropagation();
    folderInput?.click();
  });

  fileInput.addEventListener("change", () => setFiles(fileInput.files));
  folderInput?.addEventListener("change", () => setFiles(folderInput.files));

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
      const uploaded = await api.uploadImages(project.id, files, (ratio) => {
        progress.style.width = `${Math.round(ratio * 100)}%`;
      });
      progress.style.width = "100%";
      files = [];
      fileInput.value = "";
      if (folderInput) folderInput.value = "";
      fileCount.textContent = "";
      close();
      onUploaded(uploaded);
    } catch (err) {
      onError(err.message);
    } finally {
      submit.disabled = false;
    }
  });

  return { open, close };
}
