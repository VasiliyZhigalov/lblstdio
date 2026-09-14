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

console.log("math.test.mjs: ok");
