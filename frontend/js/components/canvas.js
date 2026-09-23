import { store } from "../store.js";
import {
  HANDLE_SIZE,
  MAX_ZOOM,
  MIN_BOX_IMAGE_PX,
  MIN_DRAW_SCREEN_PX,
  MIN_ZOOM,
  applyHandleResize,
  clampRectToImage,
  clientToImage,
  enforceMinRect,
  fitTransform,
  handlePoints,
  hexAlphaFromFloat,
  hexWithAlpha,
  hitHandle,
  imageRectToScreen,
  pointInRect,
  xywhToYolo,
  yoloToXywh,
  zoomAtPoint,
} from "../utils/math.js";

function cursorForHandle(handle) {
  const map = {
    n: "ns-resize",
    s: "ns-resize",
    e: "ew-resize",
    w: "ew-resize",
    nw: "nwse-resize",
    se: "nwse-resize",
    ne: "nesw-resize",
    sw: "nesw-resize",
  };
  return map[handle] || "default";
}

export class AnnotationCanvas {
  constructor(canvasEl, containerEl) {
    this.canvas = canvasEl;
    this.ctx = canvasEl.getContext("2d", { alpha: false });
    this.container = containerEl;
    this.image = null;
    this.zoom = 1;
    this.pan = { x: 0, y: 0 };
    this.dpr = 1;
    this._raf = 0;
    this.isPanning = false;
    this.isDrawing = false;
    this.isDragging = false;
    this.activeHandle = null;
    this.drawStart = { x: 0, y: 0 };
    this.draft = null;
    this.panStart = { x: 0, y: 0, panX: 0, panY: 0 };
    this.dragOffset = { x: 0, y: 0 };
    this.dragBoxId = null;
    this.bound = false;
    this.init();
  }

  init() {
    this.resize();
    this._ro = new ResizeObserver(() => this.resize());
    this._ro.observe(this.container);
    this.bindEvents();
    store.addEventListener("change", () => this.scheduleRender());
  }

  viewSize() {
    return {
      w: this.container.clientWidth || 1,
      h: this.container.clientHeight || 1,
    };
  }

  resize() {
    const { w, h } = this.viewSize();
    this.dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, 2));
    this.canvas.width = Math.floor(w * this.dpr);
    this.canvas.height = Math.floor(h * this.dpr);
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    this.scheduleRender();
  }

  scheduleRender() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = 0;
      this.render();
    });
  }

  discardBitmap() {
    this.image = null;
    this.draft = null;
    this.isDrawing = false;
    this.isDragging = false;
    this.isPanning = false;
    this.activeHandle = null;
    this.dragBoxId = null;
    this.scheduleRender();
  }

  invalidateImage() {
    this._loadId = (this._loadId || 0) + 1;
    this.discardBitmap();
  }

  async loadImage(url) {
    const loadId = (this._loadId = (this._loadId || 0) + 1);
    this.discardBitmap();
    const img = new Image();
    img.decoding = "async";
    const done = new Promise((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("Не удалось загрузить изображение"));
    });
    img.src = url;
    try {
      await done;
    } catch (err) {
      if (loadId !== this._loadId) return false;
      this.discardBitmap();
      throw err;
    }
    if (loadId !== this._loadId) return false;
    this.image = img;
    if (!store.get("zoomLocked")) this.fitToScreen();
    else this.scheduleRender();
    return true;
  }

  clearImage() {
    this.invalidateImage();
  }

  fitToScreen() {
    if (!this.image) return;
    const { w, h } = this.viewSize();
    const next = fitTransform(this.image.naturalWidth, this.image.naturalHeight, w, h);
    this.zoom = next.zoom;
    this.pan = next.pan;
    this.scheduleRender();
  }

  centerOnBox(box) {
    if (!this.image || !box) return;
    const { w, h } = this.viewSize();
    const { w: iw, h: ih } = this.imgSize();
    const xywh = yoloToXywh(box, iw, ih);
    const cx = (xywh.x + xywh.w / 2) * this.zoom;
    const cy = (xywh.y + xywh.h / 2) * this.zoom;
    this.pan = { x: w / 2 - cx, y: h / 2 - cy };
    this.scheduleRender();
  }

  syncFloatActions() {
    const el = document.getElementById("box-float-actions");
    if (!el) return;
    const selectedId = store.get("selectedBoxId");
    const hoveredId = store.get("hoveredBoxId");
    const focusId = selectedId || hoveredId;
    const box = (store.get("annotations") || []).find((item) => item.id === focusId);
    if (
      store.get("hideAnnotations") ||
      store.get("matchingInProgress") ||
      !box ||
      box.verification_status !== "PENDING_REVIEW" ||
      !this.image
    ) {
      el.classList.add("hidden");
      return;
    }
    const rect = this.screenRectForBox(box);
    const top = Math.max(4, rect.y - 34);
    const left = Math.max(4, rect.x + rect.w / 2 - 48);
    el.style.top = `${top}px`;
    el.style.left = `${left}px`;
    el.classList.remove("hidden");
  }

  canvasRect() {
    return this.canvas.getBoundingClientRect();
  }

  pointerImage(event) {
    return clientToImage(event.clientX, event.clientY, this.canvasRect(), this.pan, this.zoom);
  }

  pointerScreen(event) {
    const rect = this.canvasRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  imgSize() {
    if (!this.image) return { w: 1, h: 1 };
    return { w: this.image.naturalWidth, h: this.image.naturalHeight };
  }

  screenRectForBox(box) {
    const { w, h } = this.imgSize();
    const xywh = yoloToXywh(box, w, h);
    return imageRectToScreen(xywh.x, xywh.y, xywh.w, xywh.h, this.pan, this.zoom);
  }

  findBoxAtScreen(sx, sy) {
    if (store.get("hideAnnotations")) return null;
    const annotations = store.get("annotations") || [];
    for (let i = annotations.length - 1; i >= 0; i -= 1) {
      const box = annotations[i];
      if (pointInRect(sx, sy, this.screenRectForBox(box), 2)) return box;
    }
    return null;
  }

  commitBoxGeometry(boxId, rect) {
    const { w, h } = this.imgSize();
    const yolo = xywhToYolo(rect.x, rect.y, rect.w, rect.h, w, h);
    if (!yolo) return;
    const annotations = store.get("annotations").map((box) =>
      box.id === boxId ? { ...box, ...yolo } : box
    );
    store.patch({ annotations, hasUnsavedChanges: true, saveStatus: "unsaved" });
  }

  setCursor(value) {
    if (store.get("matchingInProgress")) {
      this.container.style.cursor = "wait";
      return;
    }
    this.container.style.cursor = value;
  }

  updateHoverCursor(event) {
    if (store.get("matchingInProgress")) {
      this.setCursor("wait");
      return;
    }
    if (this.isPanning) {
      this.setCursor("grabbing");
      return;
    }
    if (store.get("spaceHeld")) {
      this.setCursor("grab");
      return;
    }
    const screen = this.pointerScreen(event);
    if (!store.get("hideAnnotations")) {
      const selectedId = store.get("selectedBoxId");
      if (selectedId) {
        const selected = (store.get("annotations") || []).find((box) => box.id === selectedId);
        if (selected) {
          const handle = hitHandle(screen.x, screen.y, this.screenRectForBox(selected));
          if (handle) {
            this.setCursor(cursorForHandle(handle));
            return;
          }
          if (pointInRect(screen.x, screen.y, this.screenRectForBox(selected))) {
            this.setCursor("move");
            return;
          }
        }
      }
      if (this.findBoxAtScreen(screen.x, screen.y)) {
        this.setCursor("pointer");
        return;
      }
    }
    this.setCursor(store.get("mode") === "DRAW" ? "crosshair" : "default");
  }

  bindEvents() {
    if (this.bound) return;
    this.bound = true;

    this.canvas.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        if (!this.image) return;
        const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
        const nextZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, this.zoom * factor));
        if (nextZoom === this.zoom) return;
        const screen = this.pointerScreen(event);
        this.pan = zoomAtPoint(this.pan, this.zoom, nextZoom, screen.x, screen.y);
        this.zoom = nextZoom;
        this.scheduleRender();
      },
      { passive: false }
    );

    this.canvas.addEventListener("mousedown", (event) => this.onMouseDown(event));
    window.addEventListener("mousemove", (event) => this.onMouseMove(event));
    window.addEventListener("mouseup", (event) => this.onMouseUp(event));
    this.canvas.addEventListener("contextmenu", (event) => event.preventDefault());
    this.canvas.addEventListener("dblclick", (event) => {
      event.preventDefault();
      this.fitToScreen();
    });
  }

  shouldPan(event) {
    return event.button === 1 || (event.button === 0 && store.get("spaceHeld"));
  }

  onMouseDown(event) {
    if (!this.image || store.get("matchingInProgress")) return;
    if (this.shouldPan(event)) {
      event.preventDefault();
      this.isPanning = true;
      const screen = this.pointerScreen(event);
      this.panStart = { x: screen.x, y: screen.y, panX: this.pan.x, panY: this.pan.y };
      this.setCursor("grabbing");
      return;
    }
    if (event.button !== 0) return;
    if (store.get("currentProject")?.task_type === "CLASSIFICATION") return;

    const screen = this.pointerScreen(event);
    const imgPt = this.pointerImage(event);
    const mode = store.get("mode");
    const hide = store.get("hideAnnotations");

    const selectedId = store.get("selectedBoxId");
    const selected = (store.get("annotations") || []).find((box) => box.id === selectedId);
    if (selected && !hide) {
      const handle = hitHandle(screen.x, screen.y, this.screenRectForBox(selected));
      if (handle) {
        this.activeHandle = handle;
        this.dragBoxId = selected.id;
        return;
      }
    }

    const hit = hide ? null : this.findBoxAtScreen(screen.x, screen.y);
    if (hit) {
      store.set("selectedBoxId", hit.id);
      const { w, h } = this.imgSize();
      const xywh = yoloToXywh(hit, w, h);
      this.isDragging = true;
      this.dragBoxId = hit.id;
      this.dragOffset = { x: imgPt.x - xywh.x, y: imgPt.y - xywh.y };
      return;
    }

    if (mode === "DRAW") {
      if (!store.get("activeClassId")) {
        this.container.dispatchEvent(new CustomEvent("need-class", { bubbles: true }));
        return;
      }
      store.set("selectedBoxId", null);
      this.isDrawing = true;
      this.drawStart = imgPt;
      this.draft = { x: imgPt.x, y: imgPt.y, w: 0, h: 0 };
      this.scheduleRender();
      return;
    }

    store.set("selectedBoxId", null);
  }

  onMouseMove(event) {
    if (this.isPanning) {
      const screen = this.pointerScreen(event);
      this.pan = {
        x: this.panStart.panX + (screen.x - this.panStart.x),
        y: this.panStart.panY + (screen.y - this.panStart.y),
      };
      this.scheduleRender();
      return;
    }

    if (this.isDrawing) {
      const imgPt = this.pointerImage(event);
      this.draft = {
        x: this.drawStart.x,
        y: this.drawStart.y,
        w: imgPt.x - this.drawStart.x,
        h: imgPt.y - this.drawStart.y,
      };
      this.scheduleRender();
      return;
    }

    const { w: imgW, h: imgH } = this.imgSize();
    const imgPt = this.pointerImage(event);

    if (this.activeHandle && this.dragBoxId) {
      const box = store.get("annotations").find((item) => item.id === this.dragBoxId);
      if (box) {
        const current = yoloToXywh(box, imgW, imgH);
        const resized = enforceMinRect(
          applyHandleResize(current, this.activeHandle, imgPt.x, imgPt.y, imgW, imgH),
          imgW,
          imgH
        );
        this.commitBoxGeometry(this.dragBoxId, resized);
      }
      return;
    }

    if (this.isDragging && this.dragBoxId) {
      const box = store.get("annotations").find((item) => item.id === this.dragBoxId);
      if (box) {
        const current = yoloToXywh(box, imgW, imgH);
        const moved = clampRectToImage(
          {
            x: imgPt.x - this.dragOffset.x,
            y: imgPt.y - this.dragOffset.y,
            w: current.w,
            h: current.h,
          },
          imgW,
          imgH
        );
        this.commitBoxGeometry(this.dragBoxId, moved);
      }
      return;
    }

    this.updateHoverCursor(event);
    const screen = this.pointerScreen(event);
    const hovered = this.findBoxAtScreen(screen.x, screen.y);
    const hoveredId = hovered?.id || null;
    if (hoveredId !== store.get("hoveredBoxId")) {
      store.set("hoveredBoxId", hoveredId);
    }
  }

  onMouseUp(event) {
    if (this.isPanning) {
      this.isPanning = false;
      this.updateHoverCursor(event);
      return;
    }

    if (this.isDrawing) {
      this.isDrawing = false;
      const imgPt = this.pointerImage(event);
      const w = imgPt.x - this.drawStart.x;
      const h = imgPt.y - this.drawStart.y;
      this.draft = null;
      const screenW = Math.abs(w) * this.zoom;
      const screenH = Math.abs(h) * this.zoom;
      if (
        screenW >= MIN_DRAW_SCREEN_PX &&
        screenH >= MIN_DRAW_SCREEN_PX &&
        Math.abs(w) >= MIN_BOX_IMAGE_PX &&
        Math.abs(h) >= MIN_BOX_IMAGE_PX
      ) {
        const { w: imgW, h: imgH } = this.imgSize();
        const yolo = xywhToYolo(this.drawStart.x, this.drawStart.y, w, h, imgW, imgH);
        const classId = store.get("activeClassId");
        if (yolo && classId) {
          const newBox = {
            id: crypto.randomUUID(),
            class_id: classId,
            ...yolo,
            source: "MANUAL",
            verification_status: "VERIFIED",
            confidence: 1.0,
          };
          store.patch({
            annotations: [...store.get("annotations"), newBox],
            selectedBoxId: newBox.id,
            hasUnsavedChanges: true,
            saveStatus: "unsaved",
          });
          const screen = this.pointerScreen(event);
          this.container.dispatchEvent(
            new CustomEvent("box-drawn", {
              bubbles: true,
              detail: { boxId: newBox.id, screenX: screen.x, screenY: screen.y },
            })
          );
        }
      }
      this.scheduleRender();
      return;
    }

    this.activeHandle = null;
    this.isDragging = false;
    this.dragBoxId = null;
  }

  render() {
    const ctx = this.ctx;
    const { w, h } = this.viewSize();
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.fillStyle = "#0a0a0c";
    ctx.fillRect(0, 0, w, h);

    if (!this.image) {
      this.syncFloatActions();
      return;
    }

    ctx.imageSmoothingEnabled = this.zoom < 1.2;
    ctx.imageSmoothingQuality = this.zoom < 0.5 ? "low" : "medium";
    ctx.drawImage(
      this.image,
      this.pan.x,
      this.pan.y,
      this.image.naturalWidth * this.zoom,
      this.image.naturalHeight * this.zoom
    );

    const classes = store.get("classes") || [];
    const selectedId = store.get("selectedBoxId");
    const hoveredId = store.get("hoveredBoxId");
    const annotations = store.get("annotations") || [];
    const hide = store.get("hideAnnotations") === true;

    if (!hide) {
      for (const box of annotations) {
        const cls = classes.find((item) => item.id === box.class_id) || {
          name: "Unknown",
          color_hex: "#6366F1",
        };
        const rect = this.screenRectForBox(box);
        const isSelected = box.id === selectedId;
        const isHovered = box.id === hoveredId;
        this.drawBox(ctx, box, cls, rect, isSelected, isHovered);
      }
    }

    this.drawRecheckHint(ctx);

    if (this.draft) {
      const { w: imgW, h: imgH } = this.imgSize();
      const x = Math.max(0, Math.min(this.draft.x, this.draft.x + this.draft.w));
      const y = Math.max(0, Math.min(this.draft.y, this.draft.y + this.draft.h));
      const dw = Math.abs(this.draft.w);
      const dh = Math.abs(this.draft.h);
      const screen = imageRectToScreen(
        Math.max(0, x),
        Math.max(0, y),
        Math.min(imgW, x + dw) - Math.max(0, x),
        Math.min(imgH, y + dh) - Math.max(0, y),
        this.pan,
        this.zoom
      );
      ctx.save();
      ctx.setLineDash([5, 3]);
      ctx.strokeStyle = "#818cf8";
      ctx.lineWidth = 1.5;
      ctx.fillStyle = "rgba(99, 102, 241, 0.12)";
      ctx.fillRect(screen.x, screen.y, screen.w, screen.h);
      ctx.strokeRect(screen.x, screen.y, screen.w, screen.h);
      ctx.restore();
    }

    this.drawMatchDebug(ctx);
    this.syncFloatActions();
  }

  drawMatchDebug(ctx) {
    const debug = store.get("matchDebug");
    if (!debug?.transform || !store.get("showMatchDebug")) return;
    const t = debug.transform;
    const arrows = debug.arrows || [];

    const toScreen = (ix, iy) => ({
      x: ix * this.zoom + this.pan.x,
      y: iy * this.zoom + this.pan.y,
    });

    ctx.save();
    // Per-box arrows: identity place → transformed place
    for (const arrow of arrows) {
      const from = toScreen(arrow.from_x, arrow.from_y);
      const to = toScreen(arrow.to_x, arrow.to_y);
      const dx = to.x - from.x;
      const dy = to.y - from.y;
      const len = Math.hypot(dx, dy);

      ctx.beginPath();
      ctx.setLineDash([4, 3]);
      ctx.strokeStyle = "rgba(250, 204, 21, 0.85)";
      ctx.lineWidth = 1.5;
      ctx.moveTo(from.x, from.y);
      ctx.lineTo(to.x, to.y);
      ctx.stroke();
      ctx.setLineDash([]);

      // start = yellow dot (before), end = cyan arrow (after)
      ctx.fillStyle = "#facc15";
      ctx.beginPath();
      ctx.arc(from.x, from.y, 3.5, 0, Math.PI * 2);
      ctx.fill();

      if (len > 4) {
        const angle = Math.atan2(dy, dx);
        ctx.fillStyle = "#22d3ee";
        ctx.beginPath();
        ctx.moveTo(to.x, to.y);
        ctx.lineTo(to.x - 10 * Math.cos(angle - 0.4), to.y - 10 * Math.sin(angle - 0.4));
        ctx.lineTo(to.x - 10 * Math.cos(angle + 0.4), to.y - 10 * Math.sin(angle + 0.4));
        ctx.closePath();
        ctx.fill();
      }
    }

    // Global image-center vector (tx, ty) in image pixels
    const { w: imgW, h: imgH } = this.imgSize();
    const origin = toScreen(imgW / 2, imgH / 2);
    const tip = toScreen(imgW / 2 + t.tx, imgH / 2 + t.ty);
    ctx.strokeStyle = "#f97316";
    ctx.fillStyle = "#f97316";
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.moveTo(origin.x, origin.y);
    ctx.lineTo(tip.x, tip.y);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(origin.x, origin.y, 4, 0, Math.PI * 2);
    ctx.fill();
    const glen = Math.hypot(tip.x - origin.x, tip.y - origin.y);
    if (glen > 4) {
      const angle = Math.atan2(tip.y - origin.y, tip.x - origin.x);
      ctx.beginPath();
      ctx.moveTo(tip.x, tip.y);
      ctx.lineTo(tip.x - 12 * Math.cos(angle - 0.4), tip.y - 12 * Math.sin(angle - 0.4));
      ctx.lineTo(tip.x - 12 * Math.cos(angle + 0.4), tip.y - 12 * Math.sin(angle + 0.4));
      ctx.closePath();
      ctx.fill();
    }

    // HUD
    const lines = [
      "MATCH DEBUG",
      `Δx=${t.tx.toFixed(1)}px  Δy=${t.ty.toFixed(1)}px`,
      `rot=${t.rotation_deg.toFixed(2)}°  scale=${t.scale.toFixed(4)}`,
      `conf=${(t.match_score * 100).toFixed(1)}%`,
      Math.hypot(t.tx, t.ty) < 2
        ? "⚠ вектор ≈ 0 (кадры почти совпали)"
        : `‖Δ‖=${Math.hypot(t.tx, t.ty).toFixed(1)}px`,
    ];
    ctx.font = "12px ui-monospace, SFMono-Regular, Menlo, monospace";
    const pad = 8;
    const lineH = 16;
    const boxW = Math.max(...lines.map((line) => ctx.measureText(line).width)) + pad * 2;
    const boxH = lines.length * lineH + pad * 2;
    ctx.fillStyle = "rgba(9, 9, 11, 0.82)";
    ctx.strokeStyle = "rgba(249, 115, 22, 0.7)";
    ctx.lineWidth = 1;
    ctx.fillRect(10, 10, boxW, boxH);
    ctx.strokeRect(10, 10, boxW, boxH);
    ctx.fillStyle = "#fdba74";
    lines.forEach((line, index) => {
      ctx.fillStyle = index === 0 ? "#fb923c" : line.startsWith("⚠") ? "#fbbf24" : "#e4e4e7";
      ctx.fillText(line, 10 + pad, 10 + pad + (index + 1) * lineH - 4);
    });
    ctx.restore();
  }

  drawRecheckHint(ctx) {
    const image = store.get("currentImage");
    if (image?.status !== "REQUIRES_RECHECK") return;
    const pending = (store.get("annotations") || []).filter(
      (box) => box.verification_status === "PENDING_REVIEW"
    ).length;
    const lines = [
      "АУДИТ МОДЕЛИ",
      "сплошные — текущая разметка",
      "пунктир — что увидела модель",
      pending
        ? `предсказаний: ${pending}`
        : "модель ничего не нашла на кадре",
    ];
    ctx.save();
    ctx.font = "11px ui-monospace, SFMono-Regular, Menlo, monospace";
    const pad = 8;
    const lineH = 15;
    const boxW = Math.max(...lines.map((line) => ctx.measureText(line).width)) + pad * 2;
    const boxH = lines.length * lineH + pad * 2;
    ctx.fillStyle = "rgba(69, 10, 10, 0.88)";
    ctx.strokeStyle = "rgba(248, 113, 113, 0.7)";
    ctx.lineWidth = 1;
    ctx.fillRect(10, 10, boxW, boxH);
    ctx.strokeRect(10, 10, boxW, boxH);
    lines.forEach((line, index) => {
      ctx.fillStyle = index === 0 ? "#fca5a5" : "#fecaca";
      ctx.fillText(line, 10 + pad, 10 + pad + (index + 1) * lineH - 4);
    });
    ctx.restore();
  }

  drawBox(ctx, box, cls, rect, isSelected, isHovered) {
    const pending = box.verification_status === "PENDING_REVIEW";
    const boxOpacity = store.get("boxOpacity") ?? 0.2;
    const opacity =
      isSelected || isHovered ? Math.min(1, Number(boxOpacity) + 0.15) : Number(boxOpacity);
    const fillAlpha = hexAlphaFromFloat(opacity);
    ctx.save();
    ctx.setLineDash(pending ? [6, 4] : []);
    ctx.strokeStyle = cls.color_hex;
    ctx.lineWidth = isSelected ? 2.5 : 2;
    ctx.fillStyle = hexWithAlpha(cls.color_hex, fillAlpha);
    ctx.fillRect(rect.x, rect.y, rect.w, rect.h);
    ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);

    const conf = pending && box.confidence ? ` ${Math.round(box.confidence * 100)}%` : "";
    const label = `${pending ? "модель " : ""}${cls.name}${conf}`;
    ctx.font = "11px ui-monospace, SFMono-Regular, Menlo, monospace";
    const textW = ctx.measureText(label).width;
    const badgeH = 18;
    const badgeW = textW + 12;
    const badgeY = rect.y - badgeH >= 0 ? rect.y - badgeH : rect.y;
    ctx.setLineDash([]);
    ctx.fillStyle = pending ? "#854d0e" : "#18181b";
    ctx.fillRect(rect.x, badgeY, badgeW, badgeH);
    ctx.fillStyle = "#ffffff";
    ctx.fillText(label, rect.x + 6, badgeY + 13);

    if (isSelected) {
      ctx.fillStyle = "#ffffff";
      ctx.strokeStyle = "#09090b";
      ctx.lineWidth = 1;
      const points = handlePoints(rect.x, rect.y, rect.w, rect.h);
      for (const point of Object.values(points)) {
        ctx.fillRect(point.x - HANDLE_SIZE / 2, point.y - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
        ctx.strokeRect(point.x - HANDLE_SIZE / 2, point.y - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
      }
    }
    ctx.restore();
  }
}
