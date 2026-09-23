import { store } from "../store.js";
import { api } from "../api.js";
import { escapeHtml, formatRelative, refreshIcons, showModal } from "../utils/dom.js";

function taskTypeLabel(taskType) {
  return taskType === "CLASSIFICATION" ? "Классификация" : "Детекция";
}

async function enrichProject(project) {
  try {
    const [images, classes] = await Promise.all([
      api.listImages(project.id),
      api.listClasses(project.id),
    ]);
    return {
      ...project,
      imageCount: images.length,
      verifiedCount: images.filter(
        (item) => item.status === "VERIFIED" || item.status === "AUTO_VERIFIED"
      ).length,
      classCount: classes.length,
    };
  } catch {
    return { ...project, imageCount: 0, verifiedCount: 0, classCount: 0 };
  }
}

export async function loadProjectsHub() {
  const projects = await api.listProjects();
  const enriched = await Promise.all(projects.map(enrichProject));
  store.set("projects", enriched);
}

function filteredProjects() {
  const query = (store.get("projectQuery") || "").trim().toLowerCase();
  const projects = store.get("projects") || [];
  if (!query) return projects;
  return projects.filter((project) => {
    const hay = `${project.name} ${project.description || ""}`.toLowerCase();
    return hay.includes(query);
  });
}

function renderProjects() {
  const grid = document.getElementById("projects-grid");
  const empty = document.getElementById("projects-empty");
  const projects = filteredProjects();
  if (!projects.length) {
    grid.innerHTML = "";
    empty.classList.remove("hidden");
    empty.classList.add("flex");
    return;
  }
  empty.classList.add("hidden");
  empty.classList.remove("flex");
  grid.innerHTML = projects
    .map((project) => {
      const updated = formatRelative(project.updated_at || project.created_at);
      return `
        <article data-project-id="${project.id}"
          class="relative group rounded-xl border border-zinc-800 bg-zinc-900/70 hover:border-indigo-500/50 transition p-4 flex flex-col gap-3">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <div class="flex items-center gap-2 min-w-0">
                <h3 class="text-sm font-semibold truncate">${escapeHtml(project.name)}</h3>
                <span class="shrink-0 px-1.5 py-0.5 text-[10px] rounded border border-zinc-700 text-zinc-400">${escapeHtml(taskTypeLabel(project.task_type))}</span>
              </div>
              <p class="text-[11px] text-zinc-500 mt-0.5">${
                project.created_at === project.updated_at ? "Создан" : "Обновлено"
              }: ${escapeHtml(updated)}</p>
            </div>
            <button type="button" data-project-menu="${project.id}"
              class="p-1 rounded hover:bg-zinc-800 text-zinc-500 hover:text-zinc-200" title="Меню">
              <i data-lucide="more-vertical" class="w-4 h-4"></i>
            </button>
          </div>
          <p class="text-xs text-zinc-400 line-clamp-2 min-h-[2rem]">${escapeHtml(project.description || "Без описания")}</p>
          <div class="text-[11px] text-zinc-400">
            ${project.imageCount ?? 0} кадров / ${project.classCount ?? 0} классов
            ${project.verifiedCount ? ` · ${project.verifiedCount} verified` : ""}
          </div>
          <button type="button" data-open-project="${project.id}"
            class="mt-auto w-full text-xs px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-indigo-600 text-zinc-200">
            Открыть проект →
          </button>
          <div data-menu-panel="${project.id}"
            class="hidden absolute right-3 top-10 z-10 w-40 rounded-md border border-zinc-700 bg-zinc-900 shadow-xl py-1">
            <button type="button" data-edit-project="${project.id}"
              class="w-full text-left px-3 py-1.5 text-xs text-zinc-200 hover:bg-zinc-800">
              Редактировать
            </button>
            <button type="button" data-delete-project="${project.id}"
              class="w-full text-left px-3 py-1.5 text-xs text-red-300 hover:bg-red-950/40">
              Удалить проект
            </button>
          </div>
        </article>`;
    })
    .join("");
  refreshIcons(grid);
}

export function initProjectsHub({
  onOpenProject,
  onCreateProject,
  onUpdateProject,
  onDeleteProject,
}) {
  const modal = document.getElementById("project-modal");
  const modalTitle = document.getElementById("project-modal-title");
  const form = document.getElementById("project-form");
  const nameInput = document.getElementById("project-name");
  const descInput = document.getElementById("project-description");
  const submitBtn = document.getElementById("project-submit-btn");
  const deleteModal = document.getElementById("delete-project-modal");
  const deleteText = document.getElementById("delete-project-text");
  let pendingDeleteId = null;
  let editingProjectId = null;

  const closeMenus = () => {
    document.querySelectorAll("[data-menu-panel]").forEach((el) => el.classList.add("hidden"));
  };

  const openCreateModal = () => {
    editingProjectId = null;
    modalTitle.textContent = "Новый проект";
    submitBtn.textContent = "Создать";
    nameInput.value = "";
    descInput.value = "";
    const fieldset = document.getElementById("project-task-type-fieldset");
    fieldset?.classList.remove("hidden");
    const detection = document.querySelector('input[name="project-task-type"][value="DETECTION"]');
    if (detection) detection.checked = true;
    showModal(modal, true);
    nameInput.focus();
  };

  const openEditModal = (project) => {
    editingProjectId = project.id;
    modalTitle.textContent = "Редактировать проект";
    submitBtn.textContent = "Сохранить";
    nameInput.value = project.name || "";
    descInput.value = project.description || "";
    document.getElementById("project-task-type-fieldset")?.classList.add("hidden");
    showModal(modal, true);
    nameInput.focus();
    nameInput.select();
  };

  document.getElementById("btn-new-project").addEventListener("click", openCreateModal);
  document.getElementById("btn-cancel-project").addEventListener("click", () => {
    editingProjectId = null;
    showModal(modal, false);
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = nameInput.value.trim();
    if (!name) return;
    const description = descInput.value.trim() || null;
    if (submitBtn) submitBtn.disabled = true;
    try {
      if (editingProjectId) {
        await onUpdateProject(editingProjectId, name, description);
      } else {
        const taskType =
          document.querySelector('input[name="project-task-type"]:checked')?.value ||
          "DETECTION";
        await onCreateProject(name, description, taskType);
      }
      editingProjectId = null;
      showModal(modal, false);
    } catch {
      /* caller shows toast; keep modal open */
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  });

  document.getElementById("project-search").addEventListener("input", (event) => {
    store.set("projectQuery", event.target.value);
  });

  document.getElementById("projects-grid").addEventListener("click", (event) => {
    const menuBtn = event.target.closest("[data-project-menu]");
    if (menuBtn) {
      event.stopPropagation();
      const id = menuBtn.dataset.projectMenu;
      const panel = document.querySelector(`[data-menu-panel="${id}"]`);
      const wasHidden = panel.classList.contains("hidden");
      closeMenus();
      if (wasHidden) panel.classList.remove("hidden");
      return;
    }
    const edit = event.target.closest("[data-edit-project]");
    if (edit) {
      const project = (store.get("projects") || []).find(
        (item) => item.id === edit.dataset.editProject
      );
      closeMenus();
      if (project) openEditModal(project);
      return;
    }
    const del = event.target.closest("[data-delete-project]");
    if (del) {
      pendingDeleteId = del.dataset.deleteProject;
      const project = (store.get("projects") || []).find((item) => item.id === pendingDeleteId);
      deleteText.textContent = `Удалить проект «${project?.name || ""}» и все его кадры? Это действие нельзя отменить.`;
      closeMenus();
      showModal(deleteModal, true);
      return;
    }
    const open = event.target.closest("[data-open-project]");
    if (open) onOpenProject(open.dataset.openProject);
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest("[data-project-menu], [data-menu-panel]")) closeMenus();
  });

  document.getElementById("btn-cancel-delete-project").addEventListener("click", () => {
    pendingDeleteId = null;
    showModal(deleteModal, false);
  });
  document.getElementById("btn-confirm-delete-project").addEventListener("click", async () => {
    if (pendingDeleteId) await onDeleteProject(pendingDeleteId);
    pendingDeleteId = null;
    showModal(deleteModal, false);
  });

  store.addEventListener("change:projects", renderProjects);
  store.addEventListener("change:projectQuery", renderProjects);
  renderProjects();
}
