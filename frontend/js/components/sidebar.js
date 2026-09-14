import { store } from "../store.js";
import { nextClassColor } from "../utils/math.js";
import { api } from "../api.js";
import { escapeHtml, refreshIcons } from "../utils/dom.js";

export function initSidebar({ onError, onDeleteBox }) {
  const classesList = document.getElementById("classes-list");
  const annotationsList = document.getElementById("annotations-list");
  const addBtn = document.getElementById("btn-add-class");
  const form = document.getElementById("add-class-form");
  const input = document.getElementById("add-class-input");

  function renderClasses() {
    const classes = [...(store.get("classes") || [])].sort((a, b) => a.index_id - b.index_id);
    const active = store.get("activeClassId");
    if (!classes.length) {
      classesList.innerHTML = `<p class="text-[11px] text-zinc-500">Добавьте класс, чтобы начать разметку.</p>`;
      return;
    }
    classesList.innerHTML = classes
      .map((cls, index) => {
        const hotkey = index < 9 ? index + 1 : "";
        const selected = cls.id === active;
        return `
          <button type="button" data-class-id="${cls.id}"
            class="w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-left text-sm ${
              selected ? "bg-zinc-800 text-white" : "hover:bg-zinc-800/60 text-zinc-300"
            }">
            <span class="font-mono text-[10px] text-zinc-500 w-4">${hotkey}</span>
            <span class="w-2.5 h-2.5 rounded-full shrink-0" style="background:${cls.color_hex}"></span>
            <span class="truncate">${escapeHtml(cls.name)}</span>
          </button>`;
      })
      .join("");
  }

  let annotationsSignature = "";

  function renderAnnotations() {
    const annotations = store.get("annotations") || [];
    const classes = store.get("classes") || [];
    const selectedId = store.get("selectedBoxId");
    const hoveredId = store.get("hoveredBoxId");
    const signature = `${annotations.map((box) => `${box.id}:${box.class_id}`).join("|")}|${selectedId}|${hoveredId}`;
    if (signature === annotationsSignature) return;
    annotationsSignature = signature;
    if (!annotations.length) {
      annotationsList.innerHTML = `<p class="text-[11px] text-zinc-500">На кадре пока нет рамок.</p>`;
      return;
    }
    annotationsList.innerHTML = annotations
      .map((box, index) => {
        const cls = classes.find((item) => item.id === box.class_id);
        const name = cls?.name || "Unknown";
        const color = cls?.color_hex || "#6366F1";
        const selected = box.id === selectedId || box.id === hoveredId;
        return `
          <div data-box-id="${box.id}"
            class="box-row group flex items-center gap-2 px-2 py-1.5 rounded-md text-xs cursor-pointer ${
              selected ? "selected" : "hover:bg-zinc-800/50"
            }">
            <span class="w-2 h-2 rounded-full shrink-0" style="background:${color}"></span>
            <span class="truncate flex-1">${index + 1}. ${escapeHtml(name)}</span>
            <button type="button" data-delete-box="${box.id}"
              class="opacity-0 group-hover:opacity-100 text-zinc-500 hover:text-red-400" title="Удалить">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            </button>
          </div>`;
      })
      .join("");
    refreshIcons();
  }

  classesList.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-class-id]");
    if (!btn) return;
    const classId = btn.dataset.classId;
    const selectedId = store.get("selectedBoxId");
    if (selectedId) {
      const annotations = store.get("annotations").map((box) =>
        box.id === selectedId ? { ...box, class_id: classId } : box
      );
      store.patch({
        annotations,
        activeClassId: classId,
        hasUnsavedChanges: true,
        saveStatus: "unsaved",
      });
    } else {
      store.set("activeClassId", classId);
    }
  });

  annotationsList.addEventListener("mouseover", (event) => {
    const row = event.target.closest("[data-box-id]");
    if (row) store.set("hoveredBoxId", row.dataset.boxId);
  });
  annotationsList.addEventListener("mouseleave", () => store.set("hoveredBoxId", null));
  annotationsList.addEventListener("click", (event) => {
    const del = event.target.closest("[data-delete-box]");
    if (del) {
      const id = del.dataset.deleteBox;
      if (onDeleteBox) onDeleteBox(id);
      else {
        store.patch({
          annotations: store.get("annotations").filter((box) => box.id !== id),
          selectedBoxId: store.get("selectedBoxId") === id ? null : store.get("selectedBoxId"),
          hasUnsavedChanges: true,
          saveStatus: "unsaved",
        });
      }
      return;
    }
    const row = event.target.closest("[data-box-id]");
    if (row) store.set("selectedBoxId", row.dataset.boxId);
  });

  addBtn.addEventListener("click", () => {
    form.classList.toggle("hidden");
    form.classList.toggle("flex");
    if (!form.classList.contains("hidden")) {
      input.focus();
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = input.value.trim();
    const project = store.get("currentProject");
    if (!name || !project) return;
    try {
      const created = await api.createClass(project.id, name, nextClassColor(store.get("classes").length));
      const classes = [...store.get("classes"), created];
      store.patch({
        classes,
        activeClassId: created.id,
      });
      input.value = "";
      form.classList.add("hidden");
      form.classList.remove("flex");
    } catch (err) {
      onError(err.message);
    }
  });

  store.addEventListener("change:classes", renderClasses);
  store.addEventListener("change:activeClassId", renderClasses);
  store.addEventListener("change:annotations", renderAnnotations);
  store.addEventListener("change:selectedBoxId", renderAnnotations);
  store.addEventListener("change:hoveredBoxId", renderAnnotations);

  renderClasses();
  renderAnnotations();
}

export function selectClassByHotkey(digit) {
  const classes = [...(store.get("classes") || [])].sort((a, b) => a.index_id - b.index_id);
  const cls = classes[digit - 1];
  if (!cls) return;
  const selectedId = store.get("selectedBoxId");
  if (selectedId) {
    store.patch({
      annotations: store.get("annotations").map((box) =>
        box.id === selectedId ? { ...box, class_id: cls.id } : box
      ),
      activeClassId: cls.id,
      hasUnsavedChanges: true,
      saveStatus: "unsaved",
    });
  } else {
    store.set("activeClassId", cls.id);
  }
}

export function deleteSelectedBox() {
  const id = store.get("selectedBoxId");
  if (!id) return;
  store.patch({
    annotations: store.get("annotations").filter((box) => box.id !== id),
    selectedBoxId: null,
    hasUnsavedChanges: true,
    saveStatus: "unsaved",
  });
}
