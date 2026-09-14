import { store } from "./store.js";
import { api } from "./api.js";
import { AnnotationCanvas } from "./components/canvas.js";
import { initProjectsHub, loadProjectsHub } from "./components/projectsHub.js";
import { getFilmstripImages, initFilmstrip } from "./components/filmstrip.js";
import { initSidebar, selectClassByHotkey } from "./components/sidebar.js";
import { initReviewBar } from "./components/reviewBar.js";
import { initUploadModal } from "./components/uploadModal.js";
import { initDatasetVersionModal } from "./components/datasetVersionModal.js";
import { initHotkeys } from "./hotkeys.js";
import { ensureHash, navigate, parseHash } from "./router.js";
import { refreshIcons, showModal } from "./utils/dom.js";

let canvas;
let celebrateSave = false;
let saveFlashTimer = 0;
let routeSeq = 0;
let navToken = 0;
let pendingClearImageId = null;
let saveQueue = Promise.resolve();
let datasetModal = null;

function statusFromAnnotations(boxes) {
  if (!boxes?.length) return "UNANNOTATED";
  if (boxes.some((box) => box.verification_status === "PENDING_REVIEW")) {
    return "REQUIRES_REVIEW";
  }
  return "VERIFIED";
}

function patchImageStatus(imageId, status) {
  const images = (store.get("images") || []).map((item) =>
    item.id === imageId ? { ...item, status } : item
  );
  store.set("images", images);
  const current = store.get("currentImage");
  if (current?.id === imageId) {
    store.set("currentImage", { ...current, status });
  }
  return images;
}

function toast(message, timeout = 2800) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), timeout);
}

function showView(name) {
  store.set("view", name);
  document.getElementById("view-projects").classList.toggle("hidden", name !== "projects");
  document.getElementById("view-studio").classList.toggle("hidden", name !== "studio");
  if (name === "studio") {
    document.activeElement?.blur?.();
    requestAnimationFrame(() => {
      canvas?.resize();
      canvas?.fitToScreen();
    });
  }
}

function setMode(mode) {
  store.set("mode", mode);
  const active = "p-2 rounded-lg hover:bg-zinc-800 text-indigo-400 bg-zinc-800/80";
  const idle = "p-2 rounded-lg hover:bg-zinc-800 text-zinc-400";
  document.getElementById("tool-select").className = mode === "SELECT" ? active : idle;
  document.getElementById("tool-draw").className = mode === "DRAW" ? active : idle;
}

function updateSaveButton() {
  const btn = document.getElementById("btn-save-annotations");
  const label = document.getElementById("save-btn-label");
  const badge = document.getElementById("save-unsaved-badge");
  const status = store.get("saveStatus");
  const unsaved = store.get("hasUnsavedChanges");
  badge.classList.toggle("hidden", !unsaved || status === "saving");
  btn.disabled = status === "saving" || !store.get("currentImage");
  btn.classList.remove("bg-emerald-600", "hover:bg-emerald-500", "bg-indigo-600", "hover:bg-indigo-500");
  if (status === "saving") {
    label.textContent = "Saving...";
    btn.classList.add("bg-indigo-600", "hover:bg-indigo-500");
    return;
  }
  if (celebrateSave && status === "saved") {
    label.textContent = "Сохранено! ✓";
    btn.classList.add("bg-emerald-600", "hover:bg-emerald-500");
    clearTimeout(saveFlashTimer);
    saveFlashTimer = setTimeout(() => {
      celebrateSave = false;
      updateSaveButton();
    }, 2000);
    return;
  }
  label.textContent = "Сохранить аннотации";
  btn.classList.add("bg-indigo-600", "hover:bg-indigo-500");
}

function updateStudioChrome() {
  const image = store.get("currentImage");
  const images = store.get("images") || [];
  const project = store.get("currentProject");
  document.getElementById("studio-project-name").textContent = project?.name || "—";
  document.getElementById("image-filename").textContent = image?.file_name || "";
  const badge = document.getElementById("badge-split");
  badge.textContent = (image?.split || "train").toUpperCase();
  const idx = images.findIndex((item) => item.id === image?.id);
  document.getElementById("current-idx").textContent = idx >= 0 ? String(idx + 1) : "0";
  document.getElementById("total-idx").textContent = String(images.length);
  updateSaveButton();
}

function setBoxCount(imageId, count) {
  store.set("boxCounts", { ...store.get("boxCounts"), [imageId]: count });
}

function serializeBoxes(boxes) {
  return JSON.stringify(
    (boxes || []).map((box) => ({
      id: box.id || null,
      class_id: box.class_id,
      x_center: box.x_center,
      y_center: box.y_center,
      width: box.width,
      height: box.height,
    }))
  );
}

function restoreStudioHash(projectId) {
  if (!projectId) {
    history.replaceState(null, "", `${window.location.pathname}${window.location.search}#/projects`);
    return;
  }
  history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search}#/projects/${projectId}`
  );
}

async function loadProject(projectId) {
  const project = await api.getProject(projectId);
  const [classes, images, versions] = await Promise.all([
    api.listClasses(projectId),
    api.listImages(projectId),
    api.listDatasetVersions(projectId).catch(() => []),
  ]);
  const counts = { ...store.get("boxCounts") };
  for (const image of images) {
    if (image.status === "UNANNOTATED") counts[image.id] = 0;
  }
  const prevActive = store.get("activeClassId");
  const activeClassId = classes.some((item) => item.id === prevActive)
    ? prevActive
    : classes[0]?.id || null;
  store.patch({
    currentProject: project,
    classes,
    images,
    activeClassId,
    boxCounts: counts,
  });
  datasetModal?.syncVersions(versions[0]?.version_number || 0);
}

async function saveCurrent({ silent = false, force = false, celebrate = false } = {}) {
  const run = async () => {
    const image = store.get("currentImage");
    if (!image) return;
    if (!force && !store.get("hasUnsavedChanges")) return;

    const imageId = image.id;
    const snapshot = serializeBoxes(store.get("annotations"));
    const selectedId = store.get("selectedBoxId");
    const selectedIndex = store.get("annotations").findIndex((box) => box.id === selectedId);
    const boxes = store.get("annotations").map((box) => ({ ...box }));

    store.set("saveStatus", "saving");
    try {
      const saved = await api.saveAnnotations(imageId, boxes);
      setBoxCount(imageId, saved.length);

      const images = (store.get("images") || []).map((item) => {
        if (item.id !== imageId) return item;
        return { ...item, status: statusFromAnnotations(saved) };
      });
      store.set("images", images);

      const stillOnImage = store.get("currentImage")?.id === imageId;
      const localUnchanged = serializeBoxes(store.get("annotations")) === snapshot;

      if (stillOnImage && localUnchanged) {
        store.patch({
          annotations: saved,
          selectedBoxId: selectedIndex >= 0 ? saved[selectedIndex]?.id || null : null,
          hasUnsavedChanges: false,
          saveStatus: "saved",
          currentImage: images.find((item) => item.id === imageId) || store.get("currentImage"),
        });
        if (celebrate) celebrateSave = true;
        updateSaveButton();
      } else if (stillOnImage) {
        // User edited while PUT was in flight — keep local boxes dirty.
        store.set("saveStatus", "unsaved");
        updateSaveButton();
      } else if (store.get("saveStatus") === "saving") {
        store.set("saveStatus", store.get("hasUnsavedChanges") ? "unsaved" : "saved");
        updateSaveButton();
      }
    } catch (err) {
      if (store.get("currentImage")?.id === imageId) {
        store.set("saveStatus", "error");
      }
      if (!silent) toast(err.message);
      throw err;
    }
  };

  const queued = saveQueue.then(run, run);
  saveQueue = queued.catch(() => {});
  return queued;
}

async function openImage(imageId, expectedProjectId = null) {
  if (!imageId) return;
  const token = ++navToken;
  const projectId = expectedProjectId || store.get("currentProject")?.id;
  try {
    if (store.get("hasUnsavedChanges")) {
      await saveCurrent({ silent: true });
    }
    if (token !== navToken) return;
    if (projectId && store.get("currentProject")?.id !== projectId) return;

    if (store.get("currentImage")?.id === imageId && canvas.image) {
      updateStudioChrome();
      return;
    }

    const detail = await api.getImage(imageId);
    if (token !== navToken) return;
    if (projectId && store.get("currentProject")?.id !== projectId) return;

    const annotations = detail.annotations || [];
    setBoxCount(imageId, annotations.length);
    const images = (store.get("images") || []).map((item) =>
      item.id === imageId ? { ...item, status: detail.status } : item
    );
    store.patch({
      currentImage: detail,
      annotations,
      images,
      selectedBoxId: null,
      hoveredBoxId: null,
      hasUnsavedChanges: false,
      saveStatus: "saved",
      matchDebug: null,
    });
    await canvas.loadImage(api.imageFileUrl(imageId));
    if (token !== navToken) return;
    updateStudioChrome();
  } catch (err) {
    if (token === navToken) toast(err.message);
  }
}

async function go(delta) {
  const images = getFilmstripImages();
  const current = store.get("currentImage");
  if (!images.length || !current) return;
  const idx = images.findIndex((item) => item.id === current.id);
  const next = images[idx + delta];
  if (next) await openImage(next.id);
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

async function leaveStudio() {
  const projectId = store.get("currentProject")?.id;
  try {
    if (store.get("hasUnsavedChanges")) await saveCurrent({ silent: true });
  } catch {
    toast("Не удалось сохранить кадр перед выходом");
    restoreStudioHash(projectId);
    return;
  }
  navigate("/projects");
}

async function enterStudio(projectId, seq) {
  await loadProject(projectId);
  if (seq !== routeSeq) return;
  showView("studio");
  refreshIcons();
  const images = store.get("images") || [];
  const current = store.get("currentImage");
  const stillHere = current && images.some((item) => item.id === current.id);
  if (stillHere) {
    updateStudioChrome();
    canvas.resize();
    canvas.fitToScreen();
    return;
  }
  if (images[0]) {
    await openImage(images[0].id, projectId);
    return;
  }
  if (seq !== routeSeq) return;
  store.patch({
    currentImage: null,
    annotations: [],
    selectedBoxId: null,
    hasUnsavedChanges: false,
    saveStatus: "idle",
  });
  canvas.clearImage();
  updateStudioChrome();
}

async function onRoute() {
  const seq = ++routeSeq;
  const route = parseHash();
  const previousProjectId = store.get("currentProject")?.id;

  if (route.name === "projects") {
    try {
      if (store.get("hasUnsavedChanges")) await saveCurrent({ silent: true });
    } catch {
      toast("Не удалось сохранить кадр перед выходом");
      restoreStudioHash(previousProjectId);
      return;
    }
    if (seq !== routeSeq) return;
    showView("projects");
    try {
      await loadProjectsHub();
    } catch (err) {
      if (seq === routeSeq) toast(err.message);
    }
    return;
  }

  // Switching studio project: save previous frame first.
  if (
    previousProjectId &&
    previousProjectId !== route.projectId &&
    store.get("hasUnsavedChanges")
  ) {
    try {
      await saveCurrent({ silent: true });
    } catch {
      toast("Не удалось сохранить кадр перед сменой проекта");
      restoreStudioHash(previousProjectId);
      return;
    }
  }

  if (seq !== routeSeq) return;
  try {
    await enterStudio(route.projectId, seq);
  } catch (err) {
    if (seq !== routeSeq) return;
    toast(err.message);
    navigate("/projects");
  }
}

async function clearAnnotations() {
  const imageId = pendingClearImageId;
  pendingClearImageId = null;
  if (!imageId) return;
  if (store.get("currentImage")?.id !== imageId) {
    toast("Кадр уже сменён — очистка отменена");
    return;
  }
  store.patch({
    annotations: [],
    selectedBoxId: null,
    hasUnsavedChanges: true,
    saveStatus: "unsaved",
  });
  try {
    await saveCurrent({ force: true, celebrate: true });
    if (store.get("currentImage")?.id === imageId) {
      toast("Разметка кадра очищена");
    }
  } catch {
    /* toast from saveCurrent */
  }
}

function setMatchingUi(active, label = "Сопоставление ключевых точек...") {
  store.set("matchingInProgress", active);
  const overlay = document.getElementById("matching-overlay");
  const text = document.getElementById("matching-overlay-text");
  if (text) text.textContent = label;
  overlay?.classList.toggle("hidden", !active);
  if (canvas) {
    canvas.setCursor(active ? "wait" : "default");
  }
}

function copySelectedBox() {
  const image = store.get("currentImage");
  const annotations = store.get("annotations") || [];
  if (!image || !annotations.length) {
    toast("На кадре нет рамок для копирования");
    return;
  }
  store.set("clipboardBox", {
    sourceImageId: image.id,
    boxes: annotations.map((box) => ({
      id: box.id,
      class_id: box.class_id,
      x_center: box.x_center,
      y_center: box.y_center,
      width: box.width,
      height: box.height,
    })),
  });
  const n = annotations.length;
  toast(
    n === 1
      ? "Аннотация скопирована. Откройте другой кадр и нажмите «Вставить»"
      : `Скопировано аннотаций: ${n}. Откройте другой кадр и нажмите «Вставить»`
  );
  syncClipboardButtons();
}

async function pastePropagateBox() {
  const clip = store.get("clipboardBox");
  const target = store.get("currentImage");
  const boxes = clip?.boxes?.length
    ? clip.boxes
    : clip?.boxData
      ? [clip.boxData]
      : [];
  if (!clip || !boxes.length || !target) {
    toast("Буфер пуст — сначала скопируйте аннотации");
    return;
  }
  if (clip.sourceImageId === target.id) {
    toast("Перенос возможен только на другой кадр");
    return;
  }
  if (store.get("matchingInProgress")) return;

  setMatchingUi(true, `Сопоставление ключевых точек (${boxes.length})...`);
  try {
    if (store.get("hasUnsavedChanges")) {
      await saveCurrent({ silent: true });
    }
    const snapshot = serializeBoxes(store.get("annotations"));
    const payload = await api.propagateBoxes(clip.sourceImageId, target.id, boxes);
    const createdList = payload.annotations || payload;
    const transform = payload.transform || null;
    const debugArrows = payload.debug_arrows || [];

    if (createdList.length) {
      patchImageStatus(target.id, "REQUIRES_REVIEW");
    }

    if (store.get("currentImage")?.id !== target.id) {
      const prev = store.get("boxCounts")?.[target.id];
      if (typeof prev === "number") setBoxCount(target.id, prev + createdList.length);
      toast(
        createdList.length
          ? `Перенесено рамок: ${createdList.length}`
          : "Не удалось найти объекты на этом кадре. Разметьте вручную"
      );
      return;
    }

    if (!createdList.length) {
      toast("Не удалось найти объекты на этом кадре. Разметьте вручную");
      return;
    }

    const dirtyDuringMatch = serializeBoxes(store.get("annotations")) !== snapshot;
    const annotations = [...(store.get("annotations") || []), ...createdList];
    const last = createdList[createdList.length - 1];
    store.patch({
      annotations,
      selectedBoxId: last.id,
      hasUnsavedChanges: dirtyDuringMatch,
      saveStatus: dirtyDuringMatch ? "unsaved" : "saved",
      matchDebug: transform
        ? {
            transform,
            arrows: debugArrows,
          }
        : null,
    });
    setBoxCount(target.id, annotations.length);
    canvas?.centerOnBox(last);
    const t = transform;
    const debugLine = t
      ? ` | Δ=(${t.tx.toFixed(1)}, ${t.ty.toFixed(1)})px rot=${t.rotation_deg.toFixed(1)}° s=${t.scale.toFixed(3)}`
      : "";
    toast(
      createdList.length === 1
        ? `Объект найден (${Math.round((createdList[0].confidence || 0) * 100)}%)${debugLine}`
        : `Перенесено: ${createdList.length}${debugLine}`
    );
  } catch (err) {
    toast(err.message || "Не удалось найти объекты на этом кадре. Разметьте вручную");
  } finally {
    setMatchingUi(false);
  }
}

function syncClipboardButtons() {
  const pasteBtn = document.getElementById("btn-paste-annotations");
  if (!pasteBtn) return;
  const clip = store.get("clipboardBox");
  const hasClip = Boolean(clip?.boxes?.length || clip?.boxData);
  pasteBtn.classList.toggle("hidden", !hasClip);
}

function pendingFocusBox() {
  const annotations = store.get("annotations") || [];
  const selected = annotations.find((item) => item.id === store.get("selectedBoxId"));
  if (selected?.verification_status === "PENDING_REVIEW") return selected;
  const hovered = annotations.find((item) => item.id === store.get("hoveredBoxId"));
  if (hovered?.verification_status === "PENDING_REVIEW") return hovered;
  return null;
}

async function deleteBoxById(boxId) {
  const image = store.get("currentImage");
  if (!image || !boxId) return;
  const box = (store.get("annotations") || []).find((item) => item.id === boxId);
  if (!box) return;

  if (box.verification_status === "PENDING_REVIEW") {
    try {
      const remaining = await api.deleteAnnotation(image.id, box.id);
      store.patch({
        annotations: remaining,
        selectedBoxId: store.get("selectedBoxId") === boxId ? null : store.get("selectedBoxId"),
        hoveredBoxId: store.get("hoveredBoxId") === boxId ? null : store.get("hoveredBoxId"),
        hasUnsavedChanges: false,
        saveStatus: "saved",
      });
      patchImageStatus(image.id, statusFromAnnotations(remaining));
      setBoxCount(image.id, remaining.length);
      toast("Перенос отклонён");
    } catch (err) {
      toast(err.message);
    }
    return;
  }

  store.patch({
    annotations: store.get("annotations").filter((item) => item.id !== boxId),
    selectedBoxId: store.get("selectedBoxId") === boxId ? null : store.get("selectedBoxId"),
    hoveredBoxId: store.get("hoveredBoxId") === boxId ? null : store.get("hoveredBoxId"),
    hasUnsavedChanges: true,
    saveStatus: "unsaved",
  });
}

async function verifyAllPending({ goNext = true } = {}) {
  const image = store.get("currentImage");
  if (!image) return;
  const pending = (store.get("annotations") || []).filter(
    (box) => box.verification_status === "PENDING_REVIEW"
  );
  if (!pending.length) return;

  try {
    if (store.get("hasUnsavedChanges")) {
      await saveCurrent({ silent: true });
    }
    const annotations = await api.verifyAllAnnotations(image.id);
    if (store.get("currentImage")?.id !== image.id) {
      patchImageStatus(image.id, statusFromAnnotations(annotations));
      return;
    }
    store.patch({
      annotations,
      selectedBoxId: null,
      hasUnsavedChanges: false,
      saveStatus: "saved",
    });
    patchImageStatus(image.id, statusFromAnnotations(annotations));
    toast(`Подтверждено рамок: ${pending.length}`);
    if (goNext) await go(1);
  } catch (err) {
    toast(err.message);
  }
}

async function rejectAllPending() {
  const image = store.get("currentImage");
  if (!image) return;
  const pending = (store.get("annotations") || []).filter(
    (box) => box.verification_status === "PENDING_REVIEW"
  );
  if (!pending.length) return;

  try {
    const remaining = await api.rejectAllPending(image.id);
    if (store.get("currentImage")?.id !== image.id) {
      patchImageStatus(image.id, statusFromAnnotations(remaining));
      return;
    }
    store.patch({
      annotations: remaining,
      selectedBoxId: null,
      hoveredBoxId: null,
      hasUnsavedChanges: false,
      saveStatus: "saved",
    });
    patchImageStatus(image.id, statusFromAnnotations(remaining));
    setBoxCount(image.id, remaining.length);
    toast(`Отклонено гипотез: ${pending.length}`);
  } catch (err) {
    toast(err.message);
  }
}

function frameHasPending() {
  return (store.get("annotations") || []).some(
    (box) => box.verification_status === "PENDING_REVIEW"
  );
}

async function verifySelectedBox() {
  const image = store.get("currentImage");
  const box = pendingFocusBox();
  if (!image || !box) return;
  try {
    if (store.get("selectedBoxId") !== box.id) {
      store.set("selectedBoxId", box.id);
    }
    const verified = await api.verifyAnnotation(image.id, box.id);
    const annotations = (store.get("annotations") || []).map((item) =>
      item.id === verified.id ? verified : item
    );
    store.patch({
      annotations,
      selectedBoxId: verified.id,
      hasUnsavedChanges: false,
      saveStatus: "saved",
    });
    patchImageStatus(image.id, statusFromAnnotations(annotations));
    toast("Рамка подтверждена");
  } catch (err) {
    toast(err.message);
  }
}

async function rejectSelectedBox() {
  const box = pendingFocusBox();
  if (box) {
    await deleteBoxById(box.id);
    return;
  }
  const selectedId = store.get("selectedBoxId");
  if (selectedId) await deleteBoxById(selectedId);
}

function boot() {
  canvas = new AnnotationCanvas(
    document.getElementById("annotation-canvas"),
    document.getElementById("canvas-container")
  );

  initProjectsHub({
    onOpenProject: (id) => navigate(`/projects/${id}`),
    onCreateProject: async (name, description) => {
      try {
        const created = await api.createProject(name, description);
        await loadProjectsHub();
        navigate(`/projects/${created.id}`);
      } catch (err) {
        toast(err.message);
        throw err;
      }
    },
    onDeleteProject: async (id) => {
      try {
        await api.deleteProject(id);
        if (store.get("currentProject")?.id === id) {
          store.patch({ currentProject: null, images: [], currentImage: null, annotations: [] });
        }
        await loadProjectsHub();
        toast("Проект удалён");
      } catch (err) {
        toast(err.message);
      }
    },
  });

  initFilmstrip({ onOpenImage: openImage });
  initSidebar({
    onError: toast,
    onDeleteBox: (id) => {
      deleteBoxById(id).catch(() => {});
    },
  });
  initReviewBar({
    onApproveAll: () => verifyAllPending({ goNext: true }).catch(() => {}),
    onRejectAll: () => rejectAllPending().catch(() => {}),
  });
  initUploadModal({
    onError: toast,
    onUploaded: async (uploaded) => {
      const project = store.get("currentProject");
      if (!project) return;
      const images = await api.listImages(project.id);
      store.set("images", images);
      toast(`Загружено. Всего кадров: ${images.length}`);
      if (!store.get("currentImage") && uploaded?.[0]) {
        await openImage(uploaded[0].id, project.id);
      }
    },
  });

  datasetModal = initDatasetVersionModal({
    getProject: () => store.get("currentProject"),
    getImages: () => store.get("images") || [],
    onError: toast,
    onCreated: (version) => {
      toast(
        `Версия ${version.name} готова: Train ${version.train_count}, Valid ${version.valid_count}, Test ${version.test_count}`
      );
    },
  });

  initHotkeys({
    setMode,
    fit: () => canvas.fitToScreen(),
    prev: () => go(-1),
    next: () => go(1),
    deleteSelected: () => {
      rejectSelectedBox().catch(() => {});
    },
    selectClass: selectClassByHotkey,
    save: () => saveCurrent({ force: true, celebrate: true }).catch(() => {}),
    verifyAll: () => verifyAllPending({ goNext: true }).catch(() => {}),
    rejectAll: () => rejectAllPending().catch(() => {}),
    hasPending: frameHasPending,
  });

  document.getElementById("btn-copy-annotations")?.addEventListener("click", () => {
    copySelectedBox();
  });
  document.getElementById("btn-paste-annotations")?.addEventListener("click", () => {
    pastePropagateBox().catch(() => {});
  });
  store.addEventListener("change:clipboardBox", syncClipboardButtons);
  syncClipboardButtons();

  document.getElementById("btn-approve-box")?.addEventListener("click", (event) => {
    event.stopPropagation();
    verifySelectedBox().catch(() => {});
  });
  document.getElementById("btn-reject-box")?.addEventListener("click", (event) => {
    event.stopPropagation();
    rejectSelectedBox().catch(() => {});
  });

  document.getElementById("canvas-container").addEventListener("need-class", () => {
    toast("Сначала создайте и выберите класс");
  });
  document.getElementById("tool-select").addEventListener("click", () => setMode("SELECT"));
  document.getElementById("tool-draw").addEventListener("click", () => setMode("DRAW"));
  document.getElementById("tool-fit").addEventListener("click", () => canvas.fitToScreen());
  document.getElementById("btn-back-projects").addEventListener("click", leaveStudio);
  document.getElementById("btn-prev").addEventListener("click", () => go(-1));
  document.getElementById("btn-next").addEventListener("click", () => go(1));
  document.getElementById("btn-export-studio").addEventListener("click", exportDataset);
  document.getElementById("btn-create-dataset")?.addEventListener("click", () => {
    datasetModal?.open();
  });
  document.getElementById("btn-save-annotations").addEventListener("click", () => {
    saveCurrent({ force: true, celebrate: true }).catch(() => {});
  });
  document.getElementById("btn-clear-annotations").addEventListener("click", () => {
    const image = store.get("currentImage");
    if (!image) {
      toast("Нет открытого кадра");
      return;
    }
    pendingClearImageId = image.id;
    showModal(document.getElementById("clear-modal"), true);
  });
  document.getElementById("btn-cancel-clear").addEventListener("click", () => {
    pendingClearImageId = null;
    showModal(document.getElementById("clear-modal"), false);
  });
  document.getElementById("btn-confirm-clear").addEventListener("click", async () => {
    showModal(document.getElementById("clear-modal"), false);
    await clearAnnotations();
  });

  store.addEventListener("change:saveStatus", updateSaveButton);
  store.addEventListener("change:hasUnsavedChanges", updateSaveButton);
  store.addEventListener("change:currentImage", updateStudioChrome);
  store.addEventListener("change:images", updateStudioChrome);
  store.addEventListener("change:currentProject", updateStudioChrome);

  window.addEventListener("hashchange", () => {
    onRoute().catch((err) => toast(err.message));
  });
  window.addEventListener("beforeunload", (event) => {
    if (!store.get("hasUnsavedChanges")) return;
    event.preventDefault();
    event.returnValue = "";
  });

  setMode("SELECT");
  refreshIcons();
  ensureHash();
  onRoute().catch((err) => toast(err.message));
}

boot();
