import { store } from "./store.js";

const MODAL_IDS = [
  "upload-modal",
  "project-modal",
  "clear-modal",
  "delete-project-modal",
  "rename-asset-modal",
  "delete-asset-modal",
  "dataset-modal",
  "training-drawer",
  "autolabel-modal",
];

function isTypingTarget(target) {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  const editable =
    tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
  if (!editable) return false;
  if (target.disabled) return false;
  if (target.closest(".hidden")) return false;
  return true;
}

function isModalOpen() {
  return MODAL_IDS.some((id) => {
    const el = document.getElementById(id);
    return el && !el.classList.contains("hidden");
  });
}

function inAnnotateStudio() {
  return store.get("view") === "studio" && store.get("projectTab") === "annotate";
}

export function initHotkeys({
  setMode,
  fit,
  prev,
  next,
  deleteSelected,
  selectClass,
  save,
  verifyAll,
  rejectAll,
  hasPending,
  copySelected,
  pastePropagate,
  toggleHide,
  toggleLeftSidebar,
  toggleRightSidebar,
  applyQuickClassDigit,
  openQuickClass,
}) {
  window.addEventListener("keydown", (event) => {
    if (isTypingTarget(event.target)) return;
    if (store.get("view") !== "studio") return;
    if (isModalOpen()) return;

    const code = event.code;

    // Sidebar collapse works on any project tab while shell is open? Spec: annotate only.
    if (!event.ctrlKey && !event.metaKey && !event.altKey) {
      if (code === "BracketLeft" && inAnnotateStudio()) {
        event.preventDefault();
        if (!event.repeat) toggleLeftSidebar?.();
        return;
      }
      if (code === "BracketRight" && inAnnotateStudio()) {
        event.preventDefault();
        if (!event.repeat) toggleRightSidebar?.();
        return;
      }
    }

    if (!inAnnotateStudio()) return;

    if (store.get("matchingInProgress")) {
      event.preventDefault();
      return;
    }

    if (code === "Space") {
      event.preventDefault();
      if (hasPending?.()) {
        if (!event.repeat) verifyAll?.();
        return;
      }
      if (!event.repeat) store.set("spaceHeld", true);
      return;
    }

    if (event.ctrlKey || event.metaKey) {
      if (code === "KeyS") {
        event.preventDefault();
        save();
        return;
      }
      if (code === "KeyC" && !event.shiftKey) {
        event.preventDefault();
        copySelected?.();
        return;
      }
      if (code === "KeyV" && event.shiftKey) {
        event.preventDefault();
        pastePropagate?.();
        return;
      }
      return;
    }

    if (code === "KeyH") {
      event.preventDefault();
      if (!event.repeat) toggleHide?.();
      return;
    }

    if (code === "KeyC" && !event.shiftKey) {
      event.preventDefault();
      if (!event.repeat) openQuickClass?.();
      return;
    }

    if (code === "Escape" && store.get("quickClassOpen")) {
      event.preventDefault();
      store.set("quickClassOpen", false);
      return;
    }

    if (code === "KeyR") {
      if (hasPending?.()) {
        event.preventDefault();
        if (!event.repeat) rejectAll?.();
        return;
      }
    }

    if (code === "KeyW") {
      event.preventDefault();
      setMode("DRAW");
      return;
    }
    if (code === "KeyV") {
      event.preventDefault();
      setMode("SELECT");
      return;
    }
    if (code === "KeyF") {
      event.preventDefault();
      fit();
      return;
    }
    if (code === "KeyD" || code === "ArrowRight") {
      event.preventDefault();
      if (!event.repeat) next();
      return;
    }
    if (code === "KeyA" || code === "ArrowLeft") {
      event.preventDefault();
      if (!event.repeat) prev();
      return;
    }
    if (code === "Delete" || code === "Backspace") {
      event.preventDefault();
      deleteSelected();
      return;
    }
    if (/^Digit[1-9]$/.test(code)) {
      event.preventDefault();
      const digit = Number(code.slice(-1));
      if (store.get("quickClassOpen") && applyQuickClassDigit?.(digit)) return;
      selectClass(digit);
    }
  });

  window.addEventListener("keyup", (event) => {
    if (event.code === "Space") {
      store.set("spaceHeld", false);
    }
  });

  window.addEventListener("blur", () => store.set("spaceHeld", false));
}
