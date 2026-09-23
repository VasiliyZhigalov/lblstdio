import { store, isClassification } from "../store.js";
import { api } from "../api.js";
import { escapeHtml } from "../utils/dom.js";
import {
  clearGalleryFilters,
  describeGalleryFilters,
  galleryFilterState,
  hasActiveGalleryFilters,
  matchesGalleryFilters,
} from "../utils/imageFilters.js";

const FILTERS = [
  { id: "all", label: "Все" },
  { id: "review", label: "Требуют проверки" },
  { id: "unannotated", label: "Неразмеченные" },
  { id: "auto_verified", label: "Автоверифицированные" },
];

const GAP_PX = 8;
const DEFAULT_ITEM_HEIGHT = 208;
const OVERSCAN = 6;

const virtual = {
  images: [],
  itemHeight: DEFAULT_ITEM_HEIGHT,
  scrollBound: false,
  measured: false,
  raf: 0,
};

function statusMeta(image) {
  if (image.status === "REQUIRES_RECHECK") {
    return { label: "Подозрительное", className: "text-red-400" };
  }
  if (image.status === "REQUIRES_REVIEW") {
    return { label: "На проверке", className: "text-amber-400" };
  }
  if (image.status === "VERIFIED") {
    if (image.is_background) {
      return { label: "Фон", className: "text-sky-400" };
    }
    return { label: "Подтверждено", className: "text-emerald-400" };
  }
  if (image.status === "AUTO_VERIFIED") {
    return { label: "Автоматически подтверждено", className: "text-cyan-400" };
  }
  return { label: "Без разметки", className: "text-zinc-500" };
}

function filteredImages() {
  const query = (store.get("filmstripQuery") || "").trim().toLowerCase();
  const filter = store.get("filmstripFilter") || "all";
  const gallery = galleryFilterState(store);
  return (store.get("images") || []).filter((image) => {
    if (!matchesGalleryFilters(image, gallery)) return false;
    if (query && !(image.file_name || "").toLowerCase().includes(query)) return false;
    if (filter === "review" &&
      image.status !== "REQUIRES_REVIEW" &&
      image.status !== "REQUIRES_RECHECK"
    ) {
      return false;
    }
    if (filter === "unannotated" && image.status !== "UNANNOTATED") return false;
    if (filter === "auto_verified" && image.status !== "AUTO_VERIFIED") return false;
    return true;
  });
}

function syncGalleryFilterBanner() {
  const root = document.getElementById("filmstrip-gallery-filter");
  const label = document.getElementById("filmstrip-gallery-filter-label");
  if (!root || !label) return;
  const state = galleryFilterState(store);
  const active = hasActiveGalleryFilters(state);
  root.classList.toggle("hidden", !active);
  if (active) {
    const summary = describeGalleryFilters(state, store.get("classes") || []);
    label.textContent = summary ? `Фильтр: ${summary}` : "Фильтр с вкладки «Данные»";
  }
}

/** Filtered list for A/D; keeps the current frame reachable if the filter hides it. */
export function getFilmstripImages() {
  const filtered = filteredImages();
  const currentId = store.get("currentImage")?.id;
  if (currentId && !filtered.some((image) => image.id === currentId)) {
    const current = (store.get("images") || []).find((image) => image.id === currentId);
    if (current) return [current, ...filtered];
  }
  return filtered;
}

function boxCountLabel(image) {
  if (isClassification()) {
    const label = image.label;
    if (!label) return "без класса";
    const cls = (store.get("classes") || []).find((item) => item.id === label.class_id);
    const name = cls?.name || "класс";
    if (label.verification_status === "PENDING_REVIEW") {
      return `${name} ${Math.round(Number(label.confidence || 0) * 100)}%`;
    }
    return name;
  }
  const counts = store.get("boxCounts") || {};
  const known = Object.hasOwn(counts, image.id);
  if (image.is_background && image.status === "VERIFIED") {
    return "бэкграунд";
  }
  if (!known) {
    if (image.status === "UNANNOTATED") return "0 боксов";
    return "размечен";
  }
  const n = counts[image.id];
  const mod10 = n % 10;
  const mod100 = n % 100;
  let word = "боксов";
  if (mod10 === 1 && mod100 !== 11) word = "бокс";
  else if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) word = "бокса";
  return `${n} ${word}`;
}

function renderFilters() {
  const root = document.getElementById("filmstrip-filters");
  const current = store.get("filmstripFilter");
  root.innerHTML = FILTERS.map((item) => {
    const active = item.id === current;
    return `<button type="button" data-film-filter="${item.id}"
      class="px-2 py-0.5 text-[10px] rounded ${
        active ? "bg-indigo-600 text-white" : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"
      }">${item.label}</button>`;
  }).join("");
}

function cardHtml(image, currentId) {
  const active = image.id === currentId;
  const status = statusMeta(image);
  return `
    <button type="button" data-image-id="${image.id}" data-film-card
      class="w-full text-left rounded-lg overflow-hidden border transition ${
        active
          ? "border-indigo-500 ring-2 ring-indigo-500/40 bg-zinc-900"
          : "border-zinc-800 bg-zinc-950/60 hover:border-zinc-600"
      }">
      <div class="aspect-video bg-zinc-950 overflow-hidden">
        <img src="${api.imageFileUrl(image.id)}" alt="${escapeHtml(image.file_name)}"
          class="w-full h-full object-cover" loading="lazy" decoding="async" />
      </div>
      <div class="p-2 space-y-1">
        <div class="text-[11px] font-mono truncate ${active ? "text-white" : "text-zinc-300"}">${escapeHtml(image.file_name)}</div>
        <div class="text-[10px] text-zinc-500">${image.width}×${image.height}</div>
        <div class="flex items-center justify-between gap-1">
          <span class="text-[10px] ${status.className}" data-status-label>${status.label}</span>
        </div>
        <div class="text-[10px] text-zinc-500" data-box-count>${boxCountLabel(image)}</div>
      </div>
    </button>`;
}

function stride() {
  return virtual.itemHeight + GAP_PX;
}

function ensureScrollBinding(list) {
  if (virtual.scrollBound) return;
  virtual.scrollBound = true;
  list.addEventListener(
    "scroll",
    () => {
      if (virtual.raf) return;
      virtual.raf = requestAnimationFrame(() => {
        virtual.raf = 0;
        paintVisible({ preserveScroll: true });
      });
    },
    { passive: true }
  );
}

function measureItemHeight(list) {
  if (virtual.measured) return;
  const card = list.querySelector("[data-film-card]");
  if (!card) return;
  const height = card.getBoundingClientRect().height;
  if (height > 40) {
    virtual.itemHeight = height;
    virtual.measured = true;
  }
}

function paintVisible({ scrollToCurrent = false } = {}) {
  const list = document.getElementById("filmstrip-list");
  const empty = document.getElementById("filmstrip-empty");
  if (!list || !empty) return;

  const images = virtual.images;
  const currentId = store.get("currentImage")?.id;

  if (!images.length) {
    list.innerHTML = "";
    empty.classList.remove("hidden");
    empty.textContent = hasActiveGalleryFilters(galleryFilterState(store))
      ? "Нет кадров по текущему фильтру."
      : "Нет кадров. Загрузите на вкладке «Данные».";
    return;
  }
  empty.classList.add("hidden");
  ensureScrollBinding(list);

  const step = stride();
  const totalHeight = images.length * step - GAP_PX;

  if (scrollToCurrent && currentId) {
    const idx = images.findIndex((image) => image.id === currentId);
    if (idx >= 0) {
      const targetTop = idx * step;
      const viewH = list.clientHeight || 1;
      if (targetTop < list.scrollTop || targetTop + virtual.itemHeight > list.scrollTop + viewH) {
        list.scrollTop = Math.max(0, targetTop - (viewH - virtual.itemHeight) / 2);
      }
    }
  }

  const scrollTop = list.scrollTop;
  const viewH = list.clientHeight || 600;
  const start = Math.max(0, Math.floor(scrollTop / step) - OVERSCAN);
  const end = Math.min(images.length, Math.ceil((scrollTop + viewH) / step) + OVERSCAN);
  const slice = images.slice(start, end);

  list.innerHTML = `
    <div data-film-spacer style="position:relative;height:${Math.max(0, totalHeight)}px">
      ${slice
        .map((image, offset) => {
          const index = start + offset;
          return `<div data-film-slot style="position:absolute;left:0;right:0;top:${index * step}px">${cardHtml(
            image,
            currentId
          )}</div>`;
        })
        .join("")}
    </div>`;

  const heightBefore = virtual.itemHeight;
  measureItemHeight(list);
  if (virtual.itemHeight !== heightBefore) {
    // Height learned from first paint — rebuild once with accurate stride.
    paintVisible({ scrollToCurrent });
  }
}

function syncVisibleMeta() {
  const list = document.getElementById("filmstrip-list");
  if (!list) return;
  const currentId = store.get("currentImage")?.id;
  const activeClass =
    "w-full text-left rounded-lg overflow-hidden border transition border-indigo-500 ring-2 ring-indigo-500/40 bg-zinc-900";
  const idleClass =
    "w-full text-left rounded-lg overflow-hidden border transition border-zinc-800 bg-zinc-950/60 hover:border-zinc-600";

  list.querySelectorAll("[data-film-card]").forEach((card) => {
    const id = card.dataset.imageId;
    const active = id === currentId;
    card.className = active ? activeClass : idleClass;
    const name = card.querySelector(".font-mono");
    if (name) name.className = `text-[11px] font-mono truncate ${active ? "text-white" : "text-zinc-300"}`;
    const image = virtual.images.find((item) => item.id === id);
    if (!image) return;
    const countEl = card.querySelector("[data-box-count]");
    if (countEl) countEl.textContent = boxCountLabel(image);
    const statusEl = card.querySelector("[data-status-label]");
    if (statusEl) {
      const status = statusMeta(image);
      statusEl.className = `text-[10px] ${status.className}`;
      statusEl.textContent = status.label;
    }
  });
}

function sameImageOrder(prev, next) {
  return (
    prev.length === next.length && prev.every((image, index) => image.id === next[index]?.id)
  );
}

function onImagesChange() {
  const next = filteredImages();
  if (sameImageOrder(virtual.images, next)) {
    virtual.images = next;
    syncVisibleMeta();
    return;
  }
  rebuildList({ scrollToCurrent: true });
}

function rebuildList({ scrollToCurrent = false } = {}) {
  virtual.images = filteredImages();
  virtual.measured = false;
  virtual.itemHeight = DEFAULT_ITEM_HEIGHT;
  paintVisible({ scrollToCurrent });
}

function onCurrentImageChange() {
  const currentId = store.get("currentImage")?.id;
  if (!currentId) {
    syncVisibleMeta();
    return;
  }
  const visible = document
    .getElementById("filmstrip-list")
    ?.querySelector(`[data-image-id="${currentId}"]`);
  if (visible) {
    syncVisibleMeta();
    visible.scrollIntoView({ block: "nearest" });
    return;
  }
  paintVisible({ scrollToCurrent: true });
}

export function initFilmstrip({ onOpenImage }) {
  renderFilters();
  syncGalleryFilterBanner();
  rebuildList();

  document.getElementById("filmstrip-filters").addEventListener("click", (event) => {
    const btn = event.target.closest("[data-film-filter]");
    if (btn) store.set("filmstripFilter", btn.dataset.filmFilter);
  });
  document.getElementById("filmstrip-search").addEventListener("input", (event) => {
    store.set("filmstripQuery", event.target.value);
  });
  document.getElementById("filmstrip-list").addEventListener("click", (event) => {
    const card = event.target.closest("[data-image-id]");
    if (card) onOpenImage(card.dataset.imageId);
  });
  document.getElementById("btn-clear-image-filters")?.addEventListener("click", () => {
    clearGalleryFilters(store);
  });

  const onGalleryFilterChange = () => {
    syncGalleryFilterBanner();
    rebuildList({ scrollToCurrent: true });
  };

  store.addEventListener("change:images", onImagesChange);
  store.addEventListener("change:currentImage", onCurrentImageChange);
  store.addEventListener("change:boxCounts", () => {
    if (
      store.get("galleryBoxCountMin") != null ||
      store.get("galleryBoxCountMax") != null
    ) {
      onImagesChange();
      return;
    }
    syncVisibleMeta();
  });
  store.addEventListener("change:imageClassIds", () => {
    if ((store.get("galleryClassFilter") || []).length) onImagesChange();
  });
  store.addEventListener("change:filmstripQuery", () => rebuildList());
  store.addEventListener("change:filmstripFilter", () => {
    renderFilters();
    rebuildList();
  });
  store.addEventListener("change:galleryQuery", onGalleryFilterChange);
  store.addEventListener("change:galleryClassFilter", onGalleryFilterChange);
  store.addEventListener("change:galleryStatusFilter", onGalleryFilterChange);
  store.addEventListener("change:galleryBoxCountMin", onGalleryFilterChange);
  store.addEventListener("change:galleryBoxCountMax", onGalleryFilterChange);
  store.addEventListener("change:projectTab", () => {
    if (store.get("projectTab") !== "annotate") return;
    syncGalleryFilterBanner();
    requestAnimationFrame(() => {
      virtual.measured = false;
      paintVisible({ scrollToCurrent: true });
    });
  });
}
