import { store } from "../store.js";
import { api } from "../api.js";
import { escapeHtml, refreshIcons, splitBadgeClass } from "../utils/dom.js";

const FILTERS = [
  { id: "all", label: "Все" },
  { id: "review", label: "Требуют проверки" },
  { id: "unannotated", label: "Неразмеченные" },
];

function statusMeta(image) {
  if (image.status === "REQUIRES_REVIEW") {
    return { label: "Review", className: "text-amber-400", icon: "zap" };
  }
  if (image.status === "VERIFIED") {
    return { label: "Verified", className: "text-emerald-400", icon: "check-circle-2" };
  }
  return { label: "Empty", className: "text-zinc-500", icon: "circle" };
}

function filteredImages() {
  const query = (store.get("filmstripQuery") || "").trim().toLowerCase();
  const filter = store.get("filmstripFilter") || "all";
  return (store.get("images") || []).filter((image) => {
    if (query && !image.file_name.toLowerCase().includes(query)) return false;
    if (filter === "review" && image.status !== "REQUIRES_REVIEW") return false;
    if (filter === "unannotated" && image.status !== "UNANNOTATED") return false;
    return true;
  });
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
  const counts = store.get("boxCounts") || {};
  const known = Object.hasOwn(counts, image.id);
  if (!known) {
    if (image.status === "UNANNOTATED") return "0 боксов";
    // List API has no box count; avoid implying a known number.
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

function renderList() {
  const list = document.getElementById("filmstrip-list");
  const empty = document.getElementById("filmstrip-empty");
  const images = filteredImages();
  const currentId = store.get("currentImage")?.id;
  if (!images.length) {
    list.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  list.innerHTML = images
    .map((image) => {
      const active = image.id === currentId;
      const status = statusMeta(image);
      return `
        <button type="button" data-image-id="${image.id}"
          class="w-full text-left rounded-lg overflow-hidden border transition ${
            active
              ? "border-indigo-500 ring-2 ring-indigo-500/40 bg-zinc-900"
              : "border-zinc-800 bg-zinc-950/60 hover:border-zinc-600"
          }">
          <div class="aspect-video bg-zinc-950 overflow-hidden">
            <img src="${api.imageFileUrl(image.id)}" alt="${escapeHtml(image.file_name)}"
              class="w-full h-full object-cover" loading="lazy" />
          </div>
          <div class="p-2 space-y-1">
            <div class="text-[11px] font-mono truncate ${active ? "text-white" : "text-zinc-300"}">${escapeHtml(image.file_name)}</div>
            <div class="text-[10px] text-zinc-500">${image.width}×${image.height}</div>
            <div class="flex items-center justify-between gap-1">
              <span class="px-1.5 py-0.5 text-[9px] uppercase rounded border ${splitBadgeClass(image.split)}">${image.split}</span>
              <span class="flex items-center gap-1 text-[10px] ${status.className}">
                <i data-lucide="${status.icon}" class="w-3 h-3"></i>${status.label}
              </span>
            </div>
            <div class="text-[10px] text-zinc-500">${boxCountLabel(image)}</div>
          </div>
        </button>`;
    })
    .join("");
  refreshIcons(list);
  if (currentId) {
    list.querySelector(`[data-image-id="${currentId}"]`)?.scrollIntoView({ block: "nearest" });
  }
}

export function initFilmstrip({ onOpenImage }) {
  renderFilters();
  renderList();

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

  store.addEventListener("change:images", renderList);
  store.addEventListener("change:currentImage", renderList);
  store.addEventListener("change:boxCounts", renderList);
  store.addEventListener("change:filmstripQuery", renderList);
  store.addEventListener("change:filmstripFilter", () => {
    renderFilters();
    renderList();
  });
}
