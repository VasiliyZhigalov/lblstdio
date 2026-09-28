import { store } from "./store.js";
import { createAnnotationHistory } from "./utils/annotationHistory.js";

const history = createAnnotationHistory();

function applyRestored(annotations) {
  const selected = store.get("selectedBoxId");
  store.patch({
    annotations,
    selectedBoxId: annotations.some((box) => box.id === selected) ? selected : null,
    hoveredBoxId: null,
    hasUnsavedChanges: true,
    saveStatus: "unsaved",
  });
}

export function resetAnnotationHistory() {
  history.reset();
}

export function beginAnnotationGesture() {
  history.beginGesture(store.get("annotations"));
}

export function endAnnotationGesture() {
  return history.endGesture(store.get("annotations"));
}

export function commitAnnotationChange(before) {
  return history.commit(before, store.get("annotations"));
}

export function undoAnnotationChange() {
  const restored = history.undo(store.get("annotations"));
  if (!restored) return false;
  applyRestored(restored);
  return true;
}

export function redoAnnotationChange() {
  const restored = history.redo(store.get("annotations"));
  if (!restored) return false;
  applyRestored(restored);
  return true;
}
