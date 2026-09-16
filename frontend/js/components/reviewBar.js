import { store } from "../store.js";

function pendingCount(annotations) {
  return (annotations || []).filter((box) => box.verification_status === "PENDING_REVIEW")
    .length;
}

export function initReviewBar({ onApproveAll, onRejectAll, onDeleteImage }) {
  const bar = document.getElementById("review-bar");
  const countEl = document.getElementById("pending-count");
  const approveBtn = document.getElementById("btn-approve-all");
  const rejectBtn = document.getElementById("btn-reject-all");
  const deleteImageBtn = document.getElementById("btn-delete-image");
  if (!bar || !countEl || !approveBtn || !rejectBtn || !deleteImageBtn) return;

  function sync() {
    const count = pendingCount(store.get("annotations"));
    countEl.textContent = String(count);
    bar.classList.toggle("hidden", count === 0);
    bar.classList.toggle("opacity-40", count === 0);
    bar.classList.toggle("pointer-events-none", count === 0);
  }

  approveBtn.addEventListener("click", () => onApproveAll?.());
  rejectBtn.addEventListener("click", () => onRejectAll?.());
  deleteImageBtn.addEventListener("click", () => onDeleteImage?.());

  store.addEventListener("change:annotations", sync);
  store.addEventListener("change:currentImage", sync);
  sync();
}
