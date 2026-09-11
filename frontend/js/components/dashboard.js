import { store } from "../store.js";
import { api } from "../api.js";

const SPLITS = [
  { id: "all", label: "All" },
  { id: "train", label: "Train" },
  { id: "valid", label: "Valid" },
  { id: "test", label: "Test" },
];

const STATUSES = [
  { id: "all", label: "All" },
  { id: "annotated", label: "Annotated" },
  { id: "unannotated", label: "Unannotated" },
];

function chipClass(active) {
  return active
    ? "px-2.5 py-1 text-xs rounded-md bg-indigo-600 text-white"
    : "px-2.5 py-1 text-xs rounded-md bg-zinc-800 text-zinc-300 hover:bg-zinc-700";
}

function splitBadge(split) {
  const colors = {
    train: "bg-blue-950 text-blue-400 border-blue-800/50",
    valid: "bg-amber-950 text-amber-400 border-amber-800/50",
    test: "bg-fuchsia-950 text-fuchsia-300 border-fuchsia-800/50",
  };
  return colors[split] || "bg-zinc-800 text-zinc-300 border-zinc-700";
}

function isAnnotated(image) {
  return image.status && image.status !== "UNANNOTATED";
}

function filteredImages() {
  const split = store.get("splitFilter");
  const status = store.get("statusFilter");
  return (store.get("images") || []).filter((image) => {
    if (split !== "all" && image.split !== split) return false;
    if (status === "annotated" && !isAnnotated(image)) return false;
    if (status === "unannotated" && isAnnotated(image)) return false;
    return true;
  });
}

function renderFilters() {
  const splitRoot = document.getElementById("split-filters");
  const statusRoot = document.getElementById("status-filters");
  const currentSplit = store.get("splitFilter");
  const currentStatus = store.get("statusFilter");
  splitRoot.querySelectorAll("button").forEach((btn) => btn.remove());
  statusRoot.querySelectorAll("button").forEach((btn) => btn.remove());
  SPLITS.forEach((item) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.split = item.id;
    btn.className = chipClass(currentSplit === item.id);
    btn.textContent = item.label;
    splitRoot.appendChild(btn);
  });
  STATUSES.forEach((item) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.status = item.id;
    btn.className = chipClass(currentStatus === item.id);
    btn.textContent = item.label;
    statusRoot.appendChild(btn);
  });
}

function renderProjects() {
  const select = document.getElementById("project-select");
  const projects = store.get("projects") || [];
  const current = store.get("currentProject");
  select.innerHTML = "";
  if (!projects.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Нет проектов";
    select.appendChild(option);
    return;
  }
  for (const project of projects) {
    const option = document.createElement("option");
    option.value = project.id;
    option.textContent = project.name;
    select.appendChild(option);
  }
  if (current) select.value = current.id;
}

function renderGallery() {
  const grid = document.getElementById("gallery-grid");
  const empty = document.getElementById("gallery-empty");
  const count = document.getElementById("gallery-count");
  const images = filteredImages();
  count.textContent = `${images.length} / ${store.get("images").length} кадров`;
  if (!images.length) {
    grid.innerHTML = "";
    empty.classList.remove("hidden");
    empty.classList.add("flex");
    return;
  }
  empty.classList.add("hidden");
  empty.classList.remove("flex");
  grid.innerHTML = images
    .map((image) => {
      const annotated = isAnnotated(image);
      return `
        <button type="button" data-image-id="${image.id}"
          class="group text-left rounded-lg overflow-hidden border border-zinc-800 bg-zinc-900/60 hover:border-indigo-500/60 transition">
          <div class="aspect-video bg-zinc-950 overflow-hidden">
            <img src="${api.imageFileUrl(image.id)}" alt="${image.file_name}"
              class="w-full h-full object-cover group-hover:scale-[1.03] transition" loading="lazy" />
          </div>
          <div class="p-2.5 space-y-1.5">
            <div class="text-[11px] font-mono truncate text-zinc-300">${image.file_name}</div>
            <div class="flex items-center justify-between">
              <span class="px-1.5 py-0.5 text-[10px] uppercase rounded border ${splitBadge(image.split)}">${image.split}</span>
              <span class="text-[10px] ${annotated ? "text-emerald-400" : "text-zinc-500"}">${
                annotated ? "Annotated" : "Unannotated"
              }</span>
            </div>
          </div>
        </button>`;
    })
    .join("");
}

export function initDashboard({ onSelectProject, onOpenImage, onCreateProject }) {
  renderFilters();
  renderProjects();
  renderGallery();

  document.getElementById("split-filters").addEventListener("click", (event) => {
    const btn = event.target.closest("[data-split]");
    if (btn) store.set("splitFilter", btn.dataset.split);
  });
  document.getElementById("status-filters").addEventListener("click", (event) => {
    const btn = event.target.closest("[data-status]");
    if (btn) store.set("statusFilter", btn.dataset.status);
  });
  document.getElementById("project-select").addEventListener("change", (event) => {
    if (event.target.value) onSelectProject(event.target.value);
  });
  document.getElementById("gallery-grid").addEventListener("click", (event) => {
    const card = event.target.closest("[data-image-id]");
    if (card) onOpenImage(card.dataset.imageId);
  });

  const modal = document.getElementById("project-modal");
  const form = document.getElementById("project-form");
  const nameInput = document.getElementById("project-name");
  const show = (visible) => {
    modal.classList.toggle("hidden", !visible);
    modal.classList.toggle("flex", visible);
  };
  document.getElementById("btn-new-project").addEventListener("click", () => {
    nameInput.value = "";
    show(true);
    nameInput.focus();
  });
  document.getElementById("btn-cancel-project").addEventListener("click", () => show(false));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = nameInput.value.trim();
    if (!name) return;
    await onCreateProject(name);
    show(false);
  });

  store.addEventListener("change:projects", renderProjects);
  store.addEventListener("change:currentProject", renderProjects);
  store.addEventListener("change:images", renderGallery);
  store.addEventListener("change:splitFilter", () => {
    renderFilters();
    renderGallery();
  });
  store.addEventListener("change:statusFilter", () => {
    renderFilters();
    renderGallery();
  });
}
