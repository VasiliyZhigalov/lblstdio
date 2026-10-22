import assert from "node:assert/strict";
import test, { before, beforeEach, afterEach } from "node:test";
import { Window } from "happy-dom";

let win, store, api, initDataHub;
const calls = [];
const row = (id) => ({ id, file_name: `${id}.png`, width: 100, height: 80, status: "UNANNOTATED", annotations: [], label: null, tags: [], split: "train", created_at: "2026-10-22T00:00:00Z" });
const tick = () => new Promise(r => setTimeout(r, 20));
before(async () => {
  win = new Window({ url: "http://127.0.0.1:8000/#/projects/p/data" });
  for (const key of ["window", "document", "location", "history", "localStorage", "HTMLElement"]) globalThis[key] = key === "window" ? win : win[key];
  ({ store } = await import("../store.js"));
  ({ api } = await import("../api.js?v=project-data-20261022d"));
  ({ initDataHub } = await import("./projectData.js"));
});
beforeEach(() => {
  document.body.innerHTML = '<div id="project-data-root"></div>';
  history.replaceState(null, "", "#/projects/p/data");
  store.patch({ currentProject: { id: "p", name: "Project", task_type: "DETECTION" }, projectTab: "data", classes: [{ id: "c", name: "Car", index_id: 0, color_hex: "#123456" }] });
  calls.length = 0;
  api.projectDataStatistics = async () => ({ total: 101, statuses: [{ name: "UNANNOTATED", count: 101 }], classes: [], trash: 0, days: [], sources: [], splits: [] });
  api.projectCameras = async () => [];
  api.listDatasetVersions = async () => [];
  api.queryProjectData = async (id, filters) => { calls.push({ id, filters }); return { total: 101, limit: filters.limit, offset: filters.offset, items: Array.from({ length: 24 }, (_, i) => row(`image-${filters.offset+i}`)) }; };
  api.getImagesSummary = () => { throw new Error("Full project summary must not be loaded"); };
  api.getImage = () => { throw new Error("Per-image API must not be called for gallery"); };
});
afterEach(() => { document.body.innerHTML = ""; });
const click = (selector) => document.querySelector(selector).click();

test("gallery requests one page and loads only thumbnails", async () => {
  const hub = initDataHub({ onError: e => { throw new Error(e); } });
  await hub.refresh();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].filters.limit, 24);
  assert.equal(document.querySelectorAll(".pd-image-card").length, 24);
  assert.ok([...document.querySelectorAll(".pd-thumb img")].every(i => i.src.includes("/thumbnail")));
  click('[data-action="next-page"]'); await tick();
  assert.equal(calls.at(-1).filters.offset, 24);
});

test("bulk selection applies all matching filters and restores selection state", async () => {
  let action;
  api.projectDataAction = async (id, payload) => { action = payload; return { updated: 101 }; };
  const hub = initDataHub({}); await hub.refresh();
  click('[data-status="UNANNOTATED"]'); click('[data-class-filter="c"]');
  click('[data-action="apply-filters"]'); await tick();
  assert.equal(calls.at(-1).filters.status, "UNANNOTATED");
  assert.equal(calls.at(-1).filters.class_id, "c");
  click('[data-action="select-matching"]'); await tick(); click('[data-action="bulk-review"]'); await tick();
  assert.equal(action.all_matching, true);
  assert.equal(action.filters.class_id, "c");
  assert.equal(action.action, "review");
  assert.ok(document.querySelector(".pd-selection").textContent.includes("Выбрано: 0"));
});

test("stale gallery results cannot replace a different project", async () => {
  let resolve;
  api.queryProjectData = (id, f) => id === "p" ? new Promise(r => { resolve = r; }) : Promise.resolve({ items: [row("new-project")], total: 1, limit: 24, offset: 0 });
  const hub = initDataHub({});
  const pending = hub.refresh(); await tick();
  store.set("currentProject", { id: "q", name: "Next" }); await hub.refresh();
  resolve({ items: [row("stale")], total: 1, limit: 24, offset: 0 }); await pending;
  assert.ok(document.querySelector(".pd-image-card").textContent.includes("new-project"));
  assert.ok(!document.querySelector("#pd-content").textContent.includes("stale.png"));
});

test("quick viewer loads original on demand and opens annotation", async () => {
  let opened;
  const hub = initDataHub({ onOpenImage: id => { opened = id; } }); await hub.refresh();
  click('[data-open="0"]');
  assert.ok(document.querySelector(".pd-original img").src.endsWith("/images/image-0/file"));
  click('[data-action="viewer-next"]'); await tick();
  assert.ok(document.querySelector(".pd-original img").src.endsWith("/images/image-1/file"));
  click('[data-action="viewer-annotate"]');
  assert.equal(opened, "image-1");
  assert.equal(document.querySelector(".pd-modal"), null);
});

test("model class matching is reviewed before starting import", async () => {
  let started;
  api.listClasses = async () => store.get("classes");
  api.previewDataImport = async () => ({ id: "job", name: "weights.pt", kind: "model", summary: { format: "YOLO", names: ["Car", "Person"], images: 0 } });
  api.dataImportAction = async (_id, _job, action, body) => { started = { action, body }; return {}; };
  api.listDataImports = async () => [];
  const hub = initDataHub({}); await hub.refresh();
  await hub.previewModel({ name: "weights.pt" });
  assert.equal(document.querySelector('[data-import-map="0"]').value, "c");
  assert.equal(document.querySelector('[data-import-map="1"]').value, "new");
  assert.equal(started, undefined);
  click('[data-action="confirm-import"]');
  assert.equal(started, undefined);
  click('[data-action="start-import"]'); await tick();
  assert.deepEqual(started.body.mapping, { 0: "c", 1: "new" });
});
