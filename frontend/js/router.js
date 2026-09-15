function normalize(hash) {
  const raw = (hash || "").replace(/^#/, "").trim();
  if (!raw || raw === "/") return "/projects";
  return raw.startsWith("/") ? raw : `/${raw}`;
}

export function parseHash() {
  const hash = normalize(window.location.hash);
  const [pathPart, queryPart] = hash.split("?");
  const parts = pathPart.split("/").filter(Boolean);
  const query = new URLSearchParams(queryPart || "");

  if (parts[0] !== "projects") return { name: "projects" };
  if (!parts[1]) return { name: "projects" };

  const projectId = decodeURIComponent(parts[1]);
  const subTab = parts[2] || "data";

  if (subTab === "annotate") {
    return {
      name: "studio",
      projectId,
      tab: "annotate",
      imageId: query.get("image"),
    };
  }
  if (subTab === "models") {
    return { name: "models", projectId, tab: "models" };
  }
  return { name: "data", projectId, tab: "data" };
}

export function projectPath(projectId, tab = "data", imageId = null) {
  const base = `/projects/${encodeURIComponent(projectId)}/${tab}`;
  if (tab === "annotate" && imageId) {
    return `${base}?image=${encodeURIComponent(imageId)}`;
  }
  return base;
}

export function navigate(path) {
  const next = path.startsWith("#") ? path : `#${path}`;
  if (window.location.hash === next) {
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    return;
  }
  window.location.hash = next;
}

export function replaceHash(path) {
  const next = path.startsWith("#") ? path : `#${path}`;
  history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search}${next}`
  );
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
