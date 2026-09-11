import { store } from "../store.js";
import {
  HANDLE_SIZE,
  MAX_ZOOM,
  MIN_DRAW_SCREEN_PX,
  MIN_ZOOM,
  applyHandleResize,
  clampRectToImage,
  clientToImage,
  fitTransform,
  handlePoints,
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

  async loadImage(url) {
    const img = new Image();
    img.decoding = "async";
    const done = new Promise((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("Не удалось загрузить изображение"));
    });
    img.src = url;
    await done;
    this.image = img;
    this.fitToScreen();
  }

  clearImage() {
    this.image = null;
    this.draft = null;
    this.scheduleRender();
  }

  fitToScreen() {
    if (!this.image) return;
    const { w, h } = this.viewSize();
    const next = fitTransform(this.image.naturalWidth, this.image.naturalHeight, w, h);
    this.zoom = next.zoom;
    this.pan = next.pan;
    this.scheduleRender();
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
    this.container.style.cursor = value;
  }

  updateHoverCursor(event) {
    if (this.isPanning) {
      this.setCursor("grabbing");
      return;
    }
    if (store.get("spaceHeld")) {
      this.setCursor("grab");
      return;
    }
    if (store.get("mode") === "DRAW") {
      this.setCursor("crosshair");
      return;
    }
    const screen = this.pointerScreen(event);
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
    this.setCursor(this.findBoxAtScreen(screen.x, screen.y) ? "pointer" : "default");
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
    if (!this.image) return;
    if (this.shouldPan(event)) {
      event.preventDefault();
      this.isPanning = true;
      const screen = this.pointerScreen(event);
      this.panStart = { x: screen.x, y: screen.y, panX: this.pan.x, panY: this.pan.y };
      this.setCursor("grabbing");
      return;
    }
    if (event.button !== 0) return;

    const screen = this.pointerScreen(event);
    const imgPt = this.pointerImage(event);
    const mode = store.get("mode");

    if (mode === "DRAW") {
      if (!store.get("activeClassId")) {
        this.container.dispatchEvent(new CustomEvent("need-class", { bubbles: true }));
        return;
      }
      this.isDrawing = true;
      this.drawStart = imgPt;
      this.draft = { x: imgPt.x, y: imgPt.y, w: 0, h: 0 };
      this.scheduleRender();
      return;
    }

    const selectedId = store.get("selectedBoxId");
    const selected = (store.get("annotations") || []).find((box) => box.id === selectedId);
    if (selected) {
      const handle = hitHandle(screen.x, screen.y, this.screenRectForBox(selected));
      if (handle) {
        this.activeHandle = handle;
        this.dragBoxId = selected.id;
        return;
      }
    }

    const hit = this.findBoxAtScreen(screen.x, screen.y);
    if (hit) {
      store.set("selectedBoxId", hit.id);
      const { w, h } = this.imgSize();
      const xywh = yoloToXywh(hit, w, h);
      this.isDragging = true;
      this.dragBoxId = hit.id;
      this.dragOffset = { x: imgPt.x - xywh.x, y: imgPt.y - xywh.y };
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
        const resized = applyHandleResize(current, this.activeHandle, imgPt.x, imgPt.y, imgW, imgH);
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
      if (screenW >= MIN_DRAW_SCREEN_PX && screenH >= MIN_DRAW_SCREEN_PX) {
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

    if (!this.image) return;

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
  }

  drawBox(ctx, box, cls, rect, isSelected, isHovered) {
    const pending = box.verification_status === "PENDING_REVIEW";
    ctx.save();
    ctx.setLineDash(pending ? [6, 4] : []);
    ctx.strokeStyle = cls.color_hex;
    ctx.lineWidth = isSelected ? 2.5 : 2;
    ctx.fillStyle = hexWithAlpha(cls.color_hex, isHovered || isSelected ? "33" : pending ? "1A" : "26");
    ctx.fillRect(rect.x, rect.y, rect.w, rect.h);
    ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);

    const conf = pending && box.confidence ? ` ${Math.round(box.confidence * 100)}%` : "";
    const label = `${pending ? "⚡ " : ""}${cls.name}${conf}`;
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
