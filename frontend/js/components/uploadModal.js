import { store } from "../store.js";
import { api } from "../api.js";

const IMAGE_RE = /\.(jpe?g|png|webp)$/i;
const LABEL_RE = /\.txt$/i;
const META_RE = /(^|[/\\])(data\.ya?ml|classes\.txt|notes\.json)$/i;
const ZIP_RE = /\.zip$/i;
const MAX_UPLOAD_FILES = 5000;

function showModal(el, visible) {
  el.classList.toggle("hidden", !visible);
  el.classList.toggle("flex", visible);
}

function filePath(file) {
  return (file.relativePath || file.webkitRelativePath || file.name || "").replace(/\\/g, "/");
}

function pickerCancelled(err) {
  return err?.name === "AbortError";
}

async function collectDirectoryFiles(directory) {
  const files = [];

  async function walk(handle, prefix) {
    for await (const entry of handle.values()) {
      if (files.length > MAX_UPLOAD_FILES) return;
      const relative = `${prefix}/${entry.name}`;
      if (entry.kind === "directory") {
        await walk(entry, relative);
        continue;
      }
      const file = await entry.getFile();
      file.relativePath = relative;
      if (isAcceptedFile(file)) files.push(file);
    }
  }

  await walk(directory, directory.name);
  return files;
}

function isAcceptedFile(file) {
  const name = filePath(file);
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
    const name = filePath(file);
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
    const accepted = [...list].filter(isAcceptedFile);
    if (accepted.length > MAX_UPLOAD_FILES) {
      files = [];
      fileCount.textContent = `Слишком много файлов: максимум ${MAX_UPLOAD_FILES}`;
      onError(`Можно загрузить не больше ${MAX_UPLOAD_FILES} файлов за раз`);
      return;
    }
    files = accepted;
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

  async function openFilePicker(event) {
    event?.stopPropagation?.();
    if (typeof window.showOpenFilePicker === "function") {
      try {
        const handles = await window.showOpenFilePicker({ multiple: true });
        const picked = [];
        for (const handle of handles) picked.push(await handle.getFile());
        setFiles(picked);
        if (folderInput) folderInput.value = "";
      } catch (err) {
        if (!pickerCancelled(err)) onError(err.message || "Не удалось открыть файлы");
      }
      return;
    }
    fileInput?.click();
  }

  async function openFolderPicker(event) {
    event?.stopPropagation?.();
    if (typeof window.showDirectoryPicker === "function") {
      try {
        const directory = await window.showDirectoryPicker();
        fileCount.textContent = "Чтение папки…";
        setFiles(await collectDirectoryFiles(directory));
        fileInput.value = "";
      } catch (err) {
        if (!pickerCancelled(err)) onError(err.message || "Не удалось открыть папку");
      }
      return;
    }
    if (!folderInput) {
      onError("Выбор папки не поддерживается в этом браузере");
      return;
    }
    folderInput.click();
  }

  // Dropzone click opens files only when not clicking action buttons.
  dropzone.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : event.target?.parentElement;
    if (target?.closest("button, label, input")) return;
    openFilePicker(event);
  });

  document.getElementById("btn-upload-files")?.addEventListener("click", openFilePicker);
  document.getElementById("btn-upload-folder")?.addEventListener("click", openFolderPicker);

  fileInput.addEventListener("change", () => {
    setFiles(fileInput.files);
    if (folderInput) folderInput.value = "";
  });
  folderInput?.addEventListener("change", () => {
    setFiles(folderInput.files);
    // Clear the other input so repeated picks always fire change.
    fileInput.value = "";
  });

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
