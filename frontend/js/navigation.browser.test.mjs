/**
 * Browser/DOM tests for atomic project and image navigation.
 * Run from frontend/: npm run test:dom
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test, { afterEach, before } from "node:test";
import { fileURLToPath } from "node:url";
import { Window } from "happy-dom";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const waits = [];
const imageWaits = [];
let store;

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function pathnameOf(url) {
  const raw = String(url);
  const parsed = raw.startsWith("http") ? new URL(raw) : new URL(raw, "http://127.0.0.1:8000");
  return decodeURIComponent(parsed.pathname);
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const db = {
  projects: new Map(),
};

function box(id, classId, status = "VERIFIED") {
  return {
    id,
    class_id: classId,
    x_center: 0.5,
    y_center: 0.5,
    width: 0.2,
    height: 0.2,
    source: status === "PENDING_REVIEW" ? "MODEL" : "MANUAL",
    verification_status: status,
    confidence: status === "PENDING_REVIEW" ? 0.4 : 1,
  };
}

function putProject({ id, name, images }) {
  const classId = `${id}-class`;
  db.projects.set(id, {
    project: {
      id,
      name,
      description: null,
      task_type: "DETECTION",
      created_at: "2026-09-23T00:00:00Z",
    },
    classes: [{ id: classId, name: "defect", color_hex: "#EF4444", index_id: 0 }],
    images: images.map((image) => ({
      id: image.id,
      file_name: image.file_name,
      status: image.status || (image.annotations?.length ? "VERIFIED" : "UNANNOTATED"),
      width: 200,
      height: 150,
      split: "train",
      is_background: false,
      label: null,
      project_id: id,
    })),
    annotations: Object.fromEntries(images.map((image) => [image.id, image.annotations || []])),
  });
}

function findImage(imageId) {
  for (const project of db.projects.values()) {
    const summary = project.images.find((item) => item.id === imageId);
    if (summary) {
      return {
        summary,
        annotations: project.annotations[imageId] || [],
        classId: project.classes[0].id,
      };
    }
  }
  return null;
}

function answer(pathname, method, options) {
  if (method === "GET" && pathname === "/api/v1/projects") {
    return [...db.projects.values()].map((item) => item.project);
  }

  let match = pathname.match(/^\/api\/v1\/projects\/([^/]+)$/);
  if (method === "GET" && match) {
    return db.projects.get(match[1])?.project ?? { detail: "missing project" };
  }
  match = pathname.match(/^\/api\/v1\/projects\/([^/]+)\/classes$/);
  if (method === "GET" && match) return db.projects.get(match[1])?.classes ?? [];
  match = pathname.match(/^\/api\/v1\/projects\/([^/]+)\/images$/);
  if (method === "GET" && match) return db.projects.get(match[1])?.images ?? [];
  match = pathname.match(/^\/api\/v1\/projects\/([^/]+)\/dataset-versions$/);
  if (method === "GET" && match) return [];
  match = pathname.match(/^\/api\/v1\/projects\/([^/]+)\/models$/);
  if (method === "GET" && match) return [];

  match = pathname.match(/^\/api\/v1\/images\/([^/]+)$/);
  if (method === "GET" && match) {
    const found = findImage(match[1]);
    if (!found) return { detail: "missing image" };
    return { ...found.summary, annotations: found.annotations };
  }

  match = pathname.match(/^\/api\/v1\/images\/([^/]+)\/annotations$/);
  if (method === "PUT" && match) {
    const payload = JSON.parse(options.body || "{}");
    return payload.boxes || [];
  }
  match = pathname.match(/^\/api\/v1\/images\/([^/]+)\/annotations\/([^/]+)$/);
  if (method === "DELETE" && match) return [];
  match = pathname.match(/^\/api\/v1\/images\/([^/]+)\/annotations\/([^/]+)\/verify$/);
  if (method === "POST" && match) {
    const found = findImage(match[1]);
    const current = (found?.annotations || []).find((item) => item.id === match[2]);
    return { ...(current || box(match[2], found?.classId || "class")), verification_status: "VERIFIED" };
  }

  if (pathname.endsWith("/file")) {
    return null;
  }
  return [];
}

async function fetchImpl(url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const pathname = pathnameOf(url);
  const slot = waits.find((item) => !item.taken && item.match(pathname, method));
  if (slot) {
    slot.taken = true;
    const body = await slot.gate.promise;
    slot.done = true;
    return jsonResponse(body);
  }
  if (pathname.endsWith("/file")) {
    const png = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
      "base64"
    );
    return new Response(png, { status: 200, headers: { "content-type": "image/png" } });
  }
  const body = answer(pathname, method, options);
  if (body && body.detail) return jsonResponse(body, 404);
  return jsonResponse(body);
}

class ControlledImage {
  constructor() {
    this.naturalWidth = 200;
    this.naturalHeight = 150;
    this.decoding = "async";
    this.onload = null;
    this.onerror = null;
    this._src = "";
  }

  set src(value) {
    this._src = String(value);
    const slot = imageWaits.find((item) => !item.taken && item.match(this._src));
    if (slot) {
      slot.taken = true;
      slot.img = this;
      return;
    }
    queueMicrotask(() => this.onload?.());
  }

  get src() {
    return this._src;
  }
}

function hold(match) {
  const gate = deferred();
  const slot = { match, gate, taken: false, done: false };
  waits.push(slot);
  return {
    get taken() {
      return slot.taken;
    },
    release(body) {
      slot.done = true;
      slot.gate.resolve(body);
    },
  };
}

function holdImage(match) {
  const slot = { match, taken: false, img: null, finished: false };
  imageWaits.push(slot);
  return {
    get started() {
      return Boolean(slot.img);
    },
    async waitStarted() {
      await waitFor(() => slot.img, "bitmap request");
    },
    release() {
      if (!slot.img || slot.finished) return;
      slot.finished = true;
      slot.img.onload?.();
    },
    fail() {
      if (!slot.img || slot.finished) return;
      slot.finished = true;
      slot.img.onerror?.(new Event("error"));
    },
  };
}

function releaseLeftovers() {
  for (const slot of waits) {
    if (!slot.done) {
      slot.done = true;
      slot.gate.resolve([]);
    }
  }
  waits.length = 0;
  for (const slot of imageWaits) {
    if (slot.img && !slot.finished) {
      slot.finished = true;
      slot.img.onload?.();
    }
  }
  imageWaits.length = 0;
}

async function settle() {
  for (let i = 0; i < 20; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

async function waitFor(predicate, label) {
  const start = Date.now();
  while (Date.now() - start < 2000) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  const toast = document.getElementById("toast");
  throw new Error(
    `timed out waiting for ${label}; hash=${window.location.hash}; view=${store?.get("view")}; tab=${store?.get("projectTab")}; project=${store?.get("currentProject")?.id}; image=${store?.get("currentImage")?.id}; toast=${toast?.textContent || ""}`
  );
}

function go(path) {
  const next = path.startsWith("#") ? path : `#${path}`;
  if (window.location.hash === next) {
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    return;
  }
  window.location.hash = next;
}

function fakeContext() {
  return new Proxy(
    {},
    {
      get(target, prop) {
        if (prop === "measureText") return () => ({ width: 12 });
        if (prop in target) return target[prop];
        return () => {};
      },
      set(target, prop, value) {
        target[prop] = value;
        return true;
      },
    }
  );
}

function installDom() {
  const win = new Window({
    url: "http://127.0.0.1:8000/#/projects",
    settings: {
      disableJavaScriptEvaluation: true,
      disableJavaScriptFileLoading: true,
      disableCSSFileLoading: true,
      disableIframePageLoading: true,
    },
  });
  const html = fs
    .readFileSync(path.join(root, "index.html"), "utf8")
    .replace(/<script[\s\S]*?<\/script>/gi, "");
  win.document.write(html);
  win.confirm = () => true;
  win.alert = () => {};

  const globals = {
    window: win,
    document: win.document,
    HTMLElement: win.HTMLElement,
    Element: win.Element,
    Node: win.Node,
    EventTarget: win.EventTarget,
    Event: win.Event,
    CustomEvent: win.CustomEvent,
    MouseEvent: win.MouseEvent,
    KeyboardEvent: win.KeyboardEvent,
    HashChangeEvent: win.HashChangeEvent,
    ResizeObserver: win.ResizeObserver,
    requestAnimationFrame: win.requestAnimationFrame.bind(win),
    cancelAnimationFrame: win.cancelAnimationFrame.bind(win),
    getComputedStyle: win.getComputedStyle.bind(win),
    Image: ControlledImage,
    fetch: fetchImpl,
  };
  for (const [name, value] of Object.entries(globals)) {
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
  }

  const container = win.document.getElementById("canvas-container");
  Object.defineProperty(container, "clientWidth", { configurable: true, get: () => 800 });
  Object.defineProperty(container, "clientHeight", { configurable: true, get: () => 600 });
  for (const canvas of win.document.querySelectorAll("canvas")) {
    canvas.getContext = () => fakeContext();
    canvas.getBoundingClientRect = () => ({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 800,
      bottom: 600,
      width: 800,
      height: 600,
      toJSON() {
        return {};
      },
    });
  }
}

function drawOnCanvas() {
  const canvas = document.getElementById("annotation-canvas");
  canvas.dispatchEvent(
    new MouseEvent("mousedown", {
      bubbles: true,
      cancelable: true,
      clientX: 120,
      clientY: 120,
      button: 0,
    })
  );
  window.dispatchEvent(
    new MouseEvent("mousemove", { bubbles: true, clientX: 280, clientY: 260, button: 0 })
  );
  window.dispatchEvent(
    new MouseEvent("mouseup", { bubbles: true, clientX: 280, clientY: 260, button: 0 })
  );
}

async function openProjectImage(projectId, imageId) {
  go(`/projects/${projectId}/annotate?image=${imageId}`);
  await waitFor(() => store.get("currentImage")?.id === imageId, `image ${imageId}`);
  await settle();
}

before(async () => {
  installDom();
  let hashEvents = 0;
  window.addEventListener("hashchange", () => {
    hashEvents += 1;
  });
  window.location.hash = "#/hash-probe";
  await settle();
  window.location.hash = "#/projects";
  await settle();
  if (hashEvents === 0) {
    throw new Error("happy-dom did not emit hashchange");
  }
  ({ store } = await import("./store.js"));
  await import("./app.js");
  await waitFor(() => document.getElementById("view-projects") && !document.getElementById("view-projects").classList.contains("hidden"), "projects hub");
});

afterEach(async () => {
  releaseLeftovers();
  await settle();
});

test("stale project responses keep the latest project", async () => {
  putProject({
    id: "proj-a",
    name: "Project A",
    images: [{ id: "img-a", file_name: "a.png", annotations: [] }],
  });
  putProject({
    id: "proj-b",
    name: "Project B",
    images: [{ id: "img-b", file_name: "b.png", annotations: [] }],
  });

  const projectA = hold((pathname, method) => method === "GET" && pathname === "/api/v1/projects/proj-a");
  go("/projects/proj-a/data");
  await waitFor(() => projectA.taken, "project A request");

  const projectB = hold((pathname, method) => method === "GET" && pathname === "/api/v1/projects/proj-b");
  go("/projects/proj-b/data");
  await waitFor(() => projectB.taken, "project B request");

  projectB.release(db.projects.get("proj-b").project);
  await waitFor(() => store.get("currentProject")?.id === "proj-b", "project B commit");

  projectA.release(db.projects.get("proj-a").project);
  await settle();

  assert.equal(store.get("currentProject")?.id, "proj-b");
  assert.deepEqual(
    (store.get("images") || []).map((item) => item.id),
    ["img-b"]
  );
});

test("stale image responses keep the latest image", async () => {
  const classId = "proj-images-class";
  putProject({
    id: "proj-images",
    name: "Images",
    images: [
      { id: "img-1", file_name: "1.png", annotations: [box("box-1", classId)], status: "VERIFIED" },
      { id: "img-2", file_name: "2.png", annotations: [box("box-2", classId)], status: "VERIFIED" },
      { id: "img-3", file_name: "3.png", annotations: [box("box-3", classId)], status: "VERIFIED" },
    ],
  });

  await openProjectImage("proj-images", "img-1");
  assert.deepEqual(
    store.get("annotations").map((item) => item.id),
    ["box-1"]
  );

  const image2 = hold((pathname, method) => method === "GET" && pathname === "/api/v1/images/img-2");
  const bitmap2 = holdImage((src) => src.includes("/images/img-2/file"));
  go("/projects/proj-images/annotate?image=img-2");
  await waitFor(() => image2.taken, "image 2 request");

  const image3 = hold((pathname, method) => method === "GET" && pathname === "/api/v1/images/img-3");
  const bitmap3 = holdImage((src) => src.includes("/images/img-3/file"));
  go("/projects/proj-images/annotate?image=img-3");
  await waitFor(() => image3.taken, "image 3 request");

  image3.release({ ...findImage("img-3").summary, annotations: [box("box-3", classId)] });
  await bitmap3.waitStarted();
  bitmap3.release();
  await waitFor(() => store.get("currentImage")?.id === "img-3", "image 3 commit");

  image2.release({ ...findImage("img-2").summary, annotations: [box("box-2", classId)] });
  await settle();
  if (bitmap2.started) {
    bitmap2.release();
    await settle();
  }

  assert.equal(store.get("currentImage")?.id, "img-3");
  assert.deepEqual(
    store.get("annotations").map((item) => item.id),
    ["box-3"]
  );
});

test("annotations stay non-interactive until the bitmap loads", async () => {
  const classId = "proj-bitmap-class";
  putProject({
    id: "proj-bitmap",
    name: "Bitmap",
    images: [
      { id: "bmp-a", file_name: "a.png", annotations: [box("box-a", classId)], status: "VERIFIED" },
      { id: "bmp-b", file_name: "b.png", annotations: [box("box-b", classId)], status: "VERIFIED" },
    ],
  });
  await openProjectImage("proj-bitmap", "bmp-a");

  const before = store.get("annotations").length;
  drawOnCanvas();
  assert.equal(store.get("annotations").length, before + 1, "loaded bitmap accepts a new box");
  document.getElementById("btn-save-annotations").click();
  await waitFor(() => store.get("hasUnsavedChanges") === false, "save drawn box");

  const imageB = hold((pathname, method) => method === "GET" && pathname === "/api/v1/images/bmp-b");
  const bitmapB = holdImage((src) => src.includes("/images/bmp-b/file"));
  go("/projects/proj-bitmap/annotate?image=bmp-b");
  await waitFor(() => imageB.taken, "image B request");
  imageB.release({ ...findImage("bmp-b").summary, annotations: [box("box-b", classId)] });
  await bitmapB.waitStarted();

  assert.deepEqual(
    store.get("annotations").map((item) => item.id).filter((id) => id === "box-b"),
    [],
    "new annotations are not installed before the bitmap"
  );
  const pendingCount = store.get("annotations").length;
  drawOnCanvas();
  assert.equal(store.get("annotations").length, pendingCount, "old bitmap is not editable during load");

  bitmapB.release();
  await waitFor(() => store.get("currentImage")?.id === "bmp-b", "image B commit");
  assert.deepEqual(
    store.get("annotations").map((item) => item.id),
    ["box-b"]
  );
});

test("failed image load leaves the previous bitmap uneditable", async () => {
  const classId = "proj-fail-class";
  putProject({
    id: "proj-fail",
    name: "Fail",
    images: [
      { id: "fail-a", file_name: "a.png", annotations: [], status: "UNANNOTATED" },
      { id: "fail-b", file_name: "b.png", annotations: [box("box-fail", classId)], status: "VERIFIED" },
    ],
  });
  await openProjectImage("proj-fail", "fail-a");
  drawOnCanvas();
  assert.equal(store.get("annotations").length, 1, "bitmap is editable after a successful load");
  document.getElementById("btn-save-annotations").click();
  await waitFor(() => store.get("hasUnsavedChanges") === false, "save before failed navigation");

  const imageB = hold((pathname, method) => method === "GET" && pathname === "/api/v1/images/fail-b");
  const bitmapB = holdImage((src) => src.includes("/images/fail-b/file"));
  go("/projects/proj-fail/annotate?image=fail-b");
  await waitFor(() => imageB.taken, "failing image request");
  imageB.release({ ...findImage("fail-b").summary, annotations: [box("box-fail", classId)] });
  await bitmapB.waitStarted();
  bitmapB.fail();
  await settle();

  const count = store.get("annotations").length;
  drawOnCanvas();
  assert.equal(store.get("annotations").length, count);
  assert.equal(
    store.get("annotations").some((item) => item.id === "box-fail"),
    false
  );
});

test("delete, verify, and save do not patch another image after navigation", async () => {
  const classId = "proj-mutate-class";
  putProject({
    id: "proj-mutate",
    name: "Mutate",
    images: [
      {
        id: "mut-a",
        file_name: "a.png",
        status: "REQUIRES_REVIEW",
        annotations: [box("pending-a", classId, "PENDING_REVIEW")],
      },
      {
        id: "mut-b",
        file_name: "b.png",
        status: "VERIFIED",
        annotations: [box("box-b", classId)],
      },
    ],
  });
  putProject({
    id: "proj-save-next",
    name: "Save next",
    images: [{ id: "save-b", file_name: "b.png", annotations: [box("save-box-b", `${classId}-2`)], status: "VERIFIED" }],
  });

  await openProjectImage("proj-mutate", "mut-a");
  store.set("selectedBoxId", "pending-a");
  const deletion = hold(
    (pathname, method) => method === "DELETE" && pathname === "/api/v1/images/mut-a/annotations/pending-a"
  );
  window.dispatchEvent(new KeyboardEvent("keydown", { code: "Delete", bubbles: true, cancelable: true }));
  await waitFor(() => deletion.taken, "delete request");

  await openProjectImage("proj-mutate", "mut-b");
  deletion.release([]);
  await settle();
  assert.equal(store.get("currentImage")?.id, "mut-b");
  assert.deepEqual(
    store.get("annotations").map((item) => item.id),
    ["box-b"]
  );

  await openProjectImage("proj-mutate", "mut-a");
  store.set("selectedBoxId", "pending-a");
  const verification = hold(
    (pathname, method) =>
      method === "POST" && pathname === "/api/v1/images/mut-a/annotations/pending-a/verify"
  );
  document.getElementById("btn-approve-box").click();
  await waitFor(() => verification.taken, "verify request");
  await openProjectImage("proj-mutate", "mut-b");
  drawOnCanvas();
  assert.equal(store.get("hasUnsavedChanges"), true);
  const drawnIds = store.get("annotations").map((item) => item.id);
  verification.release({ ...box("pending-a", classId), verification_status: "VERIFIED" });
  await settle();
  assert.equal(store.get("currentImage")?.id, "mut-b");
  assert.equal(store.get("hasUnsavedChanges"), true);
  assert.deepEqual(
    store.get("annotations").map((item) => item.id),
    drawnIds
  );

  document.getElementById("btn-save-annotations").click();
  await waitFor(() => store.get("hasUnsavedChanges") === false, "save image B before leaving");

  await openProjectImage("proj-mutate", "mut-a");
  const saving = hold((pathname, method) => method === "PUT" && pathname === "/api/v1/images/mut-a/annotations");
  document.getElementById("btn-save-annotations").click();
  await waitFor(() => saving.taken, "save request");
  await openProjectImage("proj-save-next", "save-b");
  saving.release([box("saved-from-a", classId)]);
  await settle();

  assert.equal(store.get("currentProject")?.id, "proj-save-next");
  assert.equal(store.get("currentImage")?.id, "save-b");
  assert.deepEqual(
    store.get("annotations").map((item) => item.id),
    ["save-box-b"]
  );
  assert.equal(
    (store.get("galleryAnnotations")?.["mut-a"] || []).some((item) => item.id === "saved-from-a"),
    false
  );
});
