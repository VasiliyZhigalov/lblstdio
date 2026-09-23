import { store, isClassification } from "../store.js";

function pendingCount(annotations) {
  return (annotations || []).filter((box) => box.verification_status === "PENDING_REVIEW")
    .length;
}

export function initReviewBar({ onApproveAll, onRejectAll, onDeleteImage }) {
  const bar = document.getElementById("review-bar");
  const countEl = document.getElementById("pending-count");
  const labelEl = document.getElementById("review-bar-label");
  const approveBtn = document.getElementById("btn-approve-all");
  const rejectBtn = document.getElementById("btn-reject-all");
  const deleteImageBtn = document.getElementById("btn-delete-image");
  if (!bar || !countEl || !approveBtn || !rejectBtn || !deleteImageBtn) return;

  function sync() {
    if (isClassification()) {
      const image = store.get("currentImage");
      const pending = image?.label?.verification_status === "PENDING_REVIEW";
      countEl.textContent = pending ? "1" : "0";
      bar.classList.toggle("hidden", !pending);
      bar.classList.toggle("opacity-40", !pending);
      bar.classList.toggle("pointer-events-none", !pending);
      bar.classList.toggle("border-red-700/50", false);
      bar.classList.toggle("bg-red-950/40", false);
      bar.classList.toggle("border-amber-700/50", true);
      bar.classList.toggle("bg-amber-950/40", true);
      if (labelEl) labelEl.textContent = "На проверке:";
      approveBtn.textContent = "Подтвердить (Space)";
      rejectBtn.textContent = "Сбросить (U)";
      rejectBtn.classList.toggle("hidden", !pending);
      return;
    }
    const annotations = store.get("annotations") || [];
    const image = store.get("currentImage");
    const count = pendingCount(annotations);
    const recheck = image?.status === "REQUIRES_RECHECK";
    countEl.textContent = String(count);
    bar.classList.toggle("hidden", count === 0 && !recheck);
    bar.classList.toggle("opacity-40", count === 0 && !recheck);
    bar.classList.toggle("pointer-events-none", count === 0 && !recheck);
    bar.classList.toggle("border-red-700/50", recheck);
    bar.classList.toggle("bg-red-950/40", recheck);
    bar.classList.toggle("border-amber-700/50", !recheck);
    bar.classList.toggle("bg-amber-950/40", !recheck);
    if (labelEl) {
      labelEl.textContent = recheck
        ? "Аудит: сплошные — разметка, пунктир — модель"
        : "На проверке:";
    }
    approveBtn.textContent = recheck
      ? count
        ? "Принять модель (Space)"
        : "Разметка верна (Space)"
      : "Подтвердить (Space)";
    rejectBtn.textContent = recheck ? "Оставить разметку (R)" : "Удалить аннотации (R)";
    rejectBtn.classList.toggle("hidden", recheck && count === 0);
  }

  approveBtn.addEventListener("click", () => onApproveAll?.());
  rejectBtn.addEventListener("click", () => onRejectAll?.());
  deleteImageBtn.addEventListener("click", () => onDeleteImage?.());

  store.addEventListener("change:annotations", sync);
  store.addEventListener("change:currentImage", sync);
  sync();
}
