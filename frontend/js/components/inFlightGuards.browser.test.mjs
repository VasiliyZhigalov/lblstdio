/**
 * Run from frontend/: node --test --test-concurrency=1 js/components/inFlightGuards.browser.test.mjs
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "path";
import test, { before } from "node:test";
import { fileURLToPath } from "node:url";
import { Window } from "happy-dom";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const posts = [];
const pending = [];

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
  const fakeCtx = new Proxy({}, { get: () => () => {} });
  for (const canvas of win.document.querySelectorAll("canvas")) {
    canvas.getContext = () => fakeCtx;
  }
  const fetchImpl = (url, options = {}) => {
    const method = String(options.method || "GET").toUpperCase();
    const pathname = pathnameOf(url);
    if (method === "POST") posts.push(pathname);
    if (pathname.endsWith("/train") && method === "POST") {
      return new Promise((resolve) => {
        pending.push(() =>
          resolve(
            jsonResponse({
              id: "job-1",
              status: "QUEUED",
              current_epoch: 0,
              epochs: 10,
              progress_percent: 0,
              metrics_history: [],
            })
          )
        );
      });
    }
    if (pathname.includes("/auto-label") && method === "POST") {
      return new Promise((resolve) => {
        pending.push(() =>
          resolve(
            jsonResponse({
              id: "al-1",
              status: "PENDING",
              total_images_processed: 0,
              total_predictions_generated: 0,
            })
          )
        );
      });
    }
    if (pathname.startsWith("/api/v1/training-jobs/")) {
      return jsonResponse({
        id: "job-1",
        status: "COMPLETED",
        current_epoch: 10,
        epochs: 10,
        progress_percent: 100,
        metrics_history: [],
      });
    }
    if (pathname.startsWith("/api/v1/auto-label-jobs/")) {
      return jsonResponse({
        id: "al-1",
        status: "COMPLETED",
        total_images_processed: 1,
        total_predictions_generated: 1,
      });
    }
    if (pathname.endsWith("/dataset-versions")) {
      return jsonResponse([
        { id: "ds-1", name: "v1", status: "READY", version_number: 1, train_count: 4 },
      ]);
    }
    if (pathname.endsWith("/models") || pathname.endsWith("/training/device")) {
      return pathname.endsWith("/training/device")
        ? jsonResponse({ backend: "cpu", label: "CPU", device: "cpu" })
        : jsonResponse([{ id: "model-1", display_name: "m1" }]);
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

function click(id) {
  document.getElementById(id).dispatchEvent(new MouseEvent("click", { bubbles: true }));
}

async function settle() {
  for (let i = 0; i < 20; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

before(async () => {
  installDom();
  const { initTrainingDrawer } = await import("./trainingDrawer.js");
  const { initAutoLabelModal } = await import("./autoLabelModal.js");
  initTrainingDrawer({
    getProject: () => ({ id: "proj-1", task_type: "DETECTION" }),
  });
  initAutoLabelModal({
    getProject: () => ({ id: "proj-1", task_type: "DETECTION" }),
    getImages: () => [{ id: "img-1", status: "UNANNOTATED" }],
    getCurrentImage: () => ({ id: "img-1" }),
  });
  document.getElementById("train-dataset-version").innerHTML =
    `<option value="ds-1" selected>v1</option>`;
  document.getElementById("train-base-model").innerHTML =
    `<option value="pretrained:yolov8n.pt" selected>YOLOv8n</option>`;
  document.getElementById("autolabel-model").innerHTML =
    `<option value="model-1" selected>m1</option>`;
  document.getElementById("autolabel-all-unannotated").checked = true;
});

test("rapid double-click starts a single training job", async () => {
  posts.length = 0;
  click("btn-start-training");
  click("btn-start-training");
  await settle();
  const trainPosts = posts.filter((item) => item.endsWith("/train"));
  assert.equal(trainPosts.length, 1);
  pending.splice(0).forEach((release) => release());
  await settle();
});

test("rapid double-click starts a single auto-label job", async () => {
  posts.length = 0;
  click("btn-submit-autolabel");
  click("btn-submit-autolabel");
  await settle();
  const autoPosts = posts.filter((item) => item.includes("/auto-label"));
  assert.equal(autoPosts.length, 1);
  pending.splice(0).forEach((release) => release());
  await settle();
});
