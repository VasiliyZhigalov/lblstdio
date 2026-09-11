export const MIN_DRAW_SCREEN_PX = 5;
export const HANDLE_SIZE = 7;
export const HANDLE_HIT = 10;
export const MIN_ZOOM = 0.08;
export const MAX_ZOOM = 16;
export const CLASS_COLORS = [
  "#6366F1",
  "#22C55E",
  "#EF4444",
  "#F59E0B",
  "#06B6D4",
  "#EC4899",
  "#8B5CF6",
  "#14B8A6",
  "#F97316",
];

export function clamp(n, min, max) {
  return Math.max(min, Math.min(max, n));
}

export function round6(n) {
  return Number(Number(n).toFixed(6));
}

export function clamp01(n) {
  return clamp(round6(n), 0, 1);
}

export function clientToImage(clientX, clientY, canvasRect, pan, zoom) {
  return {
    x: (clientX - canvasRect.left - pan.x) / zoom,
    y: (clientY - canvasRect.top - pan.y) / zoom,
  };
}

export function imageRectToScreen(x, y, w, h, pan, zoom) {
  return {
    x: x * zoom + pan.x,
    y: y * zoom + pan.y,
    w: w * zoom,
    h: h * zoom,
  };
}

export function yoloToXywh(box, imgW, imgH) {
  const w = box.width * imgW;
  const h = box.height * imgH;
  return {
    x: box.x_center * imgW - w / 2,
    y: box.y_center * imgH - h / 2,
    w,
    h,
  };
}

/**
 * Convert an axis-aligned rect in original image pixels to a YOLO box
 * clipped to the frame [0, 1]. Returns null if the clipped size is empty.
 */
export function xywhToYolo(x, y, w, h, imgW, imgH) {
  if (!imgW || !imgH) return null;
  const x1 = clamp(Math.min(x, x + w), 0, imgW);
  const y1 = clamp(Math.min(y, y + h), 0, imgH);
  const x2 = clamp(Math.max(x, x + w), 0, imgW);
  const y2 = clamp(Math.max(y, y + h), 0, imgH);
  const bw = x2 - x1;
  const bh = y2 - y1;
  if (bw <= 0.5 || bh <= 0.5) return null;
  const yolo = {
    x_center: clamp01((x1 + bw / 2) / imgW),
    y_center: clamp01((y1 + bh / 2) / imgH),
    width: clamp01(bw / imgW),
    height: clamp01(bh / imgH),
  };
  if (yolo.width <= 0 || yolo.height <= 0) return null;
  return yolo;
}

export function fitTransform(imgW, imgH, viewW, viewH, padding = 32) {
  if (!imgW || !imgH || !viewW || !viewH) {
    return { zoom: 1, pan: { x: 0, y: 0 } };
  }
  const scale = Math.min((viewW - padding * 2) / imgW, (viewH - padding * 2) / imgH);
  const zoom = clamp(scale, MIN_ZOOM, MAX_ZOOM);
  return {
    zoom,
    pan: {
      x: (viewW - imgW * zoom) / 2,
      y: (viewH - imgH * zoom) / 2,
    },
  };
}

export function zoomAtPoint(pan, zoom, newZoom, mouseX, mouseY) {
  return {
    x: mouseX - ((mouseX - pan.x) * newZoom) / zoom,
    y: mouseY - ((mouseY - pan.y) * newZoom) / zoom,
  };
}

export const HANDLE_IDS = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

export function handlePoints(x, y, w, h) {
  return {
    nw: { x, y },
    n: { x: x + w / 2, y },
    ne: { x: x + w, y },
    e: { x: x + w, y: y + h / 2 },
    se: { x: x + w, y: y + h },
    s: { x: x + w / 2, y: y + h },
    sw: { x, y: y + h },
    w: { x, y: y + h / 2 },
  };
}

export function hitHandle(screenX, screenY, rect) {
  const points = handlePoints(rect.x, rect.y, rect.w, rect.h);
  for (const id of HANDLE_IDS) {
    const p = points[id];
    if (Math.abs(screenX - p.x) <= HANDLE_HIT && Math.abs(screenY - p.y) <= HANDLE_HIT) {
      return id;
    }
  }
  return null;
}

export function pointInRect(px, py, rect, pad = 0) {
  return (
    px >= rect.x - pad &&
    py >= rect.y - pad &&
    px <= rect.x + rect.w + pad &&
    py <= rect.y + rect.h + pad
  );
}

export function applyHandleResize(box, handle, imgX, imgY, imgW, imgH) {
  let x1 = box.x;
  let y1 = box.y;
  let x2 = box.x + box.w;
  let y2 = box.y + box.h;
  const cx = clamp(imgX, 0, imgW);
  const cy = clamp(imgY, 0, imgH);
  if (handle.includes("n")) y1 = cy;
  if (handle.includes("s")) y2 = cy;
  if (handle.includes("w")) x1 = cx;
  if (handle.includes("e")) x2 = cx;
  return {
    x: Math.min(x1, x2),
    y: Math.min(y1, y2),
    w: Math.abs(x2 - x1),
    h: Math.abs(y2 - y1),
  };
}

export function clampRectToImage(rect, imgW, imgH) {
  const w = Math.min(rect.w, imgW);
  const h = Math.min(rect.h, imgH);
  return {
    x: clamp(rect.x, 0, Math.max(0, imgW - w)),
    y: clamp(rect.y, 0, Math.max(0, imgH - h)),
    w,
    h,
  };
}

export function hexWithAlpha(hex, alphaByte) {
  const raw = (hex || "#6366F1").replace("#", "");
  const normalized = raw.length === 3
    ? raw.split("").map((ch) => ch + ch).join("")
    : raw.slice(0, 6);
  return `#${normalized}${alphaByte}`;
}

export function nextClassColor(index) {
  return CLASS_COLORS[index % CLASS_COLORS.length];
}
