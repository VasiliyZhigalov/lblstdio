import { store } from "./store.js";
import { api } from "./api.js";
import { AnnotationCanvas } from "./components/canvas.js";
import { initDashboard } from "./components/dashboard.js";
import { initSidebar, selectClassByHotkey, deleteSelectedBox } from "./components/sidebar.js";
import { initUploadModal } from "./components/uploadModal.js";
import { initHotkeys } from "./hotkeys.js";

const PROJECT_KEY = "lblstdio.projectId";
let canvas;
let navLock = false;

function toast(message, timeout = 2800) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), timeout);
}

function refreshIcons() {
  window.lucide?.createIcons();
}

function showView(name) {
  store.set("view", name);
  document.getElementById("view-dashboard").classList.toggle("hidden", name !== "dashboard");
  document.getElementById("view-studio").classList.toggle("hidden", name !== "studio");
  if (name === "studio") {
    requestAnimationFrame(() => {
      canvas?.resize();
      canvas?.fitToScreen();
    });
  }
}

function setMode(mode) {
  store.set("mode", mode);
  const selectBtn = document.getElementById("tool-select");
  const drawBtn = document.getElementById("tool-draw");
  const active = "p-2.5 rounded-lg hover:bg-zinc-800 text-indigo-400 bg-zinc-800/80 transition";
  const idle = "p-2.5 rounded-lg hover:bg-zinc-800 text-zinc-400 transition";
  selectBtn.className = mode === "SELECT" ? active : idle;
  drawBtn.className = mode === "DRAW" ? active : idle;
}

function setSaveIndicator() {
  const status = store.get("saveStatus");
  const dot = document.querySelector("#save-indicator .save-dot");
  const text = document.getElementById("save-indicator-text");
  const map = {
    idle: ["saved", "Сохранено"],
    saved: ["saved", "Сохранено"],
    saving: ["saving", "Сохранение..."],
    unsaved: ["unsaved", "Не сохранено"],
    error: ["error", "Ошибка сохранения"],
  };
  const [cls, label] = map[status] || map.idle;
  dot.className = `save-dot ${cls}`;
  text.textContent = label;
}

function updateStudioChrome() {
  const image = store.get("currentImage");
  const images = store.get("images") || [];
  document.getElementById("image-filename").textContent = image?.file_name || "—";
  const badge = document.getElementById("badge-split");
  badge.textContent = (image?.split || "train").toUpperCase();
  const idx = images.findIndex((item) => item.id === image?.id);
  document.getElementById("current-idx").textContent = idx >= 0 ? String(idx + 1) : "0";
  document.getElementById("total-idx").textContent = String(images.length);
}

async function loadProject(projectId) {
  const project = await api.getProject(projectId);
  const [classes, images] = await Promise.all([
    api.listClasses(projectId),
    api.listImages(projectId),
  ]);
  localStorage.setItem(PROJECT_KEY, projectId);
  store.patch({
    currentProject: project,
    classes,
    images,
    activeClassId: classes[0]?.id || null,
  });
}

async function refreshProjects(preferId) {
  const projects = await api.listProjects();
  store.set("projects", projects);
  const saved = preferId || localStorage.getItem(PROJECT_KEY);
  const chosen = projects.find((item) => item.id === saved) || projects[0] || null;
  if (chosen) await loadProject(chosen.id);
  else {
    store.patch({
      currentProject: null,
      classes: [],
      images: [],
      activeClassId: null,
    });
  }
}

async function saveCurrent({ silent = false } = {}) {
  const image = store.get("currentImage");
  if (!image || !store.get("hasUnsavedChanges")) return;
  const selectedId = store.get("selectedBoxId");
  const selectedIndex = store.get("annotations").findIndex((box) => box.id === selectedId);
  store.set("saveStatus", "saving");
  try {
    const saved = await api.saveAnnotations(image.id, store.get("annotations"));
    const images = store.get("images").map((item) => {
      if (item.id !== image.id) return item;
      return { ...item, status: saved.length ? "VERIFIED" : "UNANNOTATED" };
    });
    store.patch({
      annotations: saved,
      selectedBoxId: selectedIndex >= 0 ? saved[selectedIndex]?.id || null : null,
      hasUnsavedChanges: false,
      saveStatus: "saved",
      images,
      currentImage: images.find((item) => item.id === image.id) || image,
    });
  } catch (err) {
    store.set("saveStatus", "error");
    if (!silent) toast(err.message);
    throw err;
  }
}

async function openImage(imageId) {
  if (navLock) return;
  navLock = true;
  try {
    if (store.get("hasUnsavedChanges")) {
      await saveCurrent({ silent: true });
    }
    const detail = await api.getImage(imageId);
    store.patch({
      currentImage: detail,
      annotations: detail.annotations || [],
      selectedBoxId: null,
      hoveredBoxId: null,
      hasUnsavedChanges: false,
      saveStatus: "saved",
    });
    showView("studio");
    await canvas.loadImage(api.imageFileUrl(imageId));
    updateStudioChrome();
  } catch (err) {
    toast(err.message);
  } finally {
    navLock = false;
  }
}

async function go(delta) {
  const images = store.get("images") || [];
  const current = store.get("currentImage");
  if (!images.length || !current) return;
  const idx = images.findIndex((item) => item.id === current.id);
  const next = images[idx + delta];
  if (!next) return;
  await openImage(next.id);
}

async function exportDataset() {
  const project = store.get("currentProject");
  if (!project) {
    toast("Нет выбранного проекта");
    return;
  }
  try {
    if (store.get("hasUnsavedChanges")) await saveCurrent({ silent: true });
    const blob = await api.exportYolo(project.id);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `project-${project.id}-yolo.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    toast(err.message);
  }
}

function boot() {
  canvas = new AnnotationCanvas(
    document.getElementById("annotation-canvas"),
    document.getElementById("canvas-container")
  );

  initDashboard({
    onSelectProject: async (id) => {
      try {
        await loadProject(id);
      } catch (err) {
        toast(err.message);
      }
    },
    onOpenImage: openImage,
    onCreateProject: async (name) => {
      try {
        const created = await api.createProject(name);
        await refreshProjects(created.id);
      } catch (err) {
        toast(err.message);
      }
    },
  });

  initSidebar({ onError: toast });
  initUploadModal({
    onError: toast,
    onUploaded: async () => {
      const project = store.get("currentProject");
      if (project) {
        const images = await api.listImages(project.id);
        store.set("images", images);
        toast(`Загружено. Всего кадров: ${images.length}`);
      }
    },
  });

  initHotkeys({
    setMode,
    fit: () => canvas.fitToScreen(),
    prev: () => go(-1),
    next: () => go(1),
    deleteSelected: deleteSelectedBox,
    selectClass: selectClassByHotkey,
    save: () => saveCurrent().catch(() => {}),
  });

  document.getElementById("canvas-container").addEventListener("need-class", () => {
    toast("Сначала создайте и выберите класс");
  });

  document.getElementById("tool-select").addEventListener("click", () => setMode("SELECT"));
  document.getElementById("tool-draw").addEventListener("click", () => setMode("DRAW"));
  document.getElementById("tool-fit").addEventListener("click", () => canvas.fitToScreen());
  document.getElementById("btn-back-gallery").addEventListener("click", async () => {
    try {
      if (store.get("hasUnsavedChanges")) await saveCurrent({ silent: true });
    } catch {
      /* keep studio if save failed */
      return;
    }
    showView("dashboard");
  });
  document.getElementById("btn-prev").addEventListener("click", () => go(-1));
  document.getElementById("btn-next").addEventListener("click", () => go(1));
  document.getElementById("btn-export").addEventListener("click", exportDataset);
  document.getElementById("btn-export-studio").addEventListener("click", exportDataset);

  store.addEventListener("change:saveStatus", setSaveIndicator);
  store.addEventListener("change:currentImage", updateStudioChrome);
  store.addEventListener("change:images", updateStudioChrome);

  window.addEventListener("beforeunload", (event) => {
    if (store.get("hasUnsavedChanges")) event.preventDefault();
  });

  setMode("SELECT");
  refreshIcons();
  refreshProjects().catch((err) => toast(err.message));
}

boot();
