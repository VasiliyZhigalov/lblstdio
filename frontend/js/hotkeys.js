import { store } from "./store.js";

function isTypingTarget(target) {
  if (!target) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

export function initHotkeys({
  setMode,
  fit,
  prev,
  next,
  deleteSelected,
  selectClass,
  save,
}) {
  window.addEventListener("keydown", (event) => {
    if (isTypingTarget(event.target)) return;
    if (store.get("view") !== "studio") return;

    const key = event.key;
    const code = event.code;

    if (code === "Space") {
      event.preventDefault();
      if (!event.repeat) store.set("spaceHeld", true);
      return;
    }

    if (event.ctrlKey || event.metaKey) {
      if (key.toLowerCase() === "s") {
        event.preventDefault();
        save();
      }
      return;
    }

    if (key === "w" || key === "W") {
      event.preventDefault();
      setMode("DRAW");
      return;
    }
    if (key === "v" || key === "V") {
      event.preventDefault();
      setMode("SELECT");
      return;
    }
    if (key === "f" || key === "F") {
      event.preventDefault();
      fit();
      return;
    }
    if (key === "d" || key === "D" || key === "ArrowRight") {
      event.preventDefault();
      if (!event.repeat) next();
      return;
    }
    if (key === "a" || key === "A" || key === "ArrowLeft") {
      event.preventDefault();
      if (!event.repeat) prev();
      return;
    }
    if (key === "Delete" || key === "Backspace") {
      event.preventDefault();
      deleteSelected();
      return;
    }
    if (/^[1-9]$/.test(key)) {
      event.preventDefault();
      selectClass(Number(key));
    }
  });

  window.addEventListener("keyup", (event) => {
    if (event.code === "Space") {
      store.set("spaceHeld", false);
    }
  });

  window.addEventListener("blur", () => store.set("spaceHeld", false));
}
