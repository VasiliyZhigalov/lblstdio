import { store } from "../store.js";
import { api } from "../api.js";
import { escapeHtml, refreshIcons } from "../utils/dom.js";

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

function filteredImages() {
  const query = (store.get("galleryQuery") || "").trim().toLowerCase();
  return (store.get("images") || []).filter((image) => {
    if (query && !(image.file_name || "").toLowerCase().includes(query)) return false;
    return true;
  });
}

function renderGallery({ onOpenImage }) {
  const grid = document.getElementById("gallery-grid");
  const empty = document.getElementById("gallery-empty");
  if (!grid) return;

  const images = filteredImages();
  const counts = store.get("boxCounts") || {};
  empty?.classList.toggle("hidden", images.length > 0);
  grid.classList.toggle("hidden", images.length === 0);

  grid.innerHTML = images
    .map((image) => {
      const meta = statusMeta(image.status);
      const boxes = counts[image.id];
      const boxLabel = typeof boxes === "number" ? `${boxes} box` : "—";
      return `
        <button type="button" data-open-gallery="${image.id}"
          class="gallery-card group text-left rounded-xl border border-zinc-800 bg-zinc-900/50 overflow-hidden hover:border-zinc-600 transition">
          <div class="relative aspect-video bg-zinc-950 overflow-hidden">
            <img src="${api.imageFileUrl(image.id)}" alt="" loading="lazy" decoding="async"
              class="w-full h-full object-cover opacity-90 group-hover:opacity-100 transition" />
            <div class="absolute top-2 left-2 flex gap-1">
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
        </button>`;
    })
    .join("");

  grid.querySelectorAll("[data-open-gallery]").forEach((btn) => {
    btn.addEventListener("click", () => onOpenImage?.(btn.dataset.openGallery));
  });
}

async function refreshClassCounts(images) {
  const targets = (images || []).filter((item) => item.status !== "UNANNOTATED");
  const counts = {};
  const nextBoxCounts = {};
  if (!targets.length) {
    store.set("classCounts", counts);
    return counts;
  }

  await mapPool(targets, 6, async (image) => {
    try {
      const detail = await api.getImage(image.id);
      const boxes = detail.annotations || [];
      nextBoxCounts[image.id] = boxes.length;
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
  });
  return counts;
}

export function initDataHub({ onOpenImage, onStartAnnotate }) {
  renderSplitFilters();

  document.getElementById("gallery-search")?.addEventListener("input", (event) => {
    store.set("galleryQuery", event.target.value);
  });

  document.getElementById("gallery-split-filters")?.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-gallery-split]");
    if (!btn) return;
    store.set("gallerySplit", btn.dataset.gallerySplit);
  });

  document.getElementById("btn-gallery-annotate-first")?.addEventListener("click", () => {
    const first = filteredImages()[0] || (store.get("images") || [])[0];
    onStartAnnotate?.(first?.id || null);
  });

  const rerender = () => {
    renderSplitFilters();
    const images = store.get("images") || [];
    renderStats(images);
    renderClassBars(
      store.get("classes") || [],
      store.get("classCounts") || {},
      countBackgroundFrames(images)
    );
    renderGallery({ onOpenImage });
  };

  store.addEventListener("change:images", rerender);
  store.addEventListener("change:classes", rerender);
  store.addEventListener("change:classCounts", rerender);
  store.addEventListener("change:boxCounts", () => {
    if (store.get("projectTab") !== "data") return;
    renderGallery({ onOpenImage });
  });
  store.addEventListener("change:galleryQuery", () => renderGallery({ onOpenImage }));
  store.addEventListener("change:gallerySplit", rerender);

  return {
    async refresh() {
      const images = store.get("images") || [];
      renderStats(images);
      renderGallery({ onOpenImage });
      await refreshClassCounts(images);
      renderClassBars(
        store.get("classes") || [],
        store.get("classCounts") || {},
        countBackgroundFrames(images)
      );
      refreshIcons(document.getElementById("tab-view-data"));
    },
  };
}
