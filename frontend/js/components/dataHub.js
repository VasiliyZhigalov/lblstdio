import { store } from "../store.js";
import { api } from "../api.js";
import { escapeHtml, refreshIcons } from "../utils/dom.js";

const BACKGROUND_FILTER = "__background__";

const STATUS_FILTERS = [
  {
    id: "UNANNOTATED",
    label: "Неразмеченные",
    active: "border-zinc-500/60 bg-zinc-800 text-zinc-100",
  },
  {
    id: "VERIFIED",
    label: "Верифицированные",
    active: "border-emerald-500/60 bg-emerald-950/50 text-emerald-100",
  },
  {
    id: "REQUIRES_REVIEW",
    label: "Ревью",
    active: "border-amber-500/60 bg-amber-950/50 text-amber-100",
  },
];

async function mapPool(items, limit, fn) {
  const results = new Array(items.length);
  let cursor = 0;
  async function worker() {
    while (cursor < items.length) {
      const index = cursor;
      cursor += 1;
      results[index] = await fn(items[index], index);
    }
  }
  const workers = Array.from({ length: Math.min(limit, items.length) || 0 }, () => worker());
  await Promise.all(workers);
  return results;
}

function statusMeta(status) {
  if (status === "VERIFIED") {
    return {
      label: "Verified",
      badge: "bg-emerald-950 text-emerald-400 border-emerald-800/50",
    };
  }
  if (status === "REQUIRES_REVIEW") {
    return {
      label: "Review",
      badge: "bg-amber-950 text-amber-400 border-amber-800/50",
    };
  }
  return {
    label: "Empty",
    badge: "bg-zinc-900 text-zinc-500 border-zinc-800",
  };
}

function renderSplitFilters() {
  const root = document.getElementById("gallery-split-filters");
  if (!root) return;
  root.innerHTML = "";
  root.classList.add("hidden");
}

function renderStats(images) {
  const total = images.length;
  const verified = images.filter((item) => item.status === "VERIFIED").length;
  const pending = images.filter((item) => item.status === "REQUIRES_REVIEW").length;
  const empty = images.filter((item) => item.status === "UNANNOTATED").length;
  document.getElementById("stat-total-images").textContent = String(total);
  document.getElementById("stat-verified-images").textContent = String(verified);
  document.getElementById("stat-pending-images").textContent = String(pending);
  document.getElementById("stat-empty-images").textContent = String(empty);
}

function countBackgroundFrames(images) {
  return (images || []).filter(
    (item) => item.status === "VERIFIED" && item.is_background
  ).length;
}

function selectedSet() {
  return new Set(store.get("gallerySelectedIds") || []);
}

function setSelectedIds(ids) {
  store.set("gallerySelectedIds", [...new Set(ids)]);
}

function pruneSelection(images) {
  const alive = new Set((images || []).map((item) => item.id));
  const next = (store.get("gallerySelectedIds") || []).filter((id) => alive.has(id));
  if (next.length !== (store.get("gallerySelectedIds") || []).length) {
    store.set("gallerySelectedIds", next);
  }
}

function clearGallerySelectionState() {
  store.patch({
    gallerySelectedIds: [],
    galleryClassFilter: [],
    galleryStatusFilter: [],
    imageClassIds: {},
    galleryAnnotations: {},
  });
}

function galleryBboxOverlay(image, boxes, classes) {
  if (!boxes?.length || !image?.width || !image?.height) return "";
  const classById = new Map((classes || []).map((cls) => [cls.id, cls]));
  const rects = boxes
    .map((box) => {
      const color = escapeHtml(classById.get(box.class_id)?.color_hex || "#6366F1");
      const x = (box.x_center - box.width / 2) * image.width;
      const y = (box.y_center - box.height / 2) * image.height;
      const w = box.width * image.width;
      const h = box.height * image.height;
      const pending = box.verification_status === "PENDING_REVIEW";
      return `<rect x="${x}" y="${y}" width="${w}" height="${h}"
        fill="${color}40" stroke="${color}" stroke-width="2"
        ${pending ? 'stroke-dasharray="6 4"' : ""}
        vector-effect="non-scaling-stroke" />`;
    })
    .join("");
  return `<svg class="absolute inset-0 w-full h-full pointer-events-none"
      viewBox="0 0 ${image.width} ${image.height}"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true">${rects}</svg>`;
}

function syncClassBalanceCollapsed() {
  const collapsed = store.get("classBalanceCollapsed") !== false;
  const body = document.getElementById("class-balance-body");
  const btn = document.getElementById("btn-toggle-class-balance");
  const chevron = document.getElementById("class-balance-chevron");
  body?.classList.toggle("hidden", collapsed);
  btn?.setAttribute("aria-expanded", collapsed ? "false" : "true");
  chevron?.classList.toggle("rotate-180", !collapsed);
}

function renderClassBars(classes, classCounts, backgroundFrames = 0) {
  const root = document.getElementById("class-distribution-bars");
  const countLabel = document.getElementById("data-hub-class-count");
  const hint = document.getElementById("class-distribution-hint");
  if (!root) return;

  const sorted = [...(classes || [])].sort((a, b) => a.index_id - b.index_id);
  const classTotal = sorted.reduce((sum, cls) => sum + (classCounts[cls.id] || 0), 0);
  const total = classTotal + backgroundFrames;
  const parts = [`${sorted.length} классов`];
  if (backgroundFrames > 0) parts.push(`${backgroundFrames} background`);
  if (countLabel) countLabel.textContent = parts.join(" · ");

  if (!sorted.length && backgroundFrames <= 0) {
    root.innerHTML = `<p class="text-xs text-zinc-500">Классы ещё не созданы.</p>`;
    hint?.classList.add("hidden");
    return;
  }

  const rows = sorted.map((cls) => {
    const count = classCounts[cls.id] || 0;
    const pct = total > 0 ? Math.round((count / total) * 100) : 0;
    return {
      name: cls.name,
      color: cls.color_hex,
      count,
      pct,
    };
  });
  rows.push(
    ...(backgroundFrames > 0
      ? [
          {
            name: "background",
            color: "#38BDF8",
            count: backgroundFrames,
            pct: total > 0 ? Math.round((backgroundFrames / total) * 100) : 0,
          },
        ]
      : [])
  );

  root.innerHTML = rows
    .map(
      (row) => `
        <div class="space-y-1">
          <div class="flex items-center justify-between gap-2 text-[11px]">
            <div class="flex items-center gap-2 min-w-0">
              <span class="w-2.5 h-2.5 rounded-sm shrink-0" style="background:${escapeHtml(row.color)}"></span>
              <span class="truncate text-zinc-300">${escapeHtml(row.name)}</span>
            </div>
            <span class="font-mono text-zinc-500">${row.count} · ${row.pct}%</span>
          </div>
          <div class="h-1.5 rounded-full bg-zinc-950 overflow-hidden border border-zinc-800">
            <div class="h-full rounded-full" style="width:${row.pct}%; background:${escapeHtml(row.color)}"></div>
          </div>
        </div>`
    )
    .join("");

  if (hint) {
    if (total === 0) {
      hint.textContent =
        "Нет подсчитанных аннотаций и background-кадров (пустой проект или ещё не загружены детали).";
      hint.classList.remove("hidden");
    } else {
      hint.textContent =
        "Background — число confirmed пустых кадров (negative samples), классы — число боксов.";
      hint.classList.remove("hidden");
    }
  }
}

function imageMatchesClassFilter(image, filter, imageClassIds) {
  if (!filter.length) return true;
  const classIds = imageClassIds[image.id] || [];
  for (const token of filter) {
    if (token === BACKGROUND_FILTER) {
      if (image.is_background) return true;
      continue;
    }
    if (classIds.includes(token)) return true;
  }
  return false;
}

function imageMatchesStatusFilter(image, filter) {
  if (!filter.length) return true;
  return filter.includes(image.status);
}

function filteredImages() {
  const query = (store.get("galleryQuery") || "").trim().toLowerCase();
  const classFilter = store.get("galleryClassFilter") || [];
  const statusFilter = store.get("galleryStatusFilter") || [];
  const imageClassIds = store.get("imageClassIds") || {};
  return (store.get("images") || []).filter((image) => {
    if (query && !(image.file_name || "").toLowerCase().includes(query)) return false;
    if (!imageMatchesStatusFilter(image, statusFilter)) return false;
    if (!imageMatchesClassFilter(image, classFilter, imageClassIds)) return false;
    return true;
  });
}

function renderStatusFilters() {
  const root = document.getElementById("gallery-status-filters");
  if (!root) return;
  const active = new Set(store.get("galleryStatusFilter") || []);
  root.innerHTML = STATUS_FILTERS.map((item) => {
    const on = active.has(item.id);
    return `
      <button type="button" data-gallery-status="${item.id}"
        class="px-2 py-1 text-[11px] rounded-md border transition ${
          on ? item.active : "border-zinc-800 bg-zinc-950 text-zinc-400 hover:border-zinc-600"
        }"
        title="Фильтр: ${item.label}">
        ${item.label}
      </button>`;
  }).join("");
}

function renderClassFilters() {
  const root = document.getElementById("gallery-class-filters");
  if (!root) return;

  const classes = [...(store.get("classes") || [])].sort((a, b) => a.index_id - b.index_id);
  const images = store.get("images") || [];
  const backgroundFrames = countBackgroundFrames(images);
  const active = new Set(store.get("galleryClassFilter") || []);

  if (!classes.length && backgroundFrames <= 0) {
    root.innerHTML = "";
    return;
  }

  const chips = classes.map((cls) => {
    const on = active.has(cls.id);
    return `
      <button type="button" data-gallery-class="${escapeHtml(cls.id)}"
        class="px-2 py-1 text-[11px] rounded-md border flex items-center gap-1.5 transition ${
          on
            ? "border-indigo-500/60 bg-indigo-950/50 text-indigo-100"
            : "border-zinc-800 bg-zinc-950 text-zinc-400 hover:border-zinc-600"
        }"
        title="Фильтр: кадры с классом ${escapeHtml(cls.name)}">
        <span class="w-2 h-2 rounded-sm shrink-0" style="background:${escapeHtml(cls.color_hex)}"></span>
        <span class="truncate max-w-[7rem]">${escapeHtml(cls.name)}</span>
      </button>`;
  });

  if (backgroundFrames > 0 || active.has(BACKGROUND_FILTER)) {
    const on = active.has(BACKGROUND_FILTER);
    chips.push(`
      <button type="button" data-gallery-class="${BACKGROUND_FILTER}"
        class="px-2 py-1 text-[11px] rounded-md border flex items-center gap-1.5 transition ${
          on
            ? "border-sky-500/60 bg-sky-950/40 text-sky-100"
            : "border-zinc-800 bg-zinc-950 text-zinc-400 hover:border-zinc-600"
        }"
        title="Фильтр: background-кадры">
        <span class="w-2 h-2 rounded-sm shrink-0 bg-sky-400"></span>
        <span>background</span>
      </button>`);
  }

  root.innerHTML = chips.join("");
}

function syncSelectionBar() {
  const bar = document.getElementById("gallery-selection-bar");
  const countEl = document.getElementById("gallery-selected-count");
  if (!bar || !countEl) return;
  const selected = store.get("gallerySelectedIds") || [];
  const visible = new Set(filteredImages().map((item) => item.id));
  const visibleSelected = selected.filter((id) => visible.has(id)).length;
  countEl.textContent = String(selected.length);
  const show = selected.length > 0 || filteredImages().length > 0;
  bar.classList.toggle("hidden", !show);
  const selectAllBtn = document.getElementById("btn-gallery-select-all");
  if (selectAllBtn) {
    const allVisibleSelected =
      filteredImages().length > 0 && visibleSelected === filteredImages().length;
    selectAllBtn.textContent = allVisibleSelected ? "Снять все" : "Выбрать все";
  }
}

function renderGallery({ onOpenImage }) {
  const grid = document.getElementById("gallery-grid");
  const empty = document.getElementById("gallery-empty");
  if (!grid) return;

  const images = filteredImages();
  const counts = store.get("boxCounts") || {};
  const galleryAnnotations = store.get("galleryAnnotations") || {};
  const classes = store.get("classes") || [];
  const selected = selectedSet();
  empty?.classList.toggle("hidden", images.length > 0);
  grid.classList.toggle("hidden", images.length === 0);

  grid.innerHTML = images
    .map((image) => {
      const meta = statusMeta(image.status);
      const boxes = counts[image.id];
      const overlayBoxes = galleryAnnotations[image.id] || [];
      const boxLabel = typeof boxes === "number" ? `${boxes} box` : "—";
      const isSelected = selected.has(image.id);
      return `
        <div data-gallery-card="${image.id}"
          class="gallery-card relative text-left rounded-xl border overflow-hidden transition ${
            isSelected
              ? "border-indigo-500 bg-indigo-950/20"
              : "border-zinc-800 bg-zinc-900/50 hover:border-zinc-600"
          }">
          <label class="absolute top-2 right-2 z-10 flex items-center justify-center w-6 h-6 rounded-md bg-zinc-950/80 border border-zinc-700 cursor-pointer"
            title="Выбрать">
            <input type="checkbox" data-gallery-select="${image.id}" class="w-3.5 h-3.5 accent-indigo-500"
              ${isSelected ? "checked" : ""} />
          </label>
          <button type="button" data-open-gallery="${image.id}" class="w-full text-left group">
            <div class="relative aspect-video bg-zinc-950 overflow-hidden">
              <img src="${api.imageFileUrl(image.id)}" alt="" loading="lazy" decoding="async"
                class="w-full h-full object-cover opacity-90 group-hover:opacity-100 transition" />
              ${galleryBboxOverlay(image, overlayBoxes, classes)}
              <div class="absolute top-2 left-2 z-[1] flex gap-1">
                <span class="px-1.5 py-0.5 text-[10px] rounded border ${meta.badge}">${meta.label}</span>
              </div>
            </div>
            <div class="p-2.5 space-y-1">
              <div class="text-[11px] font-mono text-zinc-300 truncate" title="${escapeHtml(image.file_name)}">${escapeHtml(image.file_name)}</div>
              <div class="flex justify-between text-[10px] text-zinc-500">
                <span>${image.width}×${image.height}</span>
                <span>${boxLabel}</span>
              </div>
            </div>
          </button>
        </div>`;
    })
    .join("");

  grid.querySelectorAll("[data-open-gallery]").forEach((btn) => {
    btn.addEventListener("click", () => onOpenImage?.(btn.dataset.openGallery));
  });
  grid.querySelectorAll("[data-gallery-select]").forEach((input) => {
    input.addEventListener("click", (event) => event.stopPropagation());
    input.addEventListener("change", (event) => {
      event.stopPropagation();
      const id = input.dataset.gallerySelect;
      const next = selectedSet();
      if (input.checked) next.add(id);
      else next.delete(id);
      setSelectedIds([...next]);
    });
  });

  syncSelectionBar();
}

async function refreshClassCounts(images) {
  const targets = (images || []).filter((item) => item.status !== "UNANNOTATED");
  const counts = {};
  const nextBoxCounts = {};
  const nextImageClassIds = {};
  const nextGalleryAnnotations = {};
  if (!targets.length) {
    store.patch({
      classCounts: counts,
      imageClassIds: nextImageClassIds,
      galleryAnnotations: nextGalleryAnnotations,
    });
    return counts;
  }

  await mapPool(targets, 6, async (image) => {
    try {
      const detail = await api.getImage(image.id);
      const boxes = detail.annotations || [];
      nextBoxCounts[image.id] = boxes.length;
      nextGalleryAnnotations[image.id] = boxes;
      const classIds = [...new Set(boxes.map((box) => box.class_id).filter(Boolean))];
      nextImageClassIds[image.id] = classIds;
      for (const box of boxes) {
        counts[box.class_id] = (counts[box.class_id] || 0) + 1;
      }
    } catch {
      /* skip failed frame */
    }
  });
  store.patch({
    boxCounts: { ...store.get("boxCounts"), ...nextBoxCounts },
    classCounts: counts,
    imageClassIds: nextImageClassIds,
    galleryAnnotations: (() => {
      const merged = { ...(store.get("galleryAnnotations") || {}) };
      for (const image of images || []) {
        if (image.status === "UNANNOTATED") delete merged[image.id];
      }
      return { ...merged, ...nextGalleryAnnotations };
    })(),
  });
  return counts;
}

async function deleteSelected({ onError, onDeleted }) {
  const ids = [...(store.get("gallerySelectedIds") || [])];
  if (!ids.length) return;
  const ok = window.confirm(
    `Удалить выбранные кадры (${ids.length}) безвозвратно? Аннотации тоже будут удалены.`
  );
  if (!ok) return;

  let deleted = 0;
  const failed = [];
  const deletedIds = [];
  await mapPool(ids, 4, async (id) => {
    try {
      await api.deleteImage(id);
      deleted += 1;
      deletedIds.push(id);
    } catch (err) {
      failed.push(err.message || String(err));
    }
  });

  const removed = new Set(deletedIds);
  const remaining = (store.get("images") || []).filter((item) => !removed.has(item.id));
  const boxCounts = { ...(store.get("boxCounts") || {}) };
  const imageClassIds = { ...(store.get("imageClassIds") || {}) };
  const galleryAnnotations = { ...(store.get("galleryAnnotations") || {}) };
  for (const id of removed) {
    delete boxCounts[id];
    delete imageClassIds[id];
    delete galleryAnnotations[id];
  }
  const current = store.get("currentImage");
  const stillSelected = ids.filter((id) => !removed.has(id));
  store.patch({
    images: remaining,
    gallerySelectedIds: stillSelected,
    boxCounts,
    imageClassIds,
    galleryAnnotations,
    ...(current && removed.has(current.id)
      ? { currentImage: null, annotations: [], selectedBoxId: null, hoveredBoxId: null }
      : {}),
  });

  if (failed.length) {
    onError?.(`Удалено ${deleted}, ошибок: ${failed.length}`);
  } else {
    onDeleted?.(deleted);
  }
  await refreshClassCounts(remaining);
}

export function initDataHub({ onOpenImage, onStartAnnotate, onError, onDeleted }) {
  renderSplitFilters();
  syncClassBalanceCollapsed();

  document.getElementById("btn-toggle-class-balance")?.addEventListener("click", () => {
    store.set("classBalanceCollapsed", !store.get("classBalanceCollapsed"));
  });
  store.addEventListener("change:classBalanceCollapsed", syncClassBalanceCollapsed);

  document.getElementById("gallery-search")?.addEventListener("input", (event) => {
    store.set("galleryQuery", event.target.value);
  });

  document.getElementById("gallery-split-filters")?.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-gallery-split]");
    if (!btn) return;
    store.set("gallerySplit", btn.dataset.gallerySplit);
  });

  document.getElementById("gallery-class-filters")?.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-gallery-class]");
    if (!btn) return;
    const token = btn.dataset.galleryClass;
    const current = new Set(store.get("galleryClassFilter") || []);
    if (current.has(token)) current.delete(token);
    else current.add(token);
    store.set("galleryClassFilter", [...current]);
  });

  document.getElementById("gallery-status-filters")?.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-gallery-status]");
    if (!btn) return;
    const token = btn.dataset.galleryStatus;
    const current = new Set(store.get("galleryStatusFilter") || []);
    if (current.has(token)) current.delete(token);
    else current.add(token);
    store.set("galleryStatusFilter", [...current]);
  });

  document.getElementById("btn-gallery-annotate-first")?.addEventListener("click", () => {
    const first = filteredImages()[0] || (store.get("images") || [])[0];
    onStartAnnotate?.(first?.id || null);
  });

  document.getElementById("btn-gallery-select-all")?.addEventListener("click", () => {
    const visible = filteredImages().map((item) => item.id);
    const selected = selectedSet();
    const allSelected = visible.length > 0 && visible.every((id) => selected.has(id));
    if (allSelected) {
      for (const id of visible) selected.delete(id);
    } else {
      for (const id of visible) selected.add(id);
    }
    setSelectedIds([...selected]);
  });

  document.getElementById("btn-gallery-clear-selection")?.addEventListener("click", () => {
    setSelectedIds([]);
  });

  document.getElementById("btn-gallery-delete-selected")?.addEventListener("click", () => {
    deleteSelected({ onError, onDeleted }).catch((err) => onError?.(err.message));
  });

  const rerender = () => {
    renderSplitFilters();
    const images = store.get("images") || [];
    pruneSelection(images);
    renderStats(images);
    renderClassBars(
      store.get("classes") || [],
      store.get("classCounts") || {},
      countBackgroundFrames(images)
    );
    renderClassFilters();
    renderStatusFilters();
    renderGallery({ onOpenImage });
  };

  store.addEventListener("change:images", rerender);
  store.addEventListener("change:classes", rerender);
  store.addEventListener("change:classCounts", rerender);
  store.addEventListener("change:imageClassIds", () => {
    if (store.get("projectTab") !== "data") return;
    renderClassFilters();
    renderGallery({ onOpenImage });
  });
  store.addEventListener("change:boxCounts", () => {
    if (store.get("projectTab") !== "data") return;
    renderGallery({ onOpenImage });
  });
  store.addEventListener("change:galleryAnnotations", () => {
    if (store.get("projectTab") !== "data") return;
    renderGallery({ onOpenImage });
  });
  store.addEventListener("change:galleryQuery", () => {
    renderGallery({ onOpenImage });
    syncSelectionBar();
  });
  store.addEventListener("change:galleryClassFilter", () => {
    renderClassFilters();
    renderGallery({ onOpenImage });
  });
  store.addEventListener("change:galleryStatusFilter", () => {
    renderStatusFilters();
    renderGallery({ onOpenImage });
  });
  store.addEventListener("change:gallerySelectedIds", () => {
    renderGallery({ onOpenImage });
  });
  store.addEventListener("change:gallerySplit", rerender);
  store.addEventListener("change:currentProject", () => {
    clearGallerySelectionState();
  });

  return {
    async refresh() {
      const images = store.get("images") || [];
      pruneSelection(images);
      renderStats(images);
      renderStatusFilters();
      renderClassFilters();
      renderGallery({ onOpenImage });
      await refreshClassCounts(images);
      renderClassBars(
        store.get("classes") || [],
        store.get("classCounts") || {},
        countBackgroundFrames(images)
      );
      renderStatusFilters();
      renderClassFilters();
      renderGallery({ onOpenImage });
      refreshIcons(document.getElementById("tab-view-data"));
    },
  };
}
