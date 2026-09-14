export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function showModal(el, visible) {
  if (!el) return;
  el.classList.toggle("hidden", !visible);
  el.classList.toggle("flex", visible);
}

export function refreshIcons(root) {
  window.lucide?.createIcons({
    root: root || document.body,
  });
}

export function formatRelative(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const sec = (Date.now() - date.getTime()) / 1000;
  if (sec < 45) return "только что";
  if (sec < 3600) return `${Math.max(1, Math.floor(sec / 60))} мин. назад`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} ч. назад`;
  if (sec < 172800) return "вчера";
  return date.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

export function splitBadgeClass(split) {
  const colors = {
    train: "bg-blue-950 text-blue-400 border-blue-800/50",
    valid: "bg-amber-950 text-amber-400 border-amber-800/50",
    test: "bg-fuchsia-950 text-fuchsia-300 border-fuchsia-800/50",
  };
  return colors[split] || "bg-zinc-800 text-zinc-300 border-zinc-700";
}
