/**
 * Shared gallery filters: status, class, search, box count.
 * Applied on Data Hub and kept when opening the annotate tab.
 */
export const BACKGROUND_FILTER = "__background__";

export function parseBoxCountBound(value) {
  const text = String(value ?? "").trim();
  if (text === "") return null;
  const n = Number(text);
  if (!Number.isFinite(n) || n < 0) return null;
  return Math.floor(n);
}

export function imageBoxCount(image, boxCounts = {}) {
  if (image?.id && Object.hasOwn(boxCounts, image.id)) return boxCounts[image.id];
  if (!image) return null;
  if (image.status === "UNANNOTATED") return 0;
  if (image.is_background) return 0;
  return null;
}

export function imageMatchesQuery(image, query) {
  const q = (query || "").trim().toLowerCase();
  if (!q) return true;
  return (image.file_name || "").toLowerCase().includes(q);
}

export function imageMatchesClassFilter(image, filter, imageClassIds) {
  if (!filter?.length) return true;
  const classIds = imageClassIds?.[image.id] || [];
  for (const token of filter) {
    if (token === BACKGROUND_FILTER) {
      if (image.is_background) return true;
      continue;
    }
    if (classIds.includes(token)) return true;
  }
  return false;
}

export function imageMatchesStatusFilter(image, filter) {
  if (!filter?.length) return true;
  return filter.includes(image.status);
}

export function imageMatchesBoxCountFilter(image, min, max, boxCounts) {
  if (min == null && max == null) return true;
  const n = imageBoxCount(image, boxCounts);
  if (n == null) return false;
  let lo = min;
  let hi = max;
  if (lo != null && hi != null && lo > hi) {
    [lo, hi] = [hi, lo];
  }
  if (lo != null && n < lo) return false;
  if (hi != null && n > hi) return false;
  return true;
}

export function emptyGalleryFilters() {
  return {
    galleryQuery: "",
    galleryClassFilter: [],
    galleryStatusFilter: [],
    galleryBoxCountMin: null,
    galleryBoxCountMax: null,
  };
}

export function galleryFilterState(store) {
  return {
    query: store.get("galleryQuery") || "",
    classFilter: store.get("galleryClassFilter") || [],
    statusFilter: store.get("galleryStatusFilter") || [],
    boxCountMin: store.get("galleryBoxCountMin"),
    boxCountMax: store.get("galleryBoxCountMax"),
    imageClassIds: store.get("imageClassIds") || {},
    boxCounts: store.get("boxCounts") || {},
  };
}

export function hasActiveGalleryFilters(state) {
  return Boolean(
    (state.query || "").trim() ||
      (state.classFilter || []).length ||
      (state.statusFilter || []).length ||
      state.boxCountMin != null ||
      state.boxCountMax != null
  );
}

export function matchesGalleryFilters(image, state) {
  if (!imageMatchesQuery(image, state.query)) return false;
  if (!imageMatchesStatusFilter(image, state.statusFilter)) return false;
  if (!imageMatchesClassFilter(image, state.classFilter, state.imageClassIds)) return false;
  if (
    !imageMatchesBoxCountFilter(image, state.boxCountMin, state.boxCountMax, state.boxCounts)
  ) {
    return false;
  }
  return true;
}

export function describeGalleryFilters(state, classes = []) {
  const parts = [];
  const q = (state.query || "").trim();
  if (q) parts.push(`имя: ${q}`);
  if (state.statusFilter?.length) {
    const labels = {
      UNANNOTATED: "неразмеченные",
      VERIFIED: "верифицированные",
      AUTO_VERIFIED: "автоверифицированные",
      REQUIRES_REVIEW: "на проверке",
      REQUIRES_RECHECK: "повторная проверка",
    };
    parts.push(state.statusFilter.map((id) => labels[id] || id).join(", "));
  }
  if (state.classFilter?.length) {
    const byId = new Map((classes || []).map((cls) => [cls.id, cls.name]));
    parts.push(
      state.classFilter
        .map((token) => (token === BACKGROUND_FILTER ? "background" : byId.get(token) || token))
        .join(", ")
    );
  }
  if (state.boxCountMin != null || state.boxCountMax != null) {
    const lo = state.boxCountMin;
    const hi = state.boxCountMax;
    if (lo != null && hi != null) parts.push(`боксы ${lo}–${hi}`);
    else if (lo != null) parts.push(`боксы ≥ ${lo}`);
    else parts.push(`боксы ≤ ${hi}`);
  }
  return parts.join(" · ");
}

export function clearGalleryFilters(store) {
  store.patch(emptyGalleryFilters());
}
