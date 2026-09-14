function normalize(hash) {
  const raw = (hash || "").replace(/^#/, "").trim();
  if (!raw || raw === "/") return "/projects";
  return raw.startsWith("/") ? raw : `/${raw}`;
}

export function parseHash() {
  const parts = normalize(window.location.hash).split("/").filter(Boolean);
  if (parts[0] !== "projects") return { name: "projects" };
  if (parts[1]) return { name: "studio", projectId: decodeURIComponent(parts[1]) };
  return { name: "projects" };
}

export function navigate(path) {
  const next = path.startsWith("#") ? path : `#${path}`;
  if (window.location.hash === next) {
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    return;
  }
  window.location.hash = next;
}

export function ensureHash() {
  const hash = window.location.hash;
  if (!hash || hash === "#") {
    history.replaceState(
      null,
      "",
      `${window.location.pathname}${window.location.search}#/projects`
    );
  }
}
