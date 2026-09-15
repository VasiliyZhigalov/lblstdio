# Спецификация Frontend (Vanilla JS + HTML Templates)
## Платформа активного обучения и полуавтоматической разметки «LBL_STDIO»

---

## 1. Стек прототипа и архитектурный подход

Для максимальной скорости работы прототипа без сборщиков (Webpack/Vite) и тяжелых фреймворков используется **современный нативный стек**:

* **Ядро:** Чистый JavaScript (ES6+ модули `<script type="module">`).
* **Разметка:** HTML5 семантические шаблоны (`<template id="...">`), нативные кастомные события (`CustomEvent`).
* **Стилизация:** **Tailwind CSS** (через CDN скрипт) в темной теме (стиль Linear / Roboflow / Cursor).
* **Иконки:** **Lucide Icons** (через CDN `lucide.min.js`).
* **Графика холста:** Нативный **HTML5 Canvas API** (своя легкая надстройка без тяжелых библиотек для полного контроля отрисовки и событий) либо подключение **Konva.js** через один тег `<script>`. В данной спеке приводится нативная реализация на Canvas 2D — она мгновенно загружается, не имеет зависимостей и работает с 60 FPS.

---

## 2. Дизайн-система и визуальное кодирование статусов

Главный фокус в UI — **мгновенное визуальное различие** между проверенными данными и гипотезами алгоритмов.

### Цветовая палитра и стили рамок (Bounding Boxes)

```
[ Сплошная линия + заливка 15% ]        [ Пунктир 4x4 + заливка 10% + Бейдж 84% ]
+------------------------------+        + - - - - - - - - - - - - - - -+
| [Car] ✓                      |        | [Car 0.84] ?  [✓] [✗]        |
|                              |        |                              |
|                              |        |                              |
+------------------------------+        + - - - - - - - - - - - - - - -+
   VERIFIED (Ручной/Одобренный)              PENDING_REVIEW (AI / Keypoints)
```

1. **`VERIFIED` (Ручная разметка или подтвержденная человеком):**
   * Граница: **Сплошная линия** (Solid 2px) цвета класса.
   * Заливка: 15% непрозрачности цвета класса.
   * Ярлык: Плашка с именем класса и иконкой галочки `✓`.
2. **`PENDING_REVIEW` (Предсказание YOLO или перенос через Keypoints):**
   * Граница: **Пунктирная линия** (Dashed 2px: `[6, 4]`).
   * Заливка: 10% непрозрачности.
   * Ярлык: Плашка с именем класса, процентом уверенности (например, `91%`) и иконкой молнии `⚡` или ключа `🔑`.
   * **Floating Actions (Всплывающие кнопки над боксом):** При наведении или выделении прямо над рамкой появляются мини-кнопки `[✓ Подтвердить]` и `[✕ Удалить]`.
3. **`SELECTED` (Активная рамка в фокусе):**
   * 8 маркеров трансформации по углам и центрам граней (квадраты $7 \times 7$ px белого цвета с черной обводкой).

---

## 3. Архитектура приложения (Vanilla Modules)

Файловая структура фронтенда организована по принципу микро-модулей:

```text
frontend/
├── index.html              # Главная точка входа, разметка лэйаута и <template>
├── css/
│   └── styles.css          # Кастомные стили (скроллбары, анимация пульсации)
└── js/
    ├── app.js              # Инициализация и роутинг экранов
    ├── store.js            # Реактивное состояние (Proxy Store)
    ├── api.js              # REST API клиент (Fetch)
    ├── hotkeys.js          # Централизованный обработчик клавиатуры
    ├── components/
    │   ├── canvas.js       # Рендерер холста, Zoom/Pan, трансформация боксов
    │   ├── sidebar.js      # Список классов, слои текущего кадра
    │   ├── reviewBar.js    # Панель экспресс-подтверждения (Accept All / Reject)
    │   └── streamHub.js    # Вкладка «Стрим и Сбор»: live MJPEG, tripwire, harvest
    └── utils/
        └── math.js         # Перевод экранных координат в нормализованные (YOLO)
```

---

## 4. Реактивное состояние (Lightweight Reactive Store)

Чтобы компоненты синхронизировались без React, создается реактивный `Store` на нативных **JavaScript Proxy** и шине событий `EventTarget`:

```javascript
// js/store.js
class Store extends EventTarget {
  constructor(initialState) {
    super();
    this.state = new Proxy(initialState, {
      set: (target, property, value) => {
        target[property] = value;
        // Генерируем событие изменения конкретного поля и общее событие
        this.dispatchEvent(new CustomEvent('change', { detail: { property, value } }));
        this.dispatchEvent(new CustomEvent(`change:${property}`, { detail: value }));
        return true;
      }
    });
  }

  set(property, value) {
    this.state[property] = value;
  }

  get(property) {
    return this.state[property];
  }
}

export const store = new Store({
  currentProject: null,
  currentImage: null,
  annotations: [],        // Список боксов текущего кадра
  selectedBoxId: null,
  activeClassId: null,
  classes: [],
  mode: 'SELECT',         // 'SELECT' | 'DRAW'
  clipboardBox: null,     // Буфер для Keypoint Propagation (Ctrl+C)
  zoom: 1.0,
  pan: { x: 0, y: 0 },
  hasUnsavedChanges: false
});
```

---

## 5. UI и структура экранов (`index.html`)

### 5.1. Главный шаблон разметчика (Studio Layout)

Интерфейс оптимизирован под плотную работу без лишних кликов:

```html
<!-- index.html (фрагмент рабочего экрана) -->
<div id="app" class="flex h-screen w-screen overflow-hidden bg-zinc-950 text-zinc-100 select-none">
  
  <!-- ЛЕВАЯ ПАНЕЛЬ: Инструменты (Toolbar) -->
  <aside class="w-14 flex flex-col items-center py-4 border-r border-zinc-800 bg-zinc-900/50 space-y-4 z-10">
    <button id="tool-select" class="p-2.5 rounded-lg hover:bg-zinc-800 text-indigo-400 bg-zinc-800/80 transition" title="Выбор / Изменение (V)">
      <i data-lucide="mouse-pointer-2" class="w-5 h-5"></i>
    </button>
    <button id="tool-draw" class="p-2.5 rounded-lg hover:bg-zinc-800 text-zinc-400 transition" title="Новая рамка (W)">
      <i data-lucide="square" class="w-5 h-5"></i>
    </button>
    
    <div class="w-8 h-[1px] bg-zinc-800 my-2"></div>

    <button id="tool-fit" class="p-2.5 rounded-lg hover:bg-zinc-800 text-zinc-400 transition" title="Сбросить зум (F)">
      <i data-lucide="maximize" class="w-5 h-5"></i>
    </button>
  </aside>

  <!-- ЦЕНТР: Верхняя панель + Viewport Canvas + Нижний Review Bar -->
  <main class="flex-1 flex flex-col min-w-0 relative">
    
    <!-- Topbar: Хлебные крошки, статус и стрим -->
    <header class="h-12 border-b border-zinc-800 bg-zinc-900/30 flex items-center justify-between px-4 z-10">
      <div class="flex items-center space-x-3">
        <span id="image-filename" class="font-mono text-xs text-zinc-400">frame_0042.jpg</span>
        <span id="badge-split" class="px-2 py-0.5 text-[10px] font-semibold tracking-wide rounded bg-blue-950 text-blue-400 border border-blue-800/50">TRAIN</span>
        <span id="save-indicator" class="flex items-center text-[11px] text-zinc-500 space-x-1">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
          <span>Синхронизировано</span>
        </span>
      </div>

      <!-- Кнопки действий: Обучение и Поток -->
      <div class="flex items-center space-x-2">
        <button id="btn-stream-modal" class="flex items-center space-x-1.5 px-2.5 py-1 text-xs font-medium rounded-md bg-amber-500/10 text-amber-400 border border-amber-500/20 hover:bg-amber-500/20 transition">
          <i data-lucide="radio" class="w-3.5 h-3.5 animate-pulse text-amber-500"></i>
          <span>Стрим (Active Learning)</span>
        </button>
        <button id="btn-train-modal" class="flex items-center space-x-1.5 px-3 py-1 text-xs font-medium rounded-md bg-indigo-600 hover:bg-indigo-500 text-white transition shadow-sm">
          <i data-lucide="sparkles" class="w-3.5 h-3.5"></i>
          <span>Обучить v1</span>
        </button>
      </div>
    </header>

    <!-- Холст разметчика -->
    <div id="canvas-container" class="flex-1 relative overflow-hidden bg-[#0a0a0c] cursor-crosshair">
      <canvas id="annotation-canvas" class="absolute inset-0"></canvas>
      
      <!-- Подсказка буфера обмена Keypoints (Floating Toast) -->
      <div id="clipboard-toast" class="hidden absolute top-4 left-1/2 -translate-x-1/2 bg-zinc-900/90 border border-indigo-500/50 text-indigo-200 text-xs px-3 py-1.5 rounded-full shadow-xl backdrop-blur flex items-center space-x-2">
        <i data-lucide="copy" class="w-3.5 h-3.5 text-indigo-400"></i>
        <span>Бокс скопирован. Нажмите <kbd class="px-1.5 py-0.5 bg-zinc-800 rounded text-zinc-300 font-mono">Ctrl+Shift+V</kbd> для сопоставления</span>
      </div>
    </div>

    <!-- НИЖНЯЯ ПАНЕЛЬ: Экспресс-верификация предсказаний (HITL Bar) -->
    <footer id="review-bar" class="h-14 border-t border-zinc-800 bg-zinc-900/80 px-6 flex items-center justify-between z-10">
      <div class="flex items-center space-x-4">
        <button id="btn-prev" class="px-3 py-1.5 text-xs bg-zinc-800 hover:bg-zinc-700 rounded text-zinc-300 flex items-center space-x-1">
          <i data-lucide="chevron-left" class="w-4 h-4"></i> <span>A</span>
        </button>
        <span class="text-xs text-zinc-400 font-mono">Кадр <span id="current-idx">42</span> из <span id="total-idx">150</span></span>
        <button id="btn-next" class="px-3 py-1.5 text-xs bg-zinc-800 hover:bg-zinc-700 rounded text-zinc-300 flex items-center space-x-1">
          <span>D</span> <i data-lucide="chevron-right" class="w-4 h-4"></i>
        </button>
      </div>

      <!-- Блок быстрых решений при наличии неподтвержденных рамок -->
      <div id="ai-verification-actions" class="flex items-center space-x-3">
        <span class="text-xs text-amber-400 flex items-center space-x-1.5 font-medium">
          <i data-lucide="alert-circle" class="w-4 h-4"></i>
          <span>Требует проверки: <strong id="pending-count">2</strong> рамки</span>
        </span>
        <button id="btn-reject-all" class="px-3 py-1.5 text-xs bg-red-950/40 border border-red-800/50 hover:bg-red-900/50 text-red-300 rounded transition">
          Отклонить все (R)
        </button>
        <button id="btn-approve-all" class="px-4 py-1.5 text-xs bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded flex items-center space-x-1.5 transition shadow-lg shadow-emerald-900/20">
          <i data-lucide="check-check" class="w-4 h-4"></i>
          <span>Подтвердить все (Space)</span>
        </button>
      </div>
    </footer>
  </main>

  <!-- ПРАВАЯ ПАНЕЛЬ: Классы и Слои -->
  <aside class="w-72 border-l border-zinc-800 bg-zinc-900/40 flex flex-col z-10">
    <!-- Классы -->
    <div class="p-4 border-b border-zinc-800">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-xs font-semibold uppercase tracking-wider text-zinc-400">Классы (1-9)</h3>
        <button id="btn-add-class" class="text-xs text-indigo-400 hover:text-indigo-300">+ Новый</button>
      </div>
      <div id="classes-list" class="space-y-1">
        <!-- Генерируется из store: [ (1) [•] Defect ] -->
      </div>
    </div>

    <!-- Слои на текущем кадре -->
    <div class="flex-1 overflow-y-auto p-4">
      <h3 class="text-xs font-semibold uppercase tracking-wider text-zinc-400 mb-3">Объекты на кадре</h3>
      <div id="annotations-list" class="space-y-1.5">
        <!-- Список рамок с бейджами верификации -->
      </div>
    </div>
  </aside>
</div>
```

---

## 6. Реализация холста (Canvas Engine) и математика

Ключевой файл `js/components/canvas.js` берет на себя рендеринг, масштабирование под курсор и перевод систем координат.

```javascript
// js/components/canvas.js
import { store } from '../store.js';

export class AnnotationCanvas {
  constructor(canvasEl, containerEl) {
    this.canvas = canvasEl;
    this.ctx = canvasEl.getContext('2d');
    this.container = containerEl;

    this.image = null;             // Загруженный Image()
    this.isPanning = false;
    this.isDrawing = false;
    this.drawStart = { x: 0, y: 0 };
    this.activeHandle = null;      // Маркер ресайза при выделении

    this.init();
  }

  init() {
    this.resize();
    window.addEventListener('resize', () => this.resize());
    this.bindEvents();

    // Перерисовка при любых изменениях в состоянии
    store.addEventListener('change', () => this.render());
  }

  resize() {
    this.canvas.width = this.container.clientWidth;
    this.canvas.height = this.container.clientHeight;
    this.render();
  }

  // --- МАТЕМАТИКА КООРДИНАТ ---

  // Преобразование координат курсора мыши в координаты оригинального изображения (px)
  clientToImageCoords(clientX, clientY) {
    const rect = this.canvas.getBoundingClientRect();
    const pan = store.get('pan');
    const zoom = store.get('zoom');

    const screenX = clientX - rect.left;
    const screenY = clientY - rect.top;

    return {
      x: (screenX - pan.x) / zoom,
      y: (screenY - pan.y) / zoom
    };
  }

  // Перевод абсолютных пикселей оригинала в нормализованные (YOLO) 0.0 - 1.0
  toNormalizedBBox(x, y, w, h) {
    const imgW = this.image.naturalWidth;
    const imgH = this.image.naturalHeight;

    const xMin = Math.max(0, Math.min(x, x + w));
    const yMin = Math.max(0, Math.min(y, y + h));
    const width = Math.abs(w);
    const height = Math.abs(h);

    return {
      x_center: Number(((xMin + width / 2) / imgW).toFixed(6)),
      y_center: Number(((yMin + height / 2) / imgH).toFixed(6)),
      width: Number((width / imgW).toFixed(6)),
      height: Number((height / imgH).toFixed(6))
    };
  }

  // Перевод нормализованных координат YOLO в экранные координаты текущего Canvas
  fromNormalizedToScreen(box) {
    const pan = store.get('pan');
    const zoom = store.get('zoom');
    const imgW = this.image.naturalWidth;
    const imgH = this.image.naturalHeight;

    const origW = box.width * imgW;
    const origH = box.height * imgH;
    const origX = (box.x_center * imgW) - (origW / 2);
    const origY = (box.y_center * imgH) - (origH / 2);

    return {
      screenX: origX * zoom + pan.x,
      screenY: origY * zoom + pan.y,
      screenW: origW * zoom,
      screenH: origH * zoom
    };
  }

  // --- ОТРИСОВКА (RENDER LOOP) ---

  render() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    if (!this.image) return;

    const pan = store.get('pan');
    const zoom = store.get('zoom');

    ctx.save();
    ctx.translate(pan.x, pan.y);
    ctx.scale(zoom, zoom);

    // 1. Отрисовка базовой картинки
    ctx.drawImage(this.image, 0, 0);
    ctx.restore();

    // 2. Отрисовка всех рамок
    const annotations = store.get('annotations') || [];
    const selectedId = store.get('selectedBoxId');
    const classes = store.get('classes');

    annotations.forEach(box => {
      const cls = classes.find(c => c.id === box.class_id) || { name: 'Unknown', color_hex: '#6366f1' };
      const { screenX, screenY, screenW, screenH } = this.fromNormalizedToScreen(box);
      const isSelected = box.id === selectedId;

      ctx.save();

      // Стиль рамки в зависимости от статуса верификации
      if (box.verification_status === 'PENDING_REVIEW') {
        ctx.setLineDash([6, 4]); // Пунктир для непроверенных боксов
        ctx.strokeStyle = cls.color_hex;
        ctx.lineWidth = 2;
        ctx.fillStyle = cls.color_hex + '1A'; // 10% прозрачности
      } else {
        ctx.setLineDash([]);    // Сплошная линия для верифицированных
        ctx.strokeStyle = cls.color_hex;
        ctx.lineWidth = isSelected ? 3 : 2;
        ctx.fillStyle = cls.color_hex + '26'; // 15% прозрачности
      }

      // Прямоугольник
      ctx.fillRect(screenX, screenY, screenW, screenH);
      ctx.strokeRect(screenX, screenY, screenW, screenH);

      // Бейдж с именем класса и уверенностью
      this.drawBadge(ctx, box, cls, screenX, screenY);

      // Если бокс выделен — рисуем маркеры трансформации
      if (isSelected) {
        this.drawTransformHandles(ctx, screenX, screenY, screenW, screenH);
      }

      ctx.restore();
    });
  }

  drawBadge(ctx, box, cls, x, y) {
    const isPending = box.verification_status === 'PENDING_REVIEW';
    const conf = box.confidence ? ` ${Math.round(box.confidence * 100)}%` : '';
    const text = `${isPending ? '⚡ ' : ''}${cls.name}${conf}`;

    ctx.font = '11px monospace';
    const textW = ctx.measureText(text).width;
    const badgeH = 18;
    const badgeW = textW + 12;

    // Плашка под текст
    ctx.fillStyle = isPending ? '#854d0e' : '#1e1e24'; // янтарный для pending
    ctx.fillRect(x, y - badgeH, badgeW, badgeH);

    // Текст
    ctx.fillStyle = '#ffffff';
    ctx.fillText(text, x + 6, y - 5);
  }

  drawTransformHandles(ctx, x, y, w, h) {
    ctx.fillStyle = '#ffffff';
    ctx.strokeStyle = '#000000';
    ctx.lineWidth = 1;
    const size = 6;

    const points = [
      { x, y }, { x: x + w / 2, y }, { x: x + w, y },
      { x: x + w, y: y + h / 2 }, { x: x + w, y: y + h },
      { x: x + w / 2, y: y + h }, { x, y: y + h }, { x, y: y + h / 2 }
    ];

    points.forEach(p => {
      ctx.fillRect(p.x - size / 2, p.y - size / 2, size, size);
      ctx.strokeRect(p.x - size / 2, p.y - size / 2, size, size);
    });
  }

  bindEvents() {
    // Зум колесиком к курсору
    this.canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      const zoomFactor = 1.1;
      const curZoom = store.get('zoom');
      const newZoom = e.deltaY < 0 ? curZoom * zoomFactor : curZoom / zoomFactor;

      if (newZoom < 0.1 || newZoom > 15) return;

      const rect = this.canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      const pan = store.get('pan');

      store.set('pan', {
        x: mouseX - (mouseX - pan.x) * (newZoom / curZoom),
        y: mouseY - (mouseY - pan.y) * (newZoom / curZoom)
      });
      store.set('zoom', newZoom);
    });

    // Рисование нового бокса (Drag-to-create)
    this.canvas.addEventListener('mousedown', (e) => {
      if (store.get('mode') !== 'DRAW') return;
      this.isDrawing = true;
      this.drawStart = this.clientToImageCoords(e.clientX, e.clientY);
    });

    window.addEventListener('mouseup', (e) => {
      if (!this.isDrawing) return;
      this.isDrawing = false;
      const drawEnd = this.clientToImageCoords(e.clientX, e.clientY);

      const w = drawEnd.x - this.drawStart.x;
      const h = drawEnd.y - this.drawStart.y;

      // Фильтр от случайных микрокликов (минимум 5px)
      if (Math.abs(w) > 5 && Math.abs(h) > 5) {
        const normBBox = this.toNormalizedBBox(this.drawStart.x, this.drawStart.y, w, h);
        
        // Ручная рамка сразу получает статус VERIFIED
        const newBox = {
          id: crypto.randomUUID(),
          class_id: store.get('activeClassId'),
          ...normBBox,
          source: 'MANUAL',
          verification_status: 'VERIFIED',
          confidence: 1.0
        };

        const list = [...store.get('annotations'), newBox];
        store.set('annotations', list);
        store.set('selectedBoxId', newBox.id);
        store.set('hasUnsavedChanges', true);
      }
    });
  }
}
```

---

## 7. Интерактивные фичи Active Learning & Keypoints

### 7.1. Механика: Keypoint Matching Transfer (`Ctrl+C` $\to$ `Ctrl+Shift+V`)

Копирование бокса с текущего кадра и перенос на новый кадр через поиск особых точек (LightGlue / SuperPoint).

```javascript
// js/components/keypointTransfer.js
import { store } from '../store.js';
import { api } from '../api.js';

export function initKeypointShortcuts() {
  window.addEventListener('keydown', async (e) => {
    // 1. Копирование выделенного бокса (Ctrl+C / Cmd+C)
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c' && !e.shiftKey) {
      const selectedId = store.get('selectedBoxId');
      const box = store.get('annotations').find(b => b.id === selectedId);
      
      if (box) {
        store.set('clipboardBox', {
          box,
          sourceImageId: store.get('currentImage').id
        });
        
        // Показать toast уведомление
        const toast = document.getElementById('clipboard-toast');
        toast.classList.remove('hidden');
        setTimeout(() => toast.classList.add('hidden'), 4000);
      }
    }

    // 2. Вставка с вызовом матчинга ключевых точек (Ctrl+Shift+V)
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'v') {
      e.preventDefault();
      const clipboard = store.get('clipboardBox');
      const targetImage = store.get('currentImage');

      if (!clipboard || clipboard.sourceImageId === targetImage.id) return;

      // Визуальный индикатор поиска точек
      document.body.style.cursor = 'wait';

      try {
        // Запрос к бэкенду: экстракция точек и гомография
        const response = await api.post('/matching/propagate-box', {
          source_image_id: clipboard.sourceImageId,
          target_image_id: targetImage.id,
          source_box: clipboard.box
        });

        // Создаем полученный бокс ОБЯЗАТЕЛЬНО со статусом PENDING_REVIEW
        const propagatedBox = {
          id: crypto.randomUUID(),
          class_id: clipboard.box.class_id,
          ...response.projected_bbox, // { x_center, y_center, width, height }
          source: 'KEYPOINT_PROPAGATION',
          verification_status: 'PENDING_REVIEW',
          confidence: response.match_confidence // процент совпадения ключевых точек
        };

        store.set('annotations', [...store.get('annotations'), propagatedBox]);
        store.set('selectedBoxId', propagatedBox.id);
        store.set('hasUnsavedChanges', true);

      } catch (err) {
        alert('Не удалось сопоставить ключевые точки: объект сильно деформирован или скрыт');
      } finally {
        document.body.style.cursor = 'default';
      }
    }
  });
}
```

---

### 7.2. Механика: Экспресс-верификация предсказаний (HITL Bar)

Позволяет разметчику за доли секунды валидировать работу нейросети клавишей `Space`:

```javascript
// js/components/reviewBar.js
import { store } from '../store.js';

export function initReviewBar() {
  const btnApproveAll = document.getElementById('btn-approve-all');
  const btnRejectAll = document.getElementById('btn-reject-all');
  const pendingCountEl = document.getElementById('pending-count');

  // Обновление счетчика неподтвержденных рамок
  store.addEventListener('change:annotations', (e) => {
    const annotations = e.detail;
    const pending = annotations.filter(b => b.verification_status === 'PENDING_REVIEW');
    pendingCountEl.innerText = pending.length;

    const actionsContainer = document.getElementById('ai-verification-actions');
    if (pending.length === 0) {
      actionsContainer.classList.add('opacity-40', 'pointer-events-none');
    } else {
      actionsContainer.classList.remove('opacity-40', 'pointer-events-none');
    }
  });

  // Действие: Подтвердить все рамки на текущем кадре
  const approveAll = () => {
    const list = store.get('annotations').map(box => {
      if (box.verification_status === 'PENDING_REVIEW') {
        return { ...box, verification_status: 'VERIFIED' };
      }
      return box;
    });

    store.set('annotations', list);
    store.set('hasUnsavedChanges', true);
  };

  btnApproveAll.addEventListener('click', approveAll);

  // Горячая клавиша: Пробел подтверждает все гипотезы и переходит дальше
  window.addEventListener('keydown', (e) => {
    if (e.code === 'Space' && store.get('mode') === 'SELECT') {
      e.preventDefault();
      approveAll();
    }
  });
}
```

---

## 8. Полная матрица клавиатурного управления (Keyboard-First UX)

Приложение спроектировано так, чтобы разметчик мог вообще не убирать руки с клавиатуры:

| Клавиша | Контекст | Действие |
| :--- | :--- | :--- |
| `W` | Глобально | Переключить режим на рисование рамки (`DRAW`) |
| `V` | Глобально | Переключить режим на выбор/трансформацию (`SELECT`) |
| `Space` | Режим верификации | **Подтвердить все** автоматические рамки кадра (`VERIFIED`) |
| `R` | Режим верификации | **Отклонить все** автоматические рамки кадра |
| `D` или `→` | Навигация | Сохранить разметку и перейти к **следующему кадру** |
| `A` или `←` | Навигация | Сохранить разметку и перейти к **предыдущему кадру** |
| `Ctrl + C` | Выбран бокс | Скопировать геометрию бокса в буфер переноса точек |
| `Ctrl + Shift + V` | Кадр-акцептор | **Запустить Keypoint Transfer** (LightGlue сопоставление) |
| `1` .. `9` | Любой режим | Выбрать активный класс / Сменить класс выделенного бокса |
| `Delete` / `Backspace` | Выбран бокс | Удалить бокс |
| `F` | Холст | Центрировать изображение и сбросить зум (Fit to Screen) |

---

## 9. План развертывания прототипа

1. Создать каталог `/frontend`.
2. Поместить `index.html` с подключенным CDN TailwindCSS и Lucide Icons.
3. Добавить модули `store.js`, `canvas.js`, `api.js` и `keypointTransfer.js`.
4. Запустить статический сервер:
   ```bash
   # Например, через Python или live-server
   cd frontend && python3 -m http.server 3000
   ```
5. Фронтенд готов к работе и прямому взаимодействию с FastAPI бэкендом.