/**
 * Lightweight math invariants for the canvas helpers.
 * Run: node --experimental-vm-modules js/utils/math.test.mjs
 * (from frontend/)
 */
import {
  MIN_BOX_IMAGE_PX,
  clamp,
  clampRectToImage,
  enforceMinRect,
  xywhToYolo,
} from "./math.js";

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

assert(clamp(5, 0, 3) === 3, "clamp high");
assert(clamp(-1, 0, 3) === 0, "clamp low");
assert(clamp(2, 0, 3) === 2, "clamp mid");

const clipped = clampRectToImage({ x: -10, y: -5, w: 50, h: 40 }, 100, 80);
assert(clipped.x === 0 && clipped.y === 0, "clampRect origin");
assert(clipped.w === 50 && clipped.h === 40, "clampRect size");

const tiny = enforceMinRect({ x: 10, y: 10, w: 1, h: 1 }, 100, 80);
assert(tiny.w >= MIN_BOX_IMAGE_PX && tiny.h >= MIN_BOX_IMAGE_PX, "enforceMinRect size");

const tooSmall = xywhToYolo(0, 0, 2, 2, 100, 80);
assert(tooSmall === null, "xywhToYolo rejects tiny boxes");

const ok = xywhToYolo(10, 10, 20, 16, 100, 80);
assert(ok && ok.width > 0 && ok.height > 0, "xywhToYolo accepts valid box");
assert(ok.x_center >= 0 && ok.x_center <= 1, "yolo x in range");

function assertInsideFrame(box, label) {
  const left = box.x_center - box.width / 2;
  const right = box.x_center + box.width / 2;
  const top = box.y_center - box.height / 2;
  const bottom = box.y_center + box.height / 2;
  const eps = 1e-6;
  assert(left >= -eps && top >= -eps && right <= 1 + eps && bottom <= 1 + eps, label);
}

// Edge-touching boxes used to overshoot after independent round6 of center/size.
for (const w of [5, 6, 9, 37, 640]) {
  const edge = xywhToYolo(0, 0, w, 40, 640, 480);
  assert(edge, `edge box w=${w} accepted`);
  assertInsideFrame(edge, `edge box w=${w} inside frame`);
}
const rightEdge = xywhToYolo(635, 0, 5, 40, 640, 480);
assert(rightEdge, "right edge accepted");
assertInsideFrame(rightEdge, "right edge inside frame");

console.log("math.test.mjs: ok");
