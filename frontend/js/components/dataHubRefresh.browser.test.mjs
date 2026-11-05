/**
 * Run from frontend/: node --test --test-concurrency=1 js/components/dataHubRefresh.browser.test.mjs
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "path";
import test, { before } from "node:test";
import { fileURLToPath } from "node:url";
import { Window } from "happy-dom";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const requests = [];
const held = [];

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function pathnameOf(url) {
  const raw = String(url);
  const parsed = raw.startsWith("http") ? new URL(raw) : new URL(raw, "http://127.0.0.1:8000");
  return parsed.pathname;
}

const box = {
  id: "box-1",
  class_id: "cls-1",
  x_center: 0.5,
  y_center: 0.5,
  width: 0.2,
  height: 0.2,
  source: "MANUAL",
  verification_status: "VERIFIED",
  confidence: 1,
};

function installDom() {
  const win = new Window({
    url: "http://127.0.0.1:8000/",
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
  const fetchImpl = (url, options = {}) => {
    const method = String(options.method || "GET").toUpperCase();
    const pathname = pathnameOf(url);
    requests.push({ method, pathname });
    if (pathname.endsWith("/images/summary")) {
      const projectId = pathname.split("/")[4];
      return new Promise((resolve) => {
        held.push({
          projectId,
          release(body) {
            resolve(
              jsonResponse(
                body || {
                  class_counts: { "cls-1": 1 },
                  images: [
                    {
                      image_id: "img-1",
                      box_count: 1,
                      class_ids: ["cls-1"],
                      annotations: [box],
                    },
                  ],
                }
              )
            );
          },
        });
      });
    }
    if (pathname.startsWith("/api/v1/images/") && !pathname.endsWith("/file")) {
      return jsonResponse({
        id: pathname.split("/").pop(),
        annotations: [box],
        status: "VERIFIED",
        file_name: "a.png",
        width: 10,
        height: 10,
      });
    }
    return jsonResponse([]);
  };
  const globals = {
    window: win,
    document: win.document,
    HTMLElement: win.HTMLElement,
    Event: win.Event,
    MouseEvent: win.MouseEvent,
    requestAnimationFrame: win.requestAnimationFrame.bind(win),
    fetch: fetchImpl,
  };
  for (const [name, value] of Object.entries(globals)) {
    Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
  }
}

async function settle() {
  for (let i = 0; i < 20; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

let store;
let hub;

before(async () => {
  installDom();
  ({ store } = await import("../store.js"));
  const { initDataHub } = await import("./dataHub.js");
  hub = initDataHub({
    onOpenImage() {},
    onStartAnnotate() {},
  });
});

function seedProject(id, images) {
  store.patch({
    currentProject: { id, task_type: "DETECTION" },
    projectTab: "data",
    images,
    classes: [{ id: "cls-1", name: "defect", color_hex: "#EF4444", index_id: 0 }],
    classCounts: {},
    imageClassIds: {},
    galleryAnnotations: {},
    boxCounts: {},
  });
}

test("data hub refresh uses one summary request instead of per-image detail", async () => {
  seedProject("proj-sum", [
    {
      id: "img-1",
      status: "VERIFIED",
      file_name: "a.png",
      width: 10,
      height: 10,
      is_background: false,
    },
    {
      id: "img-2",
      status: "VERIFIED",
      file_name: "b.png",
      width: 10,
      height: 10,
      is_background: false,
    },
    {
      id: "img-3",
      status: "UNANNOTATED",
      file_name: "c.png",
      width: 10,
      height: 10,
      is_background: false,
    },
  ]);
  requests.length = 0;
  held.length = 0;
  const pending = hub.refresh();
  await settle();
  const summaryGets = requests.filter((item) => item.pathname.endsWith("/images/summary"));
  const detailGets = requests.filter(
    (item) =>
      item.pathname.startsWith("/api/v1/images/") &&
      !item.pathname.endsWith("/file") &&
      !item.pathname.endsWith("/summary")
  );
  assert.equal(summaryGets.length, 1);
  assert.equal(detailGets.length, 0);
  held.splice(0).forEach((item) => item.release());
  await pending;
});

test("stale data hub refresh is discarded after project change", async () => {
  seedProject("proj-old", [
    {
      id: "img-old",
      status: "VERIFIED",
      file_name: "old.png",
      width: 10,
      height: 10,
      is_background: false,
    },
  ]);
  held.length = 0;
  const stale = hub.refresh();
  await settle();
  assert.ok(held.length >= 1, "first refresh should start");
  const first = held.shift();

  seedProject("proj-new", [
    {
      id: "img-new",
      status: "VERIFIED",
      file_name: "new.png",
      width: 10,
      height: 10,
      is_background: false,
    },
  ]);
  const fresh = hub.refresh();
  await settle();
  const second = held.shift();
  second?.release({
    class_counts: { "cls-new": 3 },
    images: [
      {
        image_id: "img-new",
        box_count: 3,
        class_ids: ["cls-new"],
        annotations: [],
      },
    ],
  });
  await fresh;
  first.release({
    class_counts: { "cls-stale": 99 },
    images: [
      {
        image_id: "img-old",
        box_count: 99,
        class_ids: ["cls-stale"],
        annotations: [],
      },
    ],
  });
  await stale;
  await settle();
  assert.equal(store.get("classCounts")["cls-stale"], undefined);
  assert.equal(store.get("classCounts")["cls-new"], 3);
});

test("clear selected removes annotations and keeps the images", async () => {
  seedProject("proj-clear", [
    {
      id: "img-1",
      status: "VERIFIED",
      file_name: "a.png",
      width: 10,
      height: 10,
      is_background: false,
    },
  ]);
  store.patch({
    gallerySelectedIds: ["img-1"],
    boxCounts: { "img-1": 1 },
    galleryAnnotations: { "img-1": [box] },
    currentImage: { id: "img-1", status: "VERIFIED", is_background: false },
    annotations: [box],
    hasUnsavedChanges: true,
  });
  requests.length = 0;
  held.length = 0;
  const previousConfirm = window.confirm;
  window.confirm = () => true;
  try {
    document.getElementById("btn-gallery-clear-annotations").click();
    await settle();
    const puts = requests.filter(
      (item) => item.method === "PUT" && item.pathname.endsWith("/annotations")
    );
    assert.equal(puts.length, 1);
    assert.equal(store.get("images").find((item) => item.id === "img-1").status, "UNANNOTATED");
    assert.equal(store.get("annotations").length, 0);
    assert.equal(store.get("hasUnsavedChanges"), false);
    assert.equal(store.get("images").length, 1);
    held.splice(0).forEach((item) =>
      item.release({
        class_counts: {},
        images: [
          {
            image_id: "img-1",
            box_count: 0,
            class_ids: [],
            annotations: [],
          },
        ],
      })
    );
    await settle();
    assert.equal(store.get("boxCounts")["img-1"], 0);
    assert.deepEqual(store.get("galleryAnnotations")["img-1"], []);
  } finally {
    window.confirm = previousConfirm;
  }
});
