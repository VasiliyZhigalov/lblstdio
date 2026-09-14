import { store } from "../store.js";

function pendingCount(annotations) {
  return (annotations || []).filter((box) => box.verification_status === "PENDING_REVIEW")
    .length;
}

export function initReviewBar({ onApproveAll, onRejectAll }) {
  const bar = document.getElementById("review-bar");
  const countEl = document.getElementById("pending-count");
  const approveBtn = document.getElementById("btn-approve-all");
  const rejectBtn = document.getElementById("btn-reject-all");
  if (!bar || !countEl || !approveBtn || !rejectBtn) return;

  function sync() {
    const count = pendingCount(store.get("annotations"));
    countEl.textContent = String(count);
    bar.classList.toggle("hidden", count === 0);
    bar.classList.toggle("opacity-40", count === 0);
    bar.classList.toggle("pointer-events-none", count === 0);
  }

  approveBtn.addEventListener("click", () => onApproveAll?.());
  rejectBtn.addEventListener("click", () => onRejectAll?.());

  store.addEventListener("change:annotations", sync);
  store.addEventListener("change:currentImage", sync);
  sync();
}
