/**
 * Run: node --experimental-vm-modules js/utils/imageFilters.test.mjs
 * (from frontend/)
 */
import {
  BACKGROUND_FILTER,
  clearGalleryFilters,
  describeGalleryFilters,
  hasActiveGalleryFilters,
  imageBoxCount,
  imageMatchesBoxCountFilter,
  imageMatchesClassFilter,
  imageMatchesQuery,
  matchesGalleryFilters,
  parseBoxCountBound,
} from "./imageFilters.js";

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

assert(parseBoxCountBound("") === null, "empty bound");
assert(parseBoxCountBound("  ") === null, "blank bound");
assert(parseBoxCountBound("0") === 0, "zero bound");
assert(parseBoxCountBound("3.9") === 3, "floor bound");
assert(parseBoxCountBound("-1") === null, "negative bound");
assert(parseBoxCountBound("x") === null, "nan bound");

const unannotated = { id: "a", status: "UNANNOTATED", file_name: "cat.jpg", is_background: false };
const background = { id: "b", status: "VERIFIED", file_name: "bg.png", is_background: true };
const labeled = { id: "c", status: "VERIFIED", file_name: "dog.jpg", is_background: false };

assert(imageBoxCount(unannotated, {}) === 0, "unannotated is 0 boxes");
assert(imageBoxCount(background, {}) === 0, "background is 0 boxes");
assert(imageBoxCount(labeled, {}) === null, "unknown count stays null");
assert(imageBoxCount(labeled, { c: 4 }) === 4, "known count");

assert(imageMatchesBoxCountFilter(labeled, null, null, {}) === true, "no box filter");
assert(imageMatchesBoxCountFilter(labeled, 1, null, {}) === false, "unknown excluded");
assert(imageMatchesBoxCountFilter(labeled, 2, 5, { c: 4 }) === true, "in range");
assert(imageMatchesBoxCountFilter(labeled, 5, 2, { c: 4 }) === true, "swapped range");
assert(imageMatchesBoxCountFilter(labeled, 5, null, { c: 4 }) === false, "below min");
assert(imageMatchesBoxCountFilter(unannotated, 0, 0, {}) === true, "zero boxes");

assert(imageMatchesQuery(labeled, "") === true, "empty query");
assert(imageMatchesQuery(labeled, "DOG") === true, "query case");
assert(imageMatchesQuery(labeled, "cat") === false, "query miss");

assert(
  imageMatchesClassFilter(background, [BACKGROUND_FILTER], {}) === true,
  "background class token"
);
assert(imageMatchesClassFilter(labeled, ["cls-1"], { c: ["cls-1"] }) === true, "class hit");
assert(imageMatchesClassFilter(labeled, ["cls-1"], { c: ["cls-2"] }) === false, "class miss");

const state = {
  query: "",
  classFilter: [],
  statusFilter: ["VERIFIED"],
  boxCountMin: 2,
  boxCountMax: null,
  imageClassIds: { c: ["car"] },
  boxCounts: { c: 3 },
};
assert(hasActiveGalleryFilters(state) === true, "active filters");
assert(
  hasActiveGalleryFilters({
    query: "",
    classFilter: [],
    statusFilter: [],
    boxCountMin: null,
    boxCountMax: null,
  }) === false,
  "empty not active"
);
assert(matchesGalleryFilters(labeled, state) === true, "verified with 3 boxes");
assert(matchesGalleryFilters(unannotated, state) === false, "status mismatch");
assert(
  matchesGalleryFilters(labeled, { ...state, boxCountMin: 4 }) === false,
  "box count mismatch"
);

const desc = describeGalleryFilters(
  { ...state, query: "dog", classFilter: ["car", BACKGROUND_FILTER] },
  [{ id: "car", name: "Авто" }]
);
assert(desc.includes("имя: dog"), "describe query");
assert(desc.includes("верифицированные"), "describe status");
assert(desc.includes("Авто"), "describe class");
assert(desc.includes("background"), "describe background");
assert(desc.includes("боксы ≥ 2"), "describe min boxes");

const patched = {};
clearGalleryFilters({
  patch(partial) {
    Object.assign(patched, partial);
  },
});
assert(patched.galleryQuery === "", "clear query");
assert(Array.isArray(patched.galleryClassFilter) && patched.galleryClassFilter.length === 0, "clear class");
assert(patched.galleryBoxCountMin === null && patched.galleryBoxCountMax === null, "clear box count");

console.log("imageFilters.test.mjs ok");
