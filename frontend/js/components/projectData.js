import { api } from "../api.js?v=project-data-20261022d";
import { store } from "../store.js";
import { escapeHtml as esc } from "../utils/dom.js";

const SECTIONS = [["images", "Изображения"], ["statistics", "Статистика"], ["cameras", "Камеры проекта"], ["imports", "Импорт и модели"], ["classes", "Классы"]];
const STATUS = { UNANNOTATED: "Без разметки", REQUIRES_REVIEW: "На проверку", REQUIRES_RECHECK: "Перепроверить", VERIFIED: "Проверено", AUTO_VERIFIED: "Автопроверено", REJECTED: "Отклонено" };
const SOURCE = { MANUAL_UPLOAD: "Загрузка", STREAM_INGEST: "Сбор", DATASET_IMPORT: "Датасет" };
const JOB_STATUS = { PREVIEW: "Проверен · ждёт запуска", QUEUED: "В очереди", RUNNING: "Импортируется", COMPLETED: "Завершён", FAILED: "Ошибка", CANCELLED: "Остановлен", ROLLED_BACK: "Изображения в корзине" };
const fmt = (n) => Number(n || 0).toLocaleString("ru-RU");
const button = (action, label, cls = "", attrs = "") => `<button type="button" class="pd-btn ${cls}" data-action="${action}" ${attrs}>${label}</button>`;
const option = (v, text, current) => `<option value="${esc(String(v))}" ${String(current) === String(v) ? "selected" : ""}>${esc(String(text))}</option>`;

export function initDataHub({ onOpenImage, onStartAnnotate, onError }) {
  const root = document.getElementById("project-data-root");
  let projectId, section = "images", classes = [], cameras = [], versions = [], stats = null;
  let page = { items: [], total: 0, offset: 0, limit: 24 }, filters = {}, selected = new Set(), allMatching = false;
  let layout = "grid", dense = false, overlays = true, sequence = 0, jobs = [], pollTimer = null;
  let modalRoot = null, viewerIndex = -1, importJob = null, savedViews = [], searchTimer;
  let refreshSequence = 0, sectionSequence = 0;
  const get = (s, host = root) => host?.querySelector(s);
  const all = (s, host = root) => [...(host?.querySelectorAll(s) || [])];
  const error = (err) => onError?.(err.message || String(err));
  const run = (fn) => Promise.resolve().then(fn).catch(error);
  const dataKey = () => `lblstdio:data:views:${projectId}`;
  const cameraName = (id) => cameras.find(c => c.id === id)?.name || (id ? "Удалённый источник" : "Загрузка файлов");
  const cls = (id) => classes.find(c => c.id === id);
  const classSelect = (current, placeholder = "Все классы") => option("", placeholder, current) + classes.map(c => option(c.id, c.name, current)).join("");

  function closeModal() { modalRoot?.remove(); modalRoot = null; viewerIndex = -1; }
  function modal(title, body, footer = "", wide = false) {
    closeModal();
    modalRoot = document.createElement("div");
    modalRoot.className = "pd-modal-backdrop";
    modalRoot.innerHTML = `<section class="pd-modal ${wide ? "pd-wide" : ""}" role="dialog" aria-modal="true" aria-label="${esc(title)}"><header><h2>${esc(title)}</h2>${button("close", "✕", "", 'aria-label="Закрыть"')}</header><div class="pd-modal-body">${body}</div>${footer ? `<footer>${footer}</footer>` : ""}</section>`;
    document.body.append(modalRoot);
    modalRoot.addEventListener("click", e => { if (e.target === modalRoot || e.target.closest('[data-action="close"]')) closeModal(); });
    get('[data-action="close"]', modalRoot)?.focus();
    return modalRoot;
  }

  function header() {
    const titles = { images: ["Библиотека изображений", "Находите нужные кадры, проверяйте разметку и готовьте данные к обучению."], statistics: ["Состояние данных", "Баланс классов, источники и готовность датасета."], cameras: ["Камеры проекта", "Источники связаны с общим каталогом. Один источник доступен нескольким проектам."], imports: ["Импорт и модели", "Изображения, размеченные датасеты и веса моделей — с проверкой классов до запуска."], classes: ["Классы проекта", "Единый словарь для данных, разметки и моделей."] };
    return `<div class="pd-heading"><div><div class="pd-eyebrow">${esc(store.get("currentProject")?.name || "Проект")} / Данные</div><h1>${titles[section][0]}</h1><p>${titles[section][1]}</p></div><div class="pd-actions">${section === "images" ? button("statistics", "Статистика") + button("import-images", "+ Загрузить", "pd-primary") : section === "cameras" ? button("add-camera", "+ Добавить камеру", "pd-primary") : section === "classes" ? button("add-classes", "+ Добавить классы", "pd-primary") : ""}</div></div>`;
  }
  function renderShell() {
    root.innerHTML = `<div class="pd-shell"><nav class="pd-nav" aria-label="Разделы данных"><div class="pd-nav-title">ДАННЫЕ ПРОЕКТА</div>${SECTIONS.map(([id, name]) => `<button data-section="${id}" class="${section === id ? "active" : ""}">${name}${id === "classes" ? `<small>${classes.length}</small>` : ""}</button>`).join("")}<a href="#/streams">↗ Центр сбора</a><div class="pd-nav-note">${store.get("currentProject")?.task_type === "CLASSIFICATION" ? "Классификация" : "Детекция объектов"}<br>Классы настраиваются здесь; в разметке — назначаются изображениям.</div></nav><main class="pd-main">${header()}<div id="pd-content"></div></main></div><div id="pd-announcement" role="status" aria-live="polite"></div>`;
  }
  function showMessage(text) { const host = get("#pd-announcement"); if (host) { host.textContent = text; host.className = "pd-toast"; setTimeout(() => { host.className = ""; host.textContent = ""; }, 4500); } }
  function go(next) {
    if (store.get("projectTab") !== "data") {
      location.hash = `/projects/${projectId}/data?section=${next}`;
      return;
    }
    sequence++; sectionSequence++;
    clearTimeout(searchTimer);
    section = next;
    history.replaceState(null, "", `${location.pathname}${location.search}#/projects/${projectId}/data?section=${next}`);
    renderShell();
    return loadSection();
  }
  function metric(label, value, action = "", note = "") { return `<${action ? 'button type="button"' : "div"} class="pd-metric" ${action ? `data-action="${action}"` : ""}><span>${label}</span><strong>${fmt(value)}</strong><small>${note}</small></${action ? "button" : "div"}>`; }
  function metrics() {
    const counts = Object.fromEntries((stats?.statuses || []).map(r => [r.name, r.count]));
    return `<div class="pd-metrics">${metric("Изображений", stats?.total, "all-images")}${metric("Без разметки", counts.UNANNOTATED, "unannotated")}${metric("Ждут проверки", (counts.REQUIRES_REVIEW || 0) + (counts.REQUIRES_RECHECK || 0), "review")}${metric("Подтверждено", (counts.VERIFIED || 0) + (counts.AUTO_VERIFIED || 0), "verified")}${metric("Классов", classes.length, "classes")}</div>`;
  }
  function selectFilter(key, label, options) { return `<label class="pd-field">${label}<select data-filter="${key}">${option("", "Все", filters[key])}${options.map(([v, n]) => option(v, n, filters[key])).join("")}</select></label>`; }
  function numberFilter(key, label, max = "") { return `<label class="pd-field">${label}<input data-filter="${key}" type="number" min="0" ${max ? `max="${max}"` : ""} ${(key.includes("conf") || key.includes("area")) ? 'step="0.05"' : 'step="1"'} value="${esc(String(filters[key] ?? ""))}"></label>`; }
  function classFilters() {
    const ids = String(filters.class_id || "").split(",");
    return `<label class="pd-field">Найти класс<input id="pd-filter-class-search" placeholder="Название класса…"></label><div class="pd-class-filters">${classes.map(c => `<label class="pd-check" data-class-filter-name="${esc(c.name.toLocaleLowerCase())}"><input type="checkbox" data-class-filter="${c.id}" ${ids.includes(c.id) ? "checked" : ""}>${esc(c.name)}</label>`).join("") || '<span class="pd-muted">Классов пока нет</span>'}</div><p class="pd-muted">Любой из выбранных классов.</p>`;
  }
  function qualityFilters() {
    return `${selectFilter("quality", "Качество", [["dark", "Темно: яркость < 50 / 255"], ["blur", "Возможное размытие"]])}<p class="pd-muted">Проанализировано ${fmt(stats?.analyzed)} кадров. Запуск анализа — в статистике.</p><div class="pd-pair">${numberFilter("min_area", "Площадь рамки от", "1")}${numberFilter("max_area", "До", "1")}</div><p class="pd-muted">Доля площади кадра 0–1. Найдётся рамка в указанном диапазоне.</p>${selectFilter("orientation", "Ориентация", [["landscape", "Горизонтальная"], ["portrait", "Вертикальная"], ["square", "Квадрат"]])}${selectFilter("format", "Формат файла", [["jpg", "JPEG"], ["png", "PNG"], ["webp", "WebP"]])}`;
  }
  function filtersPanel() {
    return `<aside class="pd-filters"><div class="pd-row"><h3>Фильтры</h3>${button("reset-filters", "Сбросить", "pd-link")}</div><p class="pd-muted">Условия разных групп применяются вместе.</p><details open><summary>Разметка и классы</summary><div class="pd-filter-body">${Object.entries(STATUS).map(([id, name]) => `<label class="pd-check"><input type="checkbox" data-status="${id}" ${String(filters.status || "").split(",").includes(id) ? "checked" : ""}>${name}</label>`).join("")}${classFilters()}${selectFilter("annotation_source", "Кто разметил", [["MANUAL", "Человек / импорт"], ["MODEL_PREDICTION", "Модель"], ["KEYPOINT_PROPAGATION", "Перенос разметки"]])}<label class="pd-check"><input type="checkbox" data-boolean="background" ${filters.background ? "checked" : ""}>Только фон</label><div class="pd-pair">${numberFilter("min_objects", "Объектов от")}${numberFilter("max_objects", "До")}</div><div class="pd-pair">${numberFilter("min_conf", "Уверенность от", "1")}${numberFilter("max_conf", "До", "1")}</div><p class="pd-muted">Уверенность 0–1: только предсказания модели.</p></div></details><details open><summary>Источник и дата</summary><div class="pd-filter-body">${selectFilter("stream_source_id", "Камера", cameras.map(c => [c.id, c.name]))}${selectFilter("source_type", "Тип источника", Object.entries(SOURCE))}<label class="pd-field">С даты<input type="date" data-filter="after" value="${esc(filters.after || "")}"></label><label class="pd-field">До даты (не включая)<input type="date" data-filter="before" value="${esc(filters.before || "")}"></label><label class="pd-field">Тег<input data-filter="tag" value="${esc(filters.tag || "")}" placeholder="Например, ночь"></label></div></details><details><summary>Датасет и качество</summary><div class="pd-filter-body">${qualityFilters()}${selectFilter("split", "Раздел", [["train", "Train"], ["valid", "Validation"], ["test", "Test"]])}${selectFilter("version_id", "Версия", versions.map(v => [v.id, v.name || `v${v.version_number}`]))}<div class="pd-pair">${numberFilter("min_width", "Ширина от")}${numberFilter("min_height", "Высота от")}</div><label class="pd-check"><input type="checkbox" data-boolean="duplicates" ${filters.duplicates ? "checked" : ""}>Одинаковые pHash</label><p class="pd-muted">Сравниваются сохранённые хеши. Неанализированные изображения не входят в результат.</p></div></details><label class="pd-check pd-trash"><input type="checkbox" data-boolean="trash" ${filters.trash ? "checked" : ""}>Корзина · ${fmt(stats?.trash)}</label>${button("apply-filters", "Применить фильтры", "pd-primary pd-full")}</aside>`;
  }
  function savedViewButtons() { return `<div class="pd-saved">${button("preset-all", "Все")}${button("preset-review", "На проверку")}${button("preset-uncertain", "Уверенность < 50%")}${savedViews.map((v, i) => `<span class="pd-saved-item">${button("load-view", esc(v.name), "", `data-index="${i}"`)}${button("delete-view", "×", "pd-link", `data-index="${i}" aria-label="Удалить сохранённый фильтр"`)}</span>`).join("")}${button("save-view", "+ Сохранить фильтр")}</div>`; }
  function boxes(item) {
    if (!overlays) return "";
    return `<svg class="pd-boxes" viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true">${item.annotations.filter(b => b.verification_status !== "REJECTED").map(b => `<rect x="${(b.x_center-b.width/2)*1000}" y="${(b.y_center-b.height/2)*1000}" width="${b.width*1000}" height="${b.height*1000}" fill="none" stroke="${esc(cls(b.class_id)?.color_hex || "#a8b1ff")}" stroke-width="2" vector-effect="non-scaling-stroke"/>`).join("")}</svg>`;
  }
  function card(item, i) {
    const label = item.label ? cls(item.label.class_id)?.name || "Класс удалён" : `${item.annotations.length} объектов`;
    return `<article class="pd-image-card ${selected.has(item.id) || allMatching ? "selected" : ""}"><label class="pd-card-check"><input type="checkbox" data-select="${item.id}" ${selected.has(item.id) || allMatching ? "checked" : ""} aria-label="Выбрать ${esc(item.file_name)}"></label><button class="pd-image-open" data-open="${i}" aria-label="Просмотр ${esc(item.file_name)}"><div class="pd-thumb" style="aspect-ratio:${item.width}/${item.height}"><img src="${api.thumbnailUrl(item.id)}" width="480" height="360" loading="lazy" decoding="async" alt="${esc(item.file_name)}">${boxes(item)}<span class="pd-status ${item.status === "UNANNOTATED" ? "empty" : item.status.includes("REQUIRES") ? "warning" : ""}">${esc(STATUS[item.status] || item.status)}</span>${item.confidence != null ? `<span class="pd-confidence">${Math.round(item.confidence*100)}%</span>` : ""}</div><div class="pd-card-info"><strong title="${esc(item.file_name)}">${esc(item.file_name)}</strong><span>${esc(label)} · ${item.width} × ${item.height}</span><small>${esc(cameraName(item.stream_source_id))} · ${esc(item.split)}</small>${item.tags.length ? `<small>${item.tags.map(t => `#${esc(t)}`).join(" ")}</small>` : ""}</div></button></article>`;
  }
  function renderImages() {
    const content = get("#pd-content");
    if (!content) return;
    content.innerHTML = `${metrics()}${savedViewButtons()}<div class="pd-library">${filtersPanel()}<section class="pd-results"><div class="pd-toolbar"><input id="pd-search" type="search" placeholder="Найти по имени файла…" value="${esc(filters.q || "")}"><select id="pd-sort" aria-label="Порядок">${[["newest", "Сначала новые"], ["oldest", "Сначала старые"], ["uncertainty", "Низкая уверенность"], ["objects", "Больше объектов"], ["name", "По имени"]].map(([v, n]) => option(v, n, filters.sort || "newest")).join("")}</select>${button("toggle-layout", layout === "grid" ? "☷ Список" : "▦ Сетка")}${button("toggle-density", dense ? "Крупнее" : "Компактнее")}</div><div class="pd-result-line"><span>Найдено <strong>${fmt(page.total)}</strong>${Object.keys(filters).filter(k => !["sort", "q"].includes(k)).length ? ` · фильтров: ${Object.keys(filters).filter(k => !["sort", "q"].includes(k)).length}` : ""}</span><label class="pd-check"><input type="checkbox" id="pd-overlays" ${overlays ? "checked" : ""}>Рамки</label></div><div class="pd-selection"><label class="pd-check"><input type="checkbox" id="pd-select-page" ${page.items.length && page.items.every(i => selected.has(i.id) || allMatching) ? "checked" : ""}>Страница</label><span>Выбрано: ${fmt(allMatching ? page.total : selected.size)}</span>${button("select-matching", `Все найденные (${fmt(page.total)})`, "pd-link")}${button("clear-selection", "Снять", "pd-link")}</div>${selected.size || allMatching ? `<div class="pd-bulk">${button("bulk-tag", "Добавить тег")}${filters.trash ? button("bulk-restore", "Восстановить", "pd-primary") : button("bulk-review", "На перепроверку") + button("bulk-trash", "В корзину", "pd-danger")}</div>` : ""}<div class="pd-image-grid ${dense ? "pd-dense" : ""} ${layout === "list" ? "pd-list" : ""}">${page.items.map(card).join("") || `<div class="pd-empty"><strong>${filters.trash ? "Корзина пуста" : "Нет изображений"}</strong><p>${Object.keys(filters).length ? "Попробуйте изменить фильтры." : "Загрузите изображения или начните сбор с камеры."}</p>${button("reset-filters", "Сбросить фильтры")}${button("import-images", "Загрузить изображения", "pd-primary")}</div>`}</div><div class="pd-pagination"><span>${page.total ? `${fmt(page.offset+1)}–${fmt(Math.min(page.offset+page.limit, page.total))}` : "0"} из ${fmt(page.total)}</span><select id="pd-page-size" aria-label="Изображений на странице">${[24, 48, 96].map(n => option(n, `${n} на странице`, page.limit)).join("")}</select>${button("previous-page", "←", "", `${page.offset <= 0 ? "disabled" : ""} aria-label="Предыдущая страница"`)}<span>${Math.floor(page.offset/page.limit)+1} / ${Math.max(1, Math.ceil(page.total/page.limit))}</span>${button("next-page", "→", "", `${page.offset+page.limit >= page.total ? "disabled" : ""} aria-label="Следующая страница"`)}</div></section></div>`;
    get("#pd-search")?.addEventListener("input", e => { clearTimeout(searchTimer); const val = e.target.value; searchTimer = setTimeout(() => { filters.q = val; resetPage(); run(loadPage); }, 350); });
    get("#pd-filter-class-search")?.addEventListener("input", e => {
      const term = e.target.value.trim().toLocaleLowerCase();
      all("[data-class-filter-name]").forEach(label => { label.hidden = !label.dataset.classFilterName.includes(term); });
    });
  }
  function resetPage() { page.offset = 0; selected.clear(); allMatching = false; }
  async function loadPage() {
    const seq = ++sequence, id = projectId;
    root.setAttribute("aria-busy", "true");
    try {
      const result = await api.queryProjectData(id, { ...filters, limit: page.limit, offset: page.offset });
      if (seq !== sequence || id !== projectId || section !== "images") return;
      page = result;
      renderImages();
    } finally { if (seq === sequence) root.removeAttribute("aria-busy"); }
  }
  function readFilters() {
    all("[data-filter]").forEach(input => { const k = input.dataset.filter; if (input.value === "") delete filters[k]; else filters[k] = input.type === "number" ? Number(input.value) : input.value; });
    const statuses = all("[data-status]:checked").map(e => e.dataset.status);
    if (statuses.length) filters.status = statuses.join(","); else delete filters.status;
    const classIds = all("[data-class-filter]:checked").map(e => e.dataset.classFilter);
    if (classIds.length) filters.class_id = classIds.join(","); else delete filters.class_id;
    all("[data-boolean]").forEach(input => { if (input.checked) filters[input.dataset.boolean] = true; else delete filters[input.dataset.boolean]; });
  }
  async function refreshStats() { stats = await api.projectDataStatistics(projectId); }
  async function loadSection() {
    const seq = sectionSequence, id = projectId, target = section;
    if (section === "images") return loadPage();
    const current = () => seq === sectionSequence && projectId === id && section === target;
    if (section === "statistics") { const result = await api.projectDataStatistics(id); if (!current()) return; stats = result; renderStatistics(); }
    if (section === "cameras") { const result = await api.projectCameras(id); if (!current()) return; cameras = result; renderCameras(); }
    if (section === "imports") { const result = await api.listDataImports(id); if (!current()) return; jobs = result; renderImports(); startPolling(); }
    if (section === "classes") renderClasses();
  }
  function bar(name, n, total, color = "#a8b1ff") { return `<div class="pd-bar-row"><div><span>${esc(name)}</span><strong>${fmt(n)}</strong></div><div class="pd-bar"><i style="width:${total ? Math.max(1, n/total*100) : 0}%;background:${color}"></i></div></div>`; }
  function renderStatistics() {
    get("#pd-content").innerHTML = `${metrics()}<div class="pd-two-columns"><section class="pd-panel"><h2>Готовность к разметке</h2>${(stats.statuses || []).map(r => bar(STATUS[r.name] || r.name, r.count, stats.total)).join("") || '<p class="pd-muted">Нет данных</p>'}</section><section class="pd-panel"><h2>Баланс классов</h2><p class="pd-muted">Объектов / изображений с классом</p>${classes.map(c => { const row = stats.classes.find(r => r.id === c.id); return bar(`${c.name} · ${fmt(row?.images)} кадров`, row?.objects || 0, Math.max(1, ...stats.classes.map(r => r.objects)), c.color_hex); }).join("") || '<p class="pd-muted">Добавьте классы проекта</p>'}</section><section class="pd-panel"><h2>Источники изображений</h2>${stats.sources.map(r => bar(cameraName(r.name), r.count, stats.total, "#79cbb2")).join("")}</section><section class="pd-panel"><h2>Разделы датасета</h2>${stats.splits.map(r => bar(r.name, r.count, stats.total)).join("")}<div class="pd-notice">Train — обучение, Validation — оценка в процессе обучения, Test — независимая проверка.</div></section><section class="pd-panel"><h2>Поступление по дням</h2><div class="pd-chart">${stats.days.slice(-30).map(r => `<div title="${esc(r.name)}: ${r.count}"><i style="height:${Math.max(3, r.count/Math.max(1, ...stats.days.map(d => d.count))*115)}px"></i><small>${esc(r.name?.slice(5) || "")}</small><span>${fmt(r.count)}</span></div>`).join("")}</div></section><section class="pd-panel"><h2>Качество и пересечения</h2><div class="pd-check-item">Похожие копии с одинаковым pHash <strong>${fmt(stats.duplicates)}</strong></div><div class="pd-check-item">Группы копий между разделами <strong>${fmt(stats.leakage_groups)}</strong></div><p class="pd-muted">Проверка использует сохранённые pHash. Проанализировано: ${fmt(stats.analyzed)} из ${fmt(stats.total)}. Размытие и темнота — ориентировочные признаки; проверьте кадры визуально.</p>${button("find-duplicates", "Показать копии")}${button("quality-scan", "Анализ качества")}</section></div>`;
  }
  function renderCameras() {
    get("#pd-content").innerHTML = `<div class="pd-notice">Добавление связывает существующую камеру с проектом. Сбор запускается отдельно в Центре сбора, с выбором проекта назначения.</div><div class="pd-camera-grid">${cameras.map(c => `<section class="pd-panel"><div class="pd-row"><span class="pd-camera-icon">◉</span><span class="pd-badge ${c.is_active ? "pd-good" : ""}">${c.state === "error" ? "Ошибка источника" : c.state === "reconnecting" ? "Переподключение" : c.state === "running" ? "Сбор идёт" : "Не собирает"}</span></div><h2>${esc(c.name)}</h2><p class="pd-muted">${esc(c.source_type)} · ${c.owned ? "Источник этого проекта" : "Связан из другого проекта"}</p><div class="pd-actions">${button("camera-images", "Изображения", "", `data-id="${c.id}"`)}${button("camera-collect", "Настроить сбор", "pd-primary", `data-id="${c.id}"`)}${!c.owned ? button("unlink-camera", "Отвязать", "pd-link", `data-id="${c.id}"`) : ""}</div></section>`).join("") || `<div class="pd-empty"><strong>Камеры ещё не добавлены</strong><p>Подключите RTSP, веб-камеру, видео или выберите источник из другого проекта.</p>${button("add-camera", "+ Добавить камеру", "pd-primary")}</div>`}</div>`;
  }
  function renderImports() {
    get("#pd-content").innerHTML = `<div class="pd-import-cards">${[["images", "Изображения", "Фото или папка. Разметку можно добавить позже."], ["dataset", "Размеченный датасет", "YOLO · COCO · папки классов. Имена классов определяются из данных."], ["model", "Модель YOLO", "Веса .pt. Тип задачи и словарь классов проверяются до импорта."]].map(([kind, title, text]) => `<section class="pd-panel"><div class="pd-eyebrow">ИМПОРТ</div><h2>${title}</h2><p>${text}</p>${button(`import-${kind}`, "Выбрать файлы →", "pd-primary")}</section>`).join("")}</div><section class="pd-panel"><div class="pd-row"><h2>История импорта</h2>${button("refresh-imports", "Обновить")}</div><div id="pd-import-history">${historyMarkup()}</div></section><div class="pd-notice">Импорт выполняется в фоне. Можно переключать вкладки. Отмена завершённого импорта перемещает его изображения в корзину; классы сохраняются.</div>`;
  }
  function historyMarkup() {
    return jobs.length ? `<div class="pd-table-wrap"><table><thead><tr><th>Файлы / формат</th><th>Состояние</th><th>Прогресс</th><th>Действия</th></tr></thead><tbody>${jobs.map(j => `<tr><td><strong>${esc(j.name)}</strong><small>${esc(j.summary.format || j.kind)} · ${new Date(j.created_at).toLocaleString("ru-RU")}</small></td><td><span class="pd-badge ${j.status === "FAILED" ? "pd-bad" : j.status === "COMPLETED" ? "pd-good" : ""}">${esc(JOB_STATUS[j.status] || j.status)}</span>${j.error ? `<p class="pd-error">${esc(j.error)}</p>` : ""}</td><td>${fmt(j.processed)} / ${fmt(j.total)}<progress max="${j.total || 1}" value="${j.processed}"></progress></td><td>${j.status === "PREVIEW" ? button("resume-import", "Продолжить", "", `data-id="${j.id}"`) : ""}${["RUNNING", "QUEUED", "PREVIEW"].includes(j.status) ? button("cancel-import", "Остановить", "pd-link", `data-id="${j.id}"`) : ["images", "dataset"].includes(j.kind) && j.processed > 0 && j.status !== "ROLLED_BACK" ? button("rollback-import", "В корзину", "pd-link", `data-id="${j.id}"`) : ""}</td></tr>`).join("")}</tbody></table></div>` : '<div class="pd-empty">История пока пуста</div>';
  }
  function startPolling() {
    clearTimeout(pollTimer);
    if (!jobs.some(j => ["RUNNING", "QUEUED"].includes(j.status))) return;
    const id = projectId;
    pollTimer = setTimeout(async () => {
      if (id !== projectId) return;
      try {
        jobs = await api.listDataImports(id);
        if (section === "imports" && store.get("projectTab") === "data") { const host = get("#pd-import-history"); if (host) host.innerHTML = historyMarkup(); }
        if (!jobs.some(j => ["RUNNING", "QUEUED"].includes(j.status))) {
          await refreshStats();
          classes = await api.listClasses(id); store.set("classes", classes);
          const counter = get('[data-section="classes"] small'); if (counter) counter.textContent = String(classes.length);
          if (section === "images" && store.get("projectTab") === "data") await loadPage();
        }
      } catch (err) { error(err); }
      startPolling();
    }, 1800);
  }
  function renderClasses() {
    get("#pd-content").innerHTML = `<div class="pd-notice">Названия и индексы проекта едины для всех данных. При импорте индексы модели и датасета сопоставляются с этим словарём. Переименование сохраняет связь с разметкой.</div><section class="pd-panel"><div class="pd-row"><h2>Словарь · ${classes.length}</h2><div class="pd-actions">${button("import-dictionary", "Загрузить словарь")}${button("export-dictionary", "Скачать classes.txt")}</div></div><div class="pd-table-wrap"><table><thead><tr><th>Индекс</th><th>Класс</th><th>Объекты / кадры</th><th>Действия</th></tr></thead><tbody>${classes.map(c => { const counts = stats?.classes?.find(r => r.id === c.id); return `<tr><td><code>${c.index_id}</code></td><td><span class="pd-color" style="background:${esc(c.color_hex)}"></span>${esc(c.name)}</td><td>${fmt(counts?.objects)} / ${fmt(counts?.images)}</td><td>${button("rename-class", "Переименовать", "pd-link", `data-id="${c.id}"`)}${button("delete-class", "Удалить", "pd-link pd-danger", `data-id="${c.id}"`)}</td></tr>`; }).join("")}</tbody></table></div>${!classes.length ? `<div class="pd-empty">Создайте классы вручную или загрузите размеченный датасет / модель.</div>` : ""}</section>`;
  }
  async function syncClasses() { classes = await api.listClasses(projectId); store.set("classes", classes); await refreshStats(); }
  function addClassesModal(initial = "") {
    modal("Добавить классы", `<p class="pd-muted">По одному названию на строку. Совпадающие имена будут пропущены.</p><label class="pd-field">Названия<textarea id="pd-class-names" rows="9" placeholder="Автомобиль\nЧеловек\nВелосипед">${esc(initial)}</textarea></label><div id="pd-class-result" role="status"></div>`, button("save-classes", "Добавить классы", "pd-primary"));
    get('[data-action="save-classes"]', modalRoot).onclick = () => run(async () => {
      const names = get("#pd-class-names", modalRoot).value.split(/\r?\n/).map(n => n.trim()).filter(Boolean);
      if (!names.length) throw new Error("Введите названия классов");
      const unique = [...new Set(names.map(n => n.toLocaleLowerCase("ru-RU")))];
      const existing = new Set(classes.map(c => c.name.toLocaleLowerCase("ru-RU")));
      let added = 0, skipped = names.length - unique.length;
      const btn = get('[data-action="save-classes"]', modalRoot); btn.disabled = true;
      try {
        for (const key of unique) {
          if (existing.has(key)) { skipped++; continue; }
          const name = names.find(n => n.toLocaleLowerCase("ru-RU") === key);
          await api.createClass(projectId, name, ["#8B5CF6", "#10B981", "#F59E0B", "#3B82F6", "#EC4899"][classes.length % 5]); added++; existing.add(key);
        }
        await syncClasses(); closeModal(); renderShell(); renderClasses(); showMessage(`Добавлено: ${added}. Повторов пропущено: ${skipped}.`);
      } finally { btn.disabled = false; }
    });
  }
  function filePicker({ multiple = true, accept = "", folder = false }, callback) {
    const input = document.createElement("input"); input.type = "file"; input.multiple = multiple; input.accept = accept;
    if (folder) input.setAttribute("webkitdirectory", "");
    input.onchange = () => { if (input.files.length) run(() => callback([...input.files])); };
    input.click();
  }
  function importModal(kind) {
    modal("Импорт · выбор файлов", `<div class="pd-steps"><span class="active">1. Файлы</span><span>2. Проверка</span><span>3. Классы</span><span>4. Запуск</span></div><div class="pd-drop"><strong>${kind === "model" ? "Веса модели .pt" : kind === "dataset" ? "Архив или папка размеченного датасета" : "Изображения или папка"}</strong><p>${kind === "model" ? "Названия классов будут прочитаны из модели. Модель должна соответствовать типу проекта." : kind === "dataset" ? "YOLO: изображения + labels + data.yaml/classes.txt. COCO: JSON и изображения. Классификация: папки с именами классов." : "JPG, PNG, WebP. До 5000 изображений за импорт."}</p><div class="pd-actions">${button("pick-import", kind === "model" ? "Выбрать .pt" : "Выбрать файлы / ZIP", "pd-primary")}${kind !== "model" ? button("pick-folder", "Выбрать папку") : ""}</div></div><div id="pd-upload-status" role="status"></div>`);
    const choose = (folder) => filePicker({ multiple: kind !== "model", accept: kind === "model" ? ".pt" : ".jpg,.jpeg,.png,.webp,.zip,.txt,.yaml,.yml,.json", folder }, async files => {
      const host = get("#pd-upload-status", modalRoot); if (!host) return;
      host.innerHTML = `<div class="pd-notice">Загрузка и проверка ${fmt(files.length)} файлов… Не закрывайте окно до окончания проверки.</div>`;
      all("button[data-action^='pick-']", modalRoot).forEach(b => b.disabled = true);
      try { importJob = await api.previewDataImport(projectId, kind, files); showImportMapping(importJob); }
      catch (err) { if (host.isConnected) host.innerHTML = `<p class="pd-error">${esc(err.message)}</p>`; }
      finally { all("button[data-action^='pick-']", modalRoot).forEach(b => b.disabled = false); }
    });
    get('[data-action="pick-import"]', modalRoot).onclick = () => choose(false);
    get('[data-action="pick-folder"]', modalRoot)?.addEventListener("click", () => choose(true));
  }
  function showImportMapping(job) {
    importJob = job;
    const names = job.summary.names || [];
    modal("Импорт · проверка и классы", `<div class="pd-steps"><span>✓ Файлы</span><span>✓ Проверка</span><span class="active">3. Классы</span><span>4. Запуск</span></div><div class="pd-notice">${esc(job.summary.format)} · ${fmt(job.summary.images)} изображений · ${fmt(job.summary.objects)} объектов · ${fmt(job.summary.backgrounds)} фоновых кадров</div><p class="pd-muted">Выберите соответствие каждого исходного класса. Имена существующих классов проекта сохранятся.</p>${names.length ? `<div class="pd-table-wrap"><table><thead><tr><th>Индекс источника</th><th>Имя источника</th><th>Класс проекта</th></tr></thead><tbody>${names.map((name, i) => { const match = classes.find(c => c.name.toLocaleLowerCase() === name.toLocaleLowerCase()); return `<tr><td>${i}</td><td>${esc(name)}</td><td><select data-import-map="${i}">${option("new", "+ Создать класс", match?.id || "new")}${classes.map(c => option(c.id, c.name, match?.id || "new")).join("")}</select></td></tr>`; }).join("")}</tbody></table></div>` : job.kind === "model" ? '<label class="pd-field">Названия классов по порядку выходов модели<textarea id="pd-model-names" rows="6"></textarea></label>' : '<p>Классы не требуются для обычной загрузки изображений.</p>'}<div id="pd-import-validation" role="status"></div>`, button("confirm-import", "Проверить и перейти к запуску →", "pd-primary"), true);
    get('[data-action="confirm-import"]', modalRoot).onclick = () => {
      const mapping = Object.fromEntries(all("[data-import-map]", modalRoot).map(s => [s.dataset.importMap, s.value]));
      const manualNames = get("#pd-model-names", modalRoot)?.value.split(/\r?\n/).map(n => n.trim()).filter(Boolean);
      if (job.kind === "model" && !names.length && !manualNames?.length) { get("#pd-import-validation", modalRoot).textContent = "Укажите названия классов"; return; }
      const targets = Object.values(mapping).filter(v => v !== "new");
      if (new Set(targets).size !== targets.length) { get("#pd-import-validation", modalRoot).textContent = "Разные исходные классы нельзя сопоставить одному классу проекта"; return; }
      const newCount = Object.values(mapping).filter(v => v === "new").length;
      modal("Импорт · запуск", `<div class="pd-steps"><span>✓ Файлы</span><span>✓ Проверка</span><span>✓ Классы</span><span class="active">4. Запуск</span></div><h3>${esc(job.name)}</h3><p>${esc(job.summary.format)} · ${fmt(job.summary.images)} изображений</p><p>Совпадений: ${targets.length} · новых классов: ${newCount || manualNames?.length || 0}</p><div class="pd-notice">${job.kind === "model" ? "Модель добавится в проект с выбранным словарём. Текущая активная модель сбора сохранится." : "Импорт пойдёт в фоне. Рамки и классы сохранятся, разделы train/valid/test будут взяты из структуры датасета. Отменить импорт можно через историю."}</div><div id="pd-start-error" role="status"></div>`, button("back-mapping", "← К классам") + button("start-import", "Начать импорт", "pd-primary"));
      get('[data-action="back-mapping"]', modalRoot).onclick = () => showImportMapping(job);
      get('[data-action="start-import"]', modalRoot).onclick = () => run(async () => {
        const btn = get('[data-action="start-import"]', modalRoot); btn.disabled = true;
        try { await api.dataImportAction(projectId, job.id, "start", { mapping, ...(manualNames?.length ? { names: manualNames } : {}) }); closeModal(); await go("imports"); }
        catch (err) { get("#pd-start-error", modalRoot).textContent = err.message; btn.disabled = false; }
      });
    };
  }
  function showViewer(index) {
    const item = page.items[index]; if (!item) return;
    const body = `<div class="pd-viewer-layout"><div class="pd-viewer-media"><div class="pd-original"><img src="${api.imageFileUrl(item.id)}" alt="${esc(item.file_name)}">${boxes(item)}</div></div><aside><span class="pd-badge">${esc(STATUS[item.status] || item.status)}</span><h3>${esc(item.file_name)}</h3><dl><dt>Размер</dt><dd>${item.width} × ${item.height}</dd><dt>Источник</dt><dd>${esc(cameraName(item.stream_source_id))}</dd><dt>Добавлен</dt><dd>${new Date(item.created_at).toLocaleString("ru-RU")}</dd><dt>Раздел</dt><dd>${esc(item.split)}</dd><dt>Объекты</dt><dd>${item.annotations.length}</dd><dt>Теги</dt><dd>${esc(item.tags.join(", ") || "—")}</dd></dl><h3>Разметка</h3>${item.label ? `<p>${esc(cls(item.label.class_id)?.name || "Класс удалён")} · ${Math.round(item.label.confidence*100)}%</p>` : item.annotations.map(b => `<div class="pd-label-row"><span class="pd-color" style="background:${esc(cls(b.class_id)?.color_hex || "#a8b1ff")}"></span>${esc(cls(b.class_id)?.name || "Класс удалён")}<small>${Math.round(b.confidence*100)}% · ${esc(b.source === "MANUAL" ? "Человек / импорт" : "Модель")}</small></div>`).join("") || '<p class="pd-muted">Нет рамок</p>'}${item.is_background ? '<p>Фоновое изображение</p>' : ""}<p class="pd-muted">← → — соседний кадр · Esc — закрыть</p></aside></div>`;
    modal("Просмотр изображения", body, button("viewer-prev", "← Назад", "", index === 0 && page.offset === 0 ? "disabled" : "") + `<span>${page.offset+index+1} / ${fmt(page.total)}</span>` + button("viewer-next", "Вперёд →", "", page.offset+index+1 >= page.total ? "disabled" : "") + button("viewer-annotate", "Открыть разметку", "pd-primary"), true);
    viewerIndex = index;
    get('[data-action="viewer-prev"]', modalRoot).onclick = () => run(() => moveViewer(-1));
    get('[data-action="viewer-next"]', modalRoot).onclick = () => run(() => moveViewer(1));
    get('[data-action="viewer-annotate"]', modalRoot).onclick = () => { closeModal(); onOpenImage?.(item.id); };
  }
  async function moveViewer(delta) {
    let index = viewerIndex + delta;
    if (index < 0 && page.offset > 0) { page.offset -= page.limit; await loadPage(); index = page.items.length-1; }
    else if (index >= page.items.length && page.offset+page.limit < page.total) { page.offset += page.limit; await loadPage(); index = 0; }
    if (page.items[index]) showViewer(index);
  }
  async function cameraModal() {
    const projects = await api.listProjects();
    const lists = await Promise.all(projects.map(p => api.listStreams(p.id)));
    const sources = lists.flat();
    modal("Добавить камеру", `<div class="pd-camera-tabs"><label class="pd-field">Способ подключения<select id="pd-camera-kind"><option value="existing">Из общего каталога</option><option value="rtsp">Новый RTSP</option><option value="device">Веб-камера / устройство</option><option value="video">Видео</option></select></label></div><div id="pd-camera-fields"></div><div id="pd-camera-error" role="status"></div>`, button("save-camera", "Добавить в проект", "pd-primary"));
    function fields() {
      const kind = get("#pd-camera-kind", modalRoot).value;
      get("#pd-camera-fields", modalRoot).innerHTML = kind === "existing" ? `<label class="pd-field">Источник<select id="pd-camera-source">${sources.filter(c => !cameras.some(own => own.id === c.id)).map(c => option(c.id, `${projects.find(p => p.id === c.project_id)?.name || ""} / ${c.name}`, "")).join("")}</select></label><p class="pd-muted">Связь не меняет настройки других проектов и не создаёт копию камеры.</p>` : `<label class="pd-field">Название<input id="pd-camera-name" placeholder="Например, Въезд"></label>${kind === "rtsp" ? '<label class="pd-field">RTSP адрес<input type="password" id="pd-camera-uri" placeholder="rtsp://…" autocomplete="off"></label>' : kind === "device" ? '<label class="pd-field">Индекс устройства<input type="number" min="0" id="pd-camera-device" value="0"></label>' : '<label class="pd-field">Видеофайл<input type="file" id="pd-camera-video" accept="video/*"></label>'}`;
    }
    fields(); get("#pd-camera-kind", modalRoot).onchange = fields;
    get('[data-action="save-camera"]', modalRoot).onclick = () => run(async () => {
      const btn = get('[data-action="save-camera"]', modalRoot); btn.disabled = true;
      try {
        const kind = get("#pd-camera-kind", modalRoot).value;
        if (kind === "existing") { const id = get("#pd-camera-source", modalRoot).value; if (!id) throw new Error("Нет доступных камер; создайте новый источник"); await api.linkProjectCamera(projectId, id); }
        else {
          const name = get("#pd-camera-name", modalRoot).value.trim(); if (!name) throw new Error("Введите название камеры");
          if (kind === "rtsp") await api.createRtspStream(projectId, { name, rtsp_url: get("#pd-camera-uri", modalRoot).value.trim() });
          if (kind === "device") await api.createDeviceStream(projectId, { name, device_index: Number(get("#pd-camera-device", modalRoot).value) });
          if (kind === "video") { const file = get("#pd-camera-video", modalRoot).files[0]; if (!file) throw new Error("Выберите видео"); await api.uploadStreamVideo(projectId, file, name); }
        }
        closeModal(); await go("cameras");
      } catch (err) { get("#pd-camera-error", modalRoot).textContent = err.message; btn.disabled = false; }
    });
  }
  async function bulk(action) {
    if (!selected.size && !allMatching) return;
    const payload = { action, filters, ids: [...selected], all_matching: allMatching };
    if (action === "tag") { const tag = prompt("Тег для выбранных изображений"); if (!tag?.trim()) return; payload.tag = tag.trim(); }
    const result = await api.projectDataAction(projectId, payload);
    selected.clear(); allMatching = false;
    await refreshStats(); await loadPage(); showMessage(`Обновлено изображений: ${fmt(result.updated)}`);
  }
  root.addEventListener("click", e => {
    const sectionBtn = e.target.closest("[data-section]"); if (sectionBtn) { run(() => go(sectionBtn.dataset.section)); return; }
    const open = e.target.closest("[data-open]"); if (open) { showViewer(Number(open.dataset.open)); return; }
    const btn = e.target.closest("[data-action]"); if (!btn) return;
    const action = btn.dataset.action;
    run(async () => {
      if (SECTIONS.some(([id]) => id === action)) return go(action);
      if (action === "apply-filters") { readFilters(); resetPage(); return loadPage(); }
      if (action === "reset-filters" || action === "preset-all" || action === "all-images") { filters = {}; resetPage(); return go("images"); }
      if (["preset-review", "review", "unannotated", "verified", "preset-uncertain", "find-duplicates"].includes(action)) {
        filters = action === "unannotated" ? { status: "UNANNOTATED" } : action === "verified" ? { status: "VERIFIED,AUTO_VERIFIED" } : action === "preset-uncertain" ? { max_conf: .5, sort: "uncertainty" } : action === "find-duplicates" ? { duplicates: true } : { status: "REQUIRES_REVIEW,REQUIRES_RECHECK" }; resetPage(); return go("images");
      }
      if (action === "save-view") { readFilters(); const name = prompt("Название фильтра"); if (name?.trim()) { savedViews.push({ name: name.trim().slice(0, 80), filters: { ...filters } }); localStorage.setItem(dataKey(), JSON.stringify(savedViews)); renderImages(); } }
      if (action === "load-view") { filters = { ...savedViews[Number(btn.dataset.index)].filters }; resetPage(); return loadPage(); }
      if (action === "delete-view") { savedViews.splice(Number(btn.dataset.index), 1); localStorage.setItem(dataKey(), JSON.stringify(savedViews)); renderImages(); }
      if (action === "toggle-layout") { layout = layout === "grid" ? "list" : "grid"; renderImages(); }
      if (action === "toggle-density") { dense = !dense; renderImages(); }
      if (action === "next-page") { page.offset += page.limit; return loadPage(); }
      if (action === "previous-page") { page.offset = Math.max(0, page.offset-page.limit); return loadPage(); }
      if (action === "clear-selection") { selected.clear(); allMatching = false; renderImages(); }
      if (action === "select-matching") { allMatching = true; selected.clear(); renderImages(); }
      if (action.startsWith("bulk-")) return bulk(action.slice(5));
      if (action.startsWith("import-") && ["images", "dataset", "model"].includes(action.slice(7))) return importModal(action.slice(7));
      if (action === "refresh-imports") { jobs = await api.listDataImports(projectId); renderImports(); startPolling(); }
      if (action === "resume-import") return showImportMapping(jobs.find(j => j.id === btn.dataset.id));
      if (action === "cancel-import" || action === "rollback-import") { await api.dataImportAction(projectId, btn.dataset.id, action === "cancel-import" ? "cancel" : "rollback"); jobs = await api.listDataImports(projectId); renderImports(); startPolling(); }
      if (action === "add-classes") return addClassesModal();
      if (action === "import-dictionary") return filePicker({ multiple: false, accept: ".txt,.yaml,.yml,.json" }, async files => {
        const text = await files[0].text();
        // Plain text is editable before saving; JSON dictionaries preserve explicit order.
        let names = text;
        if (files[0].name.endsWith(".json")) { const data = JSON.parse(text); const raw = data.names || data.categories?.map(c => c.name) || data; names = (Array.isArray(raw) ? raw : Object.keys(raw).sort((a,b) => Number(a)-Number(b)).map(k => raw[k])).join("\n"); }
        if (/\.ya?ml$/i.test(files[0].name)) { const response = await api.parseClassDictionary(projectId, files[0]); names = response.names.join("\n"); }
        addClassesModal(names);
      });
      if (action === "export-dictionary") { const indices = classes.map(c => c.index_id); if (indices.some((n, i) => n !== i)) { const blob = new Blob([JSON.stringify({ names: Object.fromEntries(classes.map(c => [c.index_id, c.name])) }, null, 2)], { type: "application/json" }); download(blob, "classes.json"); } else download(new Blob([classes.map(c => c.name).join("\n")], { type: "text/plain" }), "classes.txt"); }
      if (action === "rename-class") { const c = cls(btn.dataset.id); const name = prompt("Новое название класса", c.name); if (name?.trim() && name.trim() !== c.name) { await api.renameClass(projectId, c.id, name.trim()); await syncClasses(); renderClasses(); } }
      if (action === "delete-class") {
        const c = cls(btn.dataset.id); const count = stats.classes.find(r => r.id === c.id);
        if ((count?.objects || 0) > 0) throw new Error("Класс используется в разметке. Сначала переназначьте объекты.");
        modal("Удалить класс", `<p>Удалить «${esc(c.name)}» из проекта? Для обученных моделей связь с этим классом будет потеряна.</p>`, button("confirm-delete-class", "Удалить класс", "pd-danger"));
        get('[data-action="confirm-delete-class"]', modalRoot).onclick = () => run(async () => { await api.deleteUnusedDataClass(projectId, c.id); closeModal(); await syncClasses(); renderClasses(); });
      }
      if (action === "add-camera") return cameraModal();
      if (action === "unlink-camera") { await api.linkProjectCamera(projectId, btn.dataset.id, false); return go("cameras"); }
      if (action === "camera-images") { filters = { stream_source_id: btn.dataset.id }; resetPage(); return go("images"); }
      if (action === "camera-collect") { location.hash = `/streams?project=${projectId}&source=${btn.dataset.id}`; }
      if (action === "quality-scan") { const result = await api.analyzeProjectData(projectId); showMessage(result.message); }
    });
  });
  function download(blob, name) { const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
  root.addEventListener("change", e => run(async () => {
    const t = e.target;
    if (t.dataset.select) { if (allMatching) { allMatching = false; page.items.forEach(i => selected.add(i.id)); } t.checked ? selected.add(t.dataset.select) : selected.delete(t.dataset.select); renderImages(); }
    if (t.id === "pd-select-page") { allMatching = false; page.items.forEach(i => t.checked ? selected.add(i.id) : selected.delete(i.id)); renderImages(); }
    if (t.id === "pd-overlays") { overlays = t.checked; renderImages(); }
    if (t.id === "pd-sort") { filters.sort = t.value; resetPage(); await loadPage(); }
    if (t.id === "pd-page-size") { page.limit = Number(t.value); resetPage(); await loadPage(); }
  }));
  document.getElementById("btn-open-upload")?.addEventListener("click", e => {
    if (store.get("projectTab") !== "data") return;
    e.preventDefault(); e.stopImmediatePropagation(); importModal("images");
  }, true);
  document.addEventListener("keydown", e => {
    if (!modalRoot) return;
    if (e.key === "Escape") { e.stopPropagation(); closeModal(); }
    if (viewerIndex >= 0 && ["ArrowLeft", "ArrowRight"].includes(e.key)) { e.preventDefault(); e.stopPropagation(); run(() => moveViewer(e.key === "ArrowLeft" ? -1 : 1)); }
    if (e.key === "Tab") {
      const focusable = all('button:not(:disabled),input,select,textarea,a[href]', modalRoot);
      const first = focusable[0], last = focusable.at(-1);
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    }
  }, true);
  async function refresh() {
    const project = store.get("currentProject"); if (!project || !root) return;
    const id = project.id, switched = projectId !== id, seq = ++refreshSequence;
    sequence++; sectionSequence++;
    clearTimeout(searchTimer);
    if (switched) { clearTimeout(pollTimer); closeModal(); jobs = []; }
    projectId = id;
    if (switched) { filters = {}; page.offset = 0; selected.clear(); allMatching = false; try { savedViews = JSON.parse(localStorage.getItem(dataKey()) || "[]"); } catch { savedViews = []; } }
    const query = new URLSearchParams(location.hash.split("?")[1] || "");
    section = SECTIONS.some(([s]) => s === query.get("section")) ? query.get("section") : "images";
    classes = [...(store.get("classes") || [])].sort((a, b) => a.index_id-b.index_id);
    renderShell(); get("#pd-content").innerHTML = '<div class="pd-empty">Загрузка данных…</div>';
    try {
      const results = await Promise.all([api.projectDataStatistics(id), api.projectCameras(id), api.listDatasetVersions(id)]);
      if (projectId !== id || refreshSequence !== seq) return;
      [stats, cameras, versions] = results;
      await loadSection();
    } catch (err) { if (projectId !== id || refreshSequence !== seq) return; get("#pd-content").innerHTML = `<div class="pd-empty pd-error">${esc(err.message)}${button("all-images", "Повторить")}</div>`; error(err); }
  }
  return { refresh, async previewModel(file) {
    projectId = store.get("currentProject")?.id;
    if (!projectId) throw new Error("Сначала откройте проект");
    classes = await api.listClasses(projectId);
    modal("Проверка модели", '<p class="pd-muted">Загрузка весов, проверка типа задачи и названий классов…</p>');
    try { const job = await api.previewDataImport(projectId, "model", [file]); showImportMapping(job); }
    catch (err) { closeModal(); throw err; }
  } };
}
