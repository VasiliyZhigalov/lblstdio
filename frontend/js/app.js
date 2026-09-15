import { store } from "./store.js";
import { api } from "./api.js";
import { AnnotationCanvas } from "./components/canvas.js";
import { initProjectsHub, loadProjectsHub } from "./components/projectsHub.js";
import { getFilmstripImages, initFilmstrip } from "./components/filmstrip.js";
import { initSidebar, selectClassByHotkey } from "./components/sidebar.js";
import { initReviewBar } from "./components/reviewBar.js";
import { initUploadModal } from "./components/uploadModal.js";
import { initDatasetVersionModal } from "./components/datasetVersionModal.js";
import { initTrainingDrawer } from "./components/trainingDrawer.js";
import { initAutoLabelModal } from "./components/autoLabelModal.js";
import { initDataHub } from "./components/dataHub.js";
import { initModelsHub } from "./components/modelsHub.js";
import { initHotkeys } from "./hotkeys.js";
import { ensureHash, navigate, parseHash, projectPath, replaceHash } from "./router.js";
import { escapeHtml, refreshIcons, showModal } from "./utils/dom.js";

let canvas;
let celebrateSave = false;
let saveFlashTimer = 0;
let routeSeq = 0;
let navToken = 0;
let pendingClearImageId = null;
let saveQueue = Promise.resolve();
let datasetModal = null;
let trainingDrawer = null;
let autoLabelModal = null;
let dataHub = null;
let modelsHub = null;
let quickClassBoxId = null;

function statusFromAnnotations(boxes) {
  if (!boxes?.length) return "UNANNOTATED";
  if (boxes.some((box) => box.verification_status === "PENDING_REVIEW")) {
    return "REQUIRES_REVIEW";
  }
  return "VERIFIED";
}

function patchImageStatus(imageId, status, extra = {}) {
  const images = (store.get("images") || []).map((item) =>
    item.id === imageId ? { ...item, status, ...extra } : item
  );
  store.set("images", images);
  const current = store.get("currentImage");
  if (current?.id === imageId) {
    store.set("currentImage", { ...current, status, ...extra });
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

function showShell(visible) {
  store.set("view", visible ? "studio" : "projects");
  document.getElementById("view-projects").classList.toggle("hidden", visible);
  document.getElementById("view-project-shell").classList.toggle("hidden", !visible);
}

const TAB_BTN_ACTIVE = "flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-md transition bg-zinc-800 text-white";
const TAB_BTN_IDLE = "flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-md transition text-zinc-400 hover:text-zinc-200";

function syncTabChrome(tab) {
  for (const name of ["data", "annotate", "models"]) {
    const btn = document.getElementById(`tab-btn-${name}`);
    if (btn) btn.className = name === tab ? TAB_BTN_ACTIVE : TAB_BTN_IDLE;
    const view = document.getElementById(`tab-view-${name}`);
    if (view) view.classList.toggle("hidden", name !== tab);
    const actions = document.getElementById(`shell-actions-${name}`);
    if (actions) actions.classList.toggle("hidden", name !== tab);
  }
}

async function setProjectTab(tab, { skipSave = false } = {}) {
  const prev = store.get("projectTab");
  if (prev === "annotate" && tab !== "annotate" && !skipSave) {
    try {
      if (store.get("hasUnsavedChanges")) await saveCurrent({ silent: true });
    } catch {
      toast("Не удалось сохранить кадр перед сменой вкладки");
      throw new Error("save-before-tab-failed");
    }
  }

  store.set("projectTab", tab);
  syncTabChrome(tab);
  hideQuickClassPopover();
  applySidebarCollapsed();

  if (tab === "annotate") {
    document.activeElement?.blur?.();
    requestAnimationFrame(() => {
      canvas?.resize();
      canvas?.fitToScreen();
    });
  }
  if (tab === "data") {
    dataHub?.refresh?.().catch((err) => toast(err.message));
  }
  if (tab === "models") {
    modelsHub?.refresh?.().catch((err) => toast(err.message));
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
  if (!btn || !label || !badge) return;
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
  label.textContent = "Сохранить";
  btn.classList.add("bg-indigo-600", "hover:bg-indigo-500");
}

function updateStudioChrome() {
  const image = store.get("currentImage");
  const images = store.get("images") || [];
  const project = store.get("currentProject");
  const nameEl = document.getElementById("shell-project-name");
  if (nameEl) nameEl.textContent = project?.name || "—";
  const fileEl = document.getElementById("image-filename");
  if (fileEl) fileEl.textContent = image?.file_name || "";
  const badge = document.getElementById("badge-split");
  if (badge) badge.textContent = (image?.split || "train").toUpperCase();
  const idx = images.findIndex((item) => item.id === image?.id);
  const currentIdx = document.getElementById("current-idx");
  const totalIdx = document.getElementById("total-idx");
  if (currentIdx) currentIdx.textContent = idx >= 0 ? String(idx + 1) : "0";
  if (totalIdx) totalIdx.textContent = String(images.length);
  updateSaveButton();
  syncHideButtons();
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

function restoreProjectHash(projectId, tab = "data", imageId = null) {
  if (!projectId) {
    replaceHash("/projects");
    return;
  }
  replaceHash(projectPath(projectId, tab, imageId));
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

function syncAnnotateHash(imageId) {
  const project = store.get("currentProject");
  if (!project || store.get("projectTab") !== "annotate") return;
  const next = `#${projectPath(project.id, "annotate", imageId)}`;
  if (window.location.hash !== next) {
    history.replaceState(null, "", `${window.location.pathname}${window.location.search}${next}`);
  }
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
      syncAnnotateHash(imageId);
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
    hideQuickClassPopover();
    await canvas.loadImage(api.imageFileUrl(imageId));
    if (token !== navToken) return;
    updateStudioChrome();
    syncAnnotateHash(imageId);
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
  const tab = store.get("projectTab");
  const imageId = store.get("currentImage")?.id;
  try {
    if (store.get("hasUnsavedChanges")) await saveCurrent({ silent: true });
  } catch {
    toast("Не удалось сохранить кадр перед выходом");
    restoreProjectHash(projectId, tab, tab === "annotate" ? imageId : null);
    return;
  }
  navigate("/projects");
}

async function enterProject(route, seq) {
  const { projectId, tab, imageId } = route;
  const rawHash = (window.location.hash || "").replace(/^#/, "");
  const parts = rawHash.split("?")[0].split("/").filter(Boolean);
  if (parts[0] === "projects" && parts[1] && !parts[2]) {
    replaceHash(projectPath(projectId, "data"));
  }

  await loadProject(projectId);
  if (seq !== routeSeq) return;

  showShell(true);
  try {
    await setProjectTab(tab || "data", { skipSave: true });
  } catch {
    return;
  }
  refreshIcons();
  updateStudioChrome();

  if (tab === "annotate") {
    const images = store.get("images") || [];
    const targetId =
      imageId && images.some((item) => item.id === imageId)
        ? imageId
        : store.get("currentImage")?.id && images.some((item) => item.id === store.get("currentImage").id)
          ? store.get("currentImage").id
          : images[0]?.id || null;
    if (targetId) {
      await openImage(targetId, projectId);
    } else {
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
  }
}

async function onRoute() {
  const seq = ++routeSeq;
  const route = parseHash();
  const previousProjectId = store.get("currentProject")?.id;
  const previousTab = store.get("projectTab");

  if (route.name === "projects") {
    try {
      if (store.get("hasUnsavedChanges")) await saveCurrent({ silent: true });
    } catch {
      toast("Не удалось сохранить кадр перед выходом");
      restoreProjectHash(
        previousProjectId,
        previousTab,
        previousTab === "annotate" ? store.get("currentImage")?.id : null
      );
      return;
    }
    if (seq !== routeSeq) return;
    showShell(false);
    try {
      await loadProjectsHub();
    } catch (err) {
      if (seq === routeSeq) toast(err.message);
    }
    return;
  }

  if (
    previousProjectId &&
    previousProjectId !== route.projectId &&
    store.get("hasUnsavedChanges")
  ) {
    try {
      await saveCurrent({ silent: true });
    } catch {
      toast("Не удалось сохранить кадр перед сменой проекта");
      restoreProjectHash(
        previousProjectId,
        previousTab,
        previousTab === "annotate" ? store.get("currentImage")?.id : null
      );
      return;
    }
  }

  if (seq !== routeSeq) return;

  // Same project, tab change via hash
  if (previousProjectId === route.projectId && store.get("view") === "studio") {
    try {
      await setProjectTab(route.tab || "data");
    } catch {
      restoreProjectHash(previousProjectId, previousTab, store.get("currentImage")?.id);
      return;
    }
    if (route.tab === "annotate") {
      const images = store.get("images") || [];
      const target =
        route.imageId && images.some((item) => item.id === route.imageId)
          ? route.imageId
          : store.get("currentImage")?.id || images[0]?.id;
      if (target) await openImage(target, route.projectId);
    }
    return;
  }

  try {
    await enterProject(route, seq);
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
  const selectedId = store.get("selectedBoxId");
  const selected = annotations.find((box) => box.id === selectedId);
  const toCopy = selected ? [selected] : annotations;
  store.set("clipboardBox", {
    sourceImageId: image.id,
    boxes: toCopy.map((box) => ({
      id: box.id,
      class_id: box.class_id,
      x_center: box.x_center,
      y_center: box.y_center,
      width: box.width,
      height: box.height,
    })),
  });
  const n = toCopy.length;
  toast(
    n === 1
      ? "Аннотация скопирована. Откройте другой кадр и нажмите Ctrl+Shift+V"
      : `Скопировано аннотаций: ${n}. Откройте другой кадр и нажмите Ctrl+Shift+V`
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

async function markCurrentAsBackground() {
  const image = store.get("currentImage");
  if (!image) {
    toast("Нет открытого кадра");
    return;
  }
  const boxes = store.get("annotations") || [];
  if (boxes.length) {
    toast("Сначала очистите кадр от объектов");
    return;
  }
  if (store.get("hasUnsavedChanges")) {
    await saveCurrent({ silent: true });
  }
  try {
    const updated = await api.markBackground(image.id);
    patchImageStatus(updated.id, updated.status, {
      is_background: updated.is_background,
    });
    setBoxCount(image.id, 0);
    toast("Кадр отмечен как бэкграунд (negative sample)");
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

function hideQuickClassPopover() {
  quickClassBoxId = null;
  store.set("quickClassOpen", false);
  document.getElementById("quick-class-popover")?.classList.add("hidden");
}

function showQuickClassPopover(boxId, screenX, screenY) {
  const pop = document.getElementById("quick-class-popover");
  if (!pop) return;
  const classes = [...(store.get("classes") || [])]
    .sort((a, b) => a.index_id - b.index_id)
    .slice(0, 9);
  if (!classes.length) {
    hideQuickClassPopover();
    return;
  }
  quickClassBoxId = boxId;
  store.set("quickClassOpen", true);
  pop.innerHTML = classes
    .map(
      (cls, index) => `
      <button type="button" data-quick-class="${cls.id}"
        class="w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-left text-xs hover:bg-zinc-800 text-zinc-200">
        <span class="font-mono text-zinc-500 w-4">[${index + 1}]</span>
        <span class="w-2.5 h-2.5 rounded-sm shrink-0" style="background:${escapeHtml(cls.color_hex)}"></span>
        <span class="truncate">${escapeHtml(cls.name)}</span>
      </button>`
    )
    .join("");

  const container = document.getElementById("canvas-container");
  const maxX = (container?.clientWidth || 400) - 160;
  const maxY = (container?.clientHeight || 400) - 8 - classes.length * 34;
  pop.style.left = `${Math.max(8, Math.min(screenX + 8, maxX))}px`;
  pop.style.top = `${Math.max(8, Math.min(screenY + 8, maxY))}px`;
  pop.classList.remove("hidden");

  pop.querySelectorAll("[data-quick-class]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      applyQuickClass(btn.dataset.quickClass);
    });
  });
}

function applyQuickClass(classId) {
  if (!quickClassBoxId || !classId) {
    hideQuickClassPopover();
    return false;
  }
  const boxId = quickClassBoxId;
  store.patch({
    annotations: (store.get("annotations") || []).map((box) =>
      box.id === boxId ? { ...box, class_id: classId } : box
    ),
    activeClassId: classId,
    selectedBoxId: boxId,
    hasUnsavedChanges: true,
    saveStatus: "unsaved",
  });
  hideQuickClassPopover();
  return true;
}

function applyQuickClassDigit(digit) {
  const classes = [...(store.get("classes") || [])].sort((a, b) => a.index_id - b.index_id);
  const cls = classes[digit - 1];
  if (!cls || !store.get("quickClassOpen")) return false;
  return applyQuickClass(cls.id);
}

function syncHideButtons() {
  const hidden = store.get("hideAnnotations") === true;
  const tool = document.getElementById("tool-toggle-hide");
  const shell = document.getElementById("btn-shell-toggle-hide");
  const active = "p-2 rounded-lg hover:bg-zinc-800 text-amber-400 bg-zinc-800/80";
  const idle = "p-2 rounded-lg hover:bg-zinc-800 text-zinc-400";
  if (tool) tool.className = hidden ? active : idle;
  if (shell) {
    shell.classList.toggle("bg-zinc-800", hidden);
    shell.classList.toggle("text-amber-300", hidden);
  }
}

function toggleHideAnnotations() {
  store.set("hideAnnotations", !store.get("hideAnnotations"));
  syncHideButtons();
}

function applySidebarCollapsed() {
  const leftCollapsed = store.get("leftSidebarCollapsed");
  const rightCollapsed = store.get("rightSidebarCollapsed");
  const left = document.getElementById("studio-left-sidebar");
  const right = document.getElementById("studio-right-sidebar");
  const expandLeft = document.getElementById("btn-expand-filmstrip");
  const expandRight = document.getElementById("btn-expand-right-sidebar");
  left?.classList.toggle("hidden", leftCollapsed);
  right?.classList.toggle("hidden", rightCollapsed);
  expandLeft?.classList.toggle("hidden", !leftCollapsed || store.get("projectTab") !== "annotate");
  expandRight?.classList.toggle("hidden", !rightCollapsed || store.get("projectTab") !== "annotate");
  if (store.get("projectTab") === "annotate") {
    requestAnimationFrame(() => {
      canvas?.resize();
    });
  }
  refreshIcons(document.getElementById("tab-view-annotate"));
}

function toggleLeftSidebar() {
  store.set("leftSidebarCollapsed", !store.get("leftSidebarCollapsed"));
  applySidebarCollapsed();
}

function toggleRightSidebar() {
  store.set("rightSidebarCollapsed", !store.get("rightSidebarCollapsed"));
  applySidebarCollapsed();
}

function goAnnotate(imageId = null) {
  const project = store.get("currentProject");
  if (!project) return;
  navigate(projectPath(project.id, "annotate", imageId));
}

function boot() {
  canvas = new AnnotationCanvas(
    document.getElementById("annotation-canvas"),
    document.getElementById("canvas-container")
  );

  initProjectsHub({
    onOpenProject: (id) => navigate(projectPath(id, "data")),
    onCreateProject: async (name, description) => {
      try {
        const created = await api.createProject(name, description);
        await loadProjectsHub();
        navigate(projectPath(created.id, "data"));
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

  initFilmstrip({
    onOpenImage: (id) => {
      openImage(id);
    },
  });
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
      dataHub?.refresh?.().catch(() => {});
      if (store.get("projectTab") === "annotate" && !store.get("currentImage") && uploaded?.[0]) {
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
        `Версия ${version.name}: ${version.train_count}+${version.valid_count}+${version.test_count} кадров → ${version.train_file_count} train-файлов`
      );
      modelsHub?.refresh?.().catch(() => {});
    },
  });

  autoLabelModal = initAutoLabelModal({
    getProject: () => store.get("currentProject"),
    getImages: () => store.get("images") || [],
    onError: toast,
    onDone: async (job) => {
      toast(
        `Авторазметка: ${job.total_predictions_generated} объектов на ${job.total_images_processed} кадрах`
      );
      const project = store.get("currentProject");
      if (!project) return;
      const images = await api.listImages(project.id);
      store.set("images", images);
      dataHub?.refresh?.().catch(() => {});
      modelsHub?.refresh?.().catch(() => {});
      const current = store.get("currentImage");
      if (current && store.get("projectTab") === "annotate") {
        await openImage(current.id, project.id);
      }
    },
  });

  trainingDrawer = initTrainingDrawer({
    getProject: () => store.get("currentProject"),
    onError: toast,
    onCompleted: () => {
      toast("Модель обучена");
      modelsHub?.refresh?.().catch(() => {});
    },
    onUseForAutoLabel: (modelId) => autoLabelModal?.open(modelId),
  });

  dataHub = initDataHub({
    onOpenImage: (id) => goAnnotate(id),
    onStartAnnotate: (id) => goAnnotate(id),
  });

  modelsHub = initModelsHub({
    getProject: () => store.get("currentProject"),
    onTrain: () => trainingDrawer?.open(),
    onTrainDataset: (versionId) => trainingDrawer?.open(versionId),
    onAutoLabel: () => autoLabelModal?.open(),
    onUseModel: (modelId) => autoLabelModal?.open(modelId),
    onCreateDataset: () => datasetModal?.open(),
    onError: toast,
    onChanged: () => {
      trainingDrawer?.refreshSelectors?.().catch(() => {});
      autoLabelModal?.refreshModels?.().catch(() => {});
    },
  });

  document.getElementById("btn-train-model")?.addEventListener("click", () => {
    trainingDrawer?.open();
  });
  document.getElementById("btn-auto-label")?.addEventListener("click", () => {
    autoLabelModal?.open();
  });

  document.getElementById("tab-btn-data")?.addEventListener("click", () => {
    const project = store.get("currentProject");
    if (project) navigate(projectPath(project.id, "data"));
  });
  document.getElementById("tab-btn-annotate")?.addEventListener("click", () => {
    goAnnotate(store.get("currentImage")?.id || null);
  });
  document.getElementById("tab-btn-models")?.addEventListener("click", () => {
    const project = store.get("currentProject");
    if (project) navigate(projectPath(project.id, "models"));
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
    copySelected: () => copySelectedBox(),
    pastePropagate: () => {
      pastePropagateBox().catch(() => {});
    },
    toggleHide: toggleHideAnnotations,
    toggleLeftSidebar,
    toggleRightSidebar,
    applyQuickClassDigit,
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
  document.getElementById("canvas-container").addEventListener("box-drawn", (event) => {
    const { boxId, screenX, screenY } = event.detail || {};
    if (boxId) showQuickClassPopover(boxId, screenX, screenY);
  });

  document.getElementById("tool-select").addEventListener("click", () => setMode("SELECT"));
  document.getElementById("tool-draw").addEventListener("click", () => setMode("DRAW"));
  document.getElementById("tool-fit").addEventListener("click", () => canvas.fitToScreen());
  document.getElementById("tool-toggle-hide")?.addEventListener("click", toggleHideAnnotations);
  document.getElementById("btn-shell-toggle-hide")?.addEventListener("click", toggleHideAnnotations);
  document.getElementById("btn-toggle-filmstrip")?.addEventListener("click", toggleLeftSidebar);
  document.getElementById("btn-expand-filmstrip")?.addEventListener("click", toggleLeftSidebar);
  document.getElementById("btn-toggle-right-sidebar")?.addEventListener("click", toggleRightSidebar);
  document.getElementById("btn-expand-right-sidebar")?.addEventListener("click", toggleRightSidebar);

  document.getElementById("tool-opacity")?.addEventListener("click", (event) => {
    event.stopPropagation();
    document.getElementById("opacity-popover")?.classList.toggle("hidden");
  });
  document.getElementById("canvas-opacity-slider")?.addEventListener("input", (event) => {
    store.set("boxOpacity", Number(event.target.value));
  });
  document.addEventListener("click", (event) => {
    const pop = document.getElementById("opacity-popover");
    const tool = document.getElementById("tool-opacity");
    if (!pop || pop.classList.contains("hidden")) return;
    if (pop.contains(event.target) || tool?.contains(event.target)) return;
    pop.classList.add("hidden");
  });
  document.addEventListener("mousedown", (event) => {
    const pop = document.getElementById("quick-class-popover");
    if (!pop || pop.classList.contains("hidden")) return;
    if (pop.contains(event.target)) return;
    hideQuickClassPopover();
  });

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
  document.getElementById("btn-mark-background")?.addEventListener("click", () => {
    markCurrentAsBackground().catch(() => {});
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
  store.addEventListener("change:quickClassOpen", () => {
    if (!store.get("quickClassOpen")) {
      document.getElementById("quick-class-popover")?.classList.add("hidden");
    }
  });

  window.addEventListener("hashchange", () => {
    onRoute().catch((err) => toast(err.message));
  });
  window.addEventListener("beforeunload", (event) => {
    if (!store.get("hasUnsavedChanges")) return;
    event.preventDefault();
    event.returnValue = "";
  });

  setMode("SELECT");
  syncTabChrome("data");
  applySidebarCollapsed();
  refreshIcons();
  ensureHash();
  onRoute().catch((err) => toast(err.message));
}

boot();
