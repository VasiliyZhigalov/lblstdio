import {authUser} from "../auth.js?v=auth-20261023a";
import { api } from "../api.js?v=annotation-queue-20261022e";
import { annotationRevision } from "../annotationSession.js";
import { store, isClassification } from "../store.js";
import { escapeHtml as esc } from "../utils/dom.js";

const names = { QUEUED: "Ожидает разметки", WORKING: "В работе", DONE: "Готово", ISSUE: "Требует уточнения" };
const format = n => Number(n || 0).toLocaleString("ru-RU");

export function initAnnotationQueue({ openImage, save, confirmModel, toast, fit }) {
  const view = document.getElementById("tab-view-annotate");
  const home = document.createElement("div"); home.id = "annotation-queue-home"; home.className = "hidden"; view.append(home);
  const editor = document.getElementById("canvas-container").parentElement;
  editor.classList.add("aq-editor");
  const heading = document.createElement("div"); heading.className = "aq-heading";
  heading.innerHTML = `<button data-aq="home" class="aq-button">← Моя очередь</button><div><strong id="aq-file">Выберите кадр</strong><small id="aq-file-meta"></small></div><span id="aq-save" role="status"></span>`;
  editor.prepend(heading);
  const banner = document.createElement("div"); banner.id = "aq-banner"; banner.setAttribute("role", "status"); editor.insertBefore(banner, heading.nextSibling);
  const footer = document.createElement("div"); footer.className = "aq-completion";
  footer.innerHTML = `<div><strong id="aq-completion-title">Разметьте целевые объекты</strong><small id="aq-completion-note">W — рамка · V — выбор · F — вписать · H — скрыть рамки</small></div><button data-aq="confirm" class="aq-button hidden" id="aq-confirm">Подтвердить предложения модели</button><button data-aq="clear" class="aq-button" id="aq-clear" title="Очистить разметку (R)">Очистить <kbd>R</kbd></button><button data-aq="trash" class="aq-button" id="aq-trash" title="Удалить изображение в корзину (Delete)">Удалить <kbd>Delete</kbd></button><button data-aq="background" class="aq-button" id="aq-background" title="Нет целевых объектов: сохранить как фон и перейти далее (N)">∅ Фон <kbd>N</kbd></button><button data-aq="skip" class="aq-button" id="aq-skip">Пропустить</button><button data-aq="finish" class="aq-button aq-primary" id="aq-finish">Готово <kbd>Пробел</kbd></button>`;
  editor.append(footer);
  const tools = document.getElementById("tool-select").parentElement;
  tools.classList.add("aq-tools");
  const extra = document.createElement("div"); extra.className = "aq-extra-tools";
  extra.innerHTML = `<button data-aq="undo" title="Отменить (Ctrl Z)">↶</button><button data-aq="redo" title="Повторить (Ctrl Shift Z)">↷</button><button data-aq="help" title="Инструкция и клавиши">?</button>`;
  tools.append(extra);
  const sidebar = document.getElementById("studio-right-sidebar");
  const search = document.createElement("input"); search.id = "aq-class-search"; search.type = "search"; search.placeholder = "Найти класс…"; search.setAttribute("aria-label", "Найти класс");
  document.getElementById("classes-list").before(search);
  const legend = document.createElement("div"); legend.className = "aq-legend"; legend.textContent = "Пунктир — предложение модели. Проверьте класс и границы каждого объекта."; sidebar.append(legend);
  const instruction = document.createElement("button"); instruction.className = "aq-button aq-instruction"; instruction.dataset.aq = "help"; instruction.textContent = "Инструкция и горячие клавиши"; sidebar.append(instruction);
  let lease = null, busy = false, listState = "all", offset = 0, homeSeq = 0, heartbeat, autosave, modal, stale = false;
  let claimChain = Promise.resolve();
  const projectId = () => store.get("currentProject")?.id;
  const draftKey = id => `lblstdio:annotation-draft:${authUser()?.id ? authUser().id+":" : ""}${projectId()}:${id}`;
  function closeModal() { modal?.remove(); modal = null; }
  function dialog(title, body, actions = "") {
    closeModal(); modal = document.createElement("div"); modal.className = "aq-modal-backdrop";
    modal.innerHTML = `<section class="aq-modal" role="dialog" aria-modal="true" aria-label="${esc(title)}"><h2>${esc(title)}</h2>${body}<div class="aq-modal-actions"><button class="aq-button" data-aq="close">Закрыть</button>${actions}</div></section>`;
    document.body.append(modal); modal.onclick = e => { if (e.target === modal) closeModal(); }; modal.querySelector("button")?.focus();
  }
  function saveDraft() {
    const image = store.get("currentImage");
    if (!image || store.get("annotationReadonly") || !store.get("hasUnsavedChanges")) return;
    try { localStorage.setItem(draftKey(image.id), JSON.stringify({ annotations: store.get("annotations"), revision: annotationRevision(image.id), createdAt: Date.now() })); }
    catch { toast("Не удалось сохранить локальный черновик. Не закрывайте вкладку до сохранения на сервере."); }
  }
  function lock(message) { saveDraft(); stale = true; store.set("annotationReadonly", true); store.set("selectedBoxId", null); sync(message); }
  async function flush() {
    clearTimeout(autosave);
    if (store.get("hasUnsavedChanges")) {
      try { await save({ silent: true }); }
      catch (err) { if (err.status === 409 || !err.status || err.status >= 500 || !navigator.onLine) lock(err.message); throw err; }
    }
    const id = store.get("currentImage")?.id;
    if (id && !store.get("hasUnsavedChanges")) localStorage.removeItem(draftKey(id));
  }
  async function release() {
    clearInterval(heartbeat); clearTimeout(autosave);
    const previous = lease;
    if (previous?.mine && !stale) {
      try { await api.annotationQueueAction(previous.projectId, previous.image_id, "release"); }
      catch (err) { if (err.status !== 409) throw err; }
    }
    lease = null;
  }
  function startHeartbeat() {
    clearInterval(heartbeat);
    if (!lease?.mine || lease.readonly) return;
    heartbeat = setInterval(async () => {
      if (store.get("projectTab") !== "annotate" || !lease?.mine) return;
      const id = lease.image_id, pid = lease.projectId;
      try { await api.annotationQueueAction(pid, id, "heartbeat"); }
      catch (err) { if (lease?.image_id === id) lock(err.message); }
    }, 30000);
    heartbeat.unref?.();
  }
  function beforeOpen(id, isCurrent = () => true) {
    const pid = projectId();
    const request = claimChain.then(async () => {
      if(!isCurrent()) return;
      clearTimeout(autosave); clearInterval(heartbeat);
      let result;
      try { result = await api.claimAnnotation(pid, id); }
      catch (err) { if (err.status !== 409) throw err; toast(err.message); await showHome(); return false; }
      if(!isCurrent()) {
        if(result.mine && !result.readonly) await api.annotationQueueAction(pid,id,"release");
        return;
      }
      lease = { ...result, projectId: pid }; stale = false;
      store.set("annotationReadonly", !!result.readonly); startHeartbeat(); return result;
    });
    claimChain = request.catch(() => {});
    return request;
  }
  function afterOpen() {
    home.classList.add("hidden"); view.classList.remove("aq-home-visible");
    sync(); fit?.();
    const image = store.get("currentImage");
    const pid = projectId();
    if(image) api.annotationQueue(pid).then(result=>{
      if(projectId()!==pid || store.get('currentImage')?.id!==image.id)return;
      const images=result.items.map(t=>t.image);
      if(!images.some(i=>i.id===image.id))images.unshift(image);
      store.set('images',images);
    }).catch(err=>toast(err.message));
    if (!image || store.get("annotationReadonly")) return;
    let draft; try { draft = JSON.parse(localStorage.getItem(draftKey(image.id)) || "null"); } catch {}
    if (!draft) return;
    const matches = draft.revision === annotationRevision(image.id);
    dialog("Найден локальный черновик", `<p>${matches ? "Предыдущее сохранение не завершилось. Можно восстановить свои изменения этого кадра." : "Версия кадра изменилась. Черновик сохранён для сравнения; автоматическая перезапись серверной разметки отключена."}</p><p>Сохранён ${new Date(draft.createdAt).toLocaleString("ru-RU")}. Рамок: ${draft.annotations?.length || 0}.</p>`, `${matches ? '<button class="aq-button aq-primary" data-aq="restore-draft">Восстановить черновик</button>' : '<button class="aq-button" data-aq="download-draft">Скачать черновик JSON</button>'}<button class="aq-button" data-aq="discard-draft">Оставить серверную версию</button>`);
    modal.dataset.image = image.id; modal.dataset.draft = JSON.stringify(draft);
  }
  async function showHome() {
    const seq = ++homeSeq, pid = projectId(); if (!pid) return;
    await flush(); await release();
    if(pid !== projectId() || store.get("projectTab") !== "annotate") return;
    history.replaceState(null, "", `${location.pathname}${location.search}#/projects/${pid}/annotate`);
    store.patch({ annotationReadonly: true, hasUnsavedChanges: false });
    view.classList.add("aq-home-visible"); home.classList.remove("hidden");
    home.innerHTML = '<div class="aq-empty">Загрузка очереди…</div>';
    let result;
    try { result = await api.annotationQueue(pid, listState, offset); }
    catch (err) { if(seq===homeSeq) home.innerHTML=`<div class="aq-empty">Не удалось загрузить очередь.<br>${esc(err.message)}<br><button class="aq-button" data-aq="refresh">Повторить</button></div>`; throw err; }
    if (seq !== homeSeq || pid !== projectId() || store.get("projectTab") !== "annotate") return;
    const counts = result.counts;
    home.innerHTML = `<div class="aq-home-content"><div class="aq-home-heading"><div><div class="aq-eyebrow">${esc(store.get("currentProject")?.name || "")} / Разметка</div><h1>Очередь разметки</h1><p>Возьмите свободный кадр, разметьте объекты и нажмите «Готово».</p></div><button class="aq-button aq-primary" data-aq="start">Начать работу →</button></div><div class="aq-counts">${[["QUEUED","Ожидают разметки"],["WORKING","Сейчас в работе"],["DONE","Готово"]].map(([k,n])=>`<div><span>${n}</span><strong>${format(counts[k])}</strong></div>`).join("")}</div><div class="aq-notice">Очередь формируется во вкладке «Данные»: выберите изображения или результат фильтра → «В очередь разметки». Уже занятые кадры защищены. До авторизации разметчики различаются по сессиям вкладок браузера.</div><div class="aq-home-filters">${[["all","Все задания"],["available","Свободные"],["mine","Мой кадр"]].map(([key,label])=>`<button class="aq-button ${listState===key?'aq-active':''}" data-aq-filter="${key}">${label}</button>`).join("")}<button class="aq-button" data-aq="refresh">Обновить</button></div><div class="aq-task-table"><table><thead><tr><th>Кадр</th><th>Состояние</th><th>Примечание</th><th></th></tr></thead><tbody>${result.items.map(t=>`<tr><td><img src="${api.thumbnailUrl(t.image_id)}" loading="lazy" alt=""><strong>${esc(t.image.file_name)}</strong><small>${t.image.width} × ${t.image.height}</small></td><td><span class="aq-badge ${t.state==='DONE'?'good':t.state==='ISSUE'?'warn':''}">${t.mine?'Редактируете вы':t.state==='WORKING'?'Занят другой сессией':names[t.state]}</span></td><td>${esc(t.reason || (t.mine?'Черновик сохранён на сервере':t.state==='DONE'?'Разметка подтверждена':'—'))}</td><td><button class="aq-button" data-aq-open="${t.image_id}" ${t.state==='WORKING'&&!t.mine?'disabled':''}>${['DONE','ISSUE'].includes(t.state)?'Посмотреть':'Открыть'}</button></td></tr>`).join("")||'<tr><td colspan="4"><div class="aq-empty">Здесь пока нет кадров.<br>Добавьте изображения в очередь из вкладки «Данные».</div></td></tr>'}</tbody></table></div><div class="aq-home-pager"><span>${format(result.total)} заданий · страница ${Math.floor(offset/48)+1}</span><button class="aq-button" data-aq="previous" ${offset===0?'disabled':''}>←</button><button class="aq-button" data-aq="next-page" ${offset+48>=result.total?'disabled':''}>→</button></div><div class="aq-help-cards"><div><strong>Один кадр — один разметчик</strong><p>Пока вы работаете, другая сессия не сможет изменить этот кадр.</p></div><div><strong>Черновик сохраняется автоматически</strong><p>Черновик не входит в обучение до завершения кадра. При потере связи работа сохраняется на устройстве.</p></div><div><strong>Сложный кадр можно пропустить</strong><p>Черновик сохранится, кадр вернётся в конец очереди, а вы продолжите работу.</p></div></div></div>`;
    store.set("images", result.items.map(t=>t.image));
  }
  async function start(skippedId = null) {
    const pid = projectId(); await flush();
    if(pid !== projectId() || store.get("projectTab") !== "annotate") return;
    const result = await api.claimAnnotation(pid);
    if(pid !== projectId() || store.get("projectTab") !== "annotate") {
      if(result.image_id && result.mine) await api.annotationQueueAction(pid,result.image_id,"release");
      return;
    }
    if (!result.image_id) { toast("Свободных кадров нет. Добавьте изображения в очередь или обновите список."); return showHome(); }
    if (result.image_id === skippedId) { await api.annotationQueueAction(pid, result.image_id, "release"); return showHome(); }
    await openImage(result.image_id, pid);
  }
  async function finish(action = "finish") {
    if (busy || store.get("annotationReadonly")) return;
    busy = true; sync();
    try {
      await flush();
      const image = store.get("currentImage");
      await api.annotationQueueAction(projectId(), image.id, action);
      localStorage.removeItem(draftKey(image.id)); lease = null; clearInterval(heartbeat);
      store.set("annotationReadonly", true); toast("Кадр готов. Разметка подтверждена.");
      await start();
    } catch (err) { if (err.status === 409) lock(err.message); toast(err.message); }
    finally { busy = false; sync(); }
  }
  function sync(message = "") {
    const image = store.get("currentImage"), readonly = store.get("annotationReadonly");
    view.classList.toggle("aq-readonly", !!readonly);
    const pending = isClassification() ? Number(image?.label?.verification_status === "PENDING_REVIEW") : (store.get("annotations") || []).filter(b=>b.verification_status === "PENDING_REVIEW").length;
    const count = (store.get("annotations") || []).length;
    document.getElementById("aq-file").textContent = image?.file_name || "Выберите кадр";
    document.getElementById("aq-file-meta").textContent = image ? `${image.width} × ${image.height} · ${isClassification()?"Классификация":"Детекция объектов"} · ${readonly?"Только просмотр":"Редактируете вы"}` : "";
    document.getElementById("aq-save").textContent = store.get("hasUnsavedChanges") ? "● Сохраняется…" : "✓ Черновик сохранён";
    banner.innerHTML = message ? `${esc(message)} <button data-aq="reload" class="aq-button">Перезагрузить кадр</button>` : stale ? 'Редактирование остановлено. Локальный черновик сохранён. <button data-aq="reload" class="aq-button">Проверить доступ</button>' : readonly && image ? `Кадр ${lease?.state==='DONE'?'готов':lease?.state==='ISSUE'?'требует уточнения':'доступен только для просмотра'}. Чтобы изменить завершённый кадр, повторно отправьте его в очередь из «Данных».` : "";
    banner.hidden = !banner.textContent.trim();
    document.getElementById("aq-finish").disabled = busy || readonly || !image || (isClassification() ? !image.label : !count && !image.is_background);
    document.getElementById("aq-background").hidden = isClassification();
    document.getElementById("aq-background").disabled = busy || readonly || !image;
    document.getElementById("aq-skip").disabled = busy || readonly || !image;
    for (const id of ["aq-clear", "aq-trash"]) document.getElementById(id).disabled = busy || readonly || !image;
    document.getElementById("aq-confirm").classList.toggle("hidden", true);
    document.getElementById("aq-confirm").textContent = `Подтвердить предложения (${pending})`;
    document.getElementById("aq-completion-title").textContent = readonly ? "Только просмотр" : pending ? `Проверьте ${pending} предложений модели` : isClassification() ? image?.label ? "Класс назначен — завершите кадр" : "Выберите класс изображения" : count ? `Объектов: ${count}. Можно завершить кадр.` : image?.is_background ? "Отмечено отсутствие целевых объектов" : "Нарисуйте объекты или отметьте их отсутствие";
    document.getElementById("aq-completion-note").textContent = isClassification() ? "1–9 — назначить класс · Пробел — готово" : "W — рамка · V — выбор · F — вписать · H — скрыть рамки";
    legend.hidden = isClassification();
    document.getElementById("btn-mark-background").disabled = readonly || !!count;
    document.getElementById("btn-mark-background").textContent = image?.is_background ? "✓ Нет целевых объектов" : "Нет целевых объектов";
    filterClasses();
  }
  function filterClasses() { const term = search.value.toLocaleLowerCase(); document.querySelectorAll('#classes-list [data-class-id]').forEach(b=>b.parentElement.hidden=!b.textContent.toLocaleLowerCase().includes(term)); }
  search.oninput = filterClasses;
  document.addEventListener("click", e => {
    const open = e.target.closest("[data-aq-open]"); const filter = e.target.closest("[data-aq-filter]"); const button = e.target.closest("[data-aq]");
    if (open&&!open.disabled) { openImage(open.dataset.aqOpen).catch(err=>toast(err.message)); return; }
    if (filter) { listState=filter.dataset.aqFilter; offset=0; showHome().catch(err=>toast(err.message)); return; }
    if (!button || button.disabled) return;
    const action = button.dataset.aq;
    Promise.resolve().then(async()=>{
      if (action==='close') closeModal();
      if (action==='home'||action==='refresh') await showHome();
      if (action==='start') { if(busy)return; busy=true;try{await start();}finally{busy=false;sync();} }
      if (action==='finish') await finish();
      if (action==='background') await finish('background');
      if (action==='confirm') { await flush(); await confirmModel(); sync(); }
      if (action==='previous'||action==='next-page') {offset=Math.max(0,offset+(action==='previous'?-48:48));await showHome();}
      if (action==='reload') { if(!navigator.onLine)throw new Error('Связь не восстановлена. Черновик остаётся на устройстве.'); store.set('hasUnsavedChanges',false); await openImage(store.get('currentImage').id, null, true); }
      if (action==='clear'||action==='trash') {
        if(busy||store.get('annotationReadonly'))return; busy=true;sync();
        try {
          await flush(); const image=store.get('currentImage');
          await api.annotationQueueAction(projectId(),image.id,action);
          localStorage.removeItem(draftKey(image.id)); lease=null;clearInterval(heartbeat);
          store.patch({currentImage:null,annotations:[],selectedBoxId:null,hasUnsavedChanges:false,annotationReadonly:true});
          toast(action==='clear'?'Разметка очищена. Кадр возвращён в неразмеченные.':'Изображение перемещено в корзину.');
          await start();
        } finally {busy=false;sync();}
      }
      if (action==='skip') {
        if(busy)return; busy=true; sync();
        try { await flush(); const skippedId=store.get('currentImage').id; await api.annotationQueueAction(projectId(),skippedId,'skip');lease=null;clearInterval(heartbeat);await start(skippedId); }
        finally { busy=false;sync(); }
      }
      if (action==='restore-draft') { const d=JSON.parse(modal.dataset.draft);if(modal.dataset.image!==store.get('currentImage')?.id||store.get('annotationReadonly'))return; store.patch({annotations:d.annotations,hasUnsavedChanges:true});closeModal(); }
      if (action==='discard-draft') {localStorage.removeItem(draftKey(modal.dataset.image));closeModal();}
      if (action==='download-draft') { const url=URL.createObjectURL(new Blob([modal.dataset.draft],{type:'application/json'})); const a=document.createElement('a');a.href=url;a.download='annotation-draft.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000); }
      if(action==='undo'||action==='redo') window.dispatchEvent(new KeyboardEvent('keydown',{code:'KeyZ',key:'z',ctrlKey:true,shiftKey:action==='redo',bubbles:true}));
      if(action==='help') dialog('Как размечать кадр','<p>1. Выберите класс справа.<br>2. Протяните рамку вокруг объекта.<br>3. Проверьте предложения модели (пунктир).<br>4. Нажмите «Готово».</p><p><b>W</b> — рамка · <b>V</b> — выбор · <b>1–9</b> — класс<br><b>Alt + мышь</b> — сдвиг · колесо — масштаб<br><b>F</b> — вписать · <b>H</b> — скрыть рамки<br><b>Ctrl Z</b> — отменить · <b>Backspace</b> — удалить выбранную рамку<br><b>Пробел</b> — готово · <b>Delete</b> — удалить кадр<br><b>R</b> — очистить · <b>N</b> — фон и далее</p><p>«Очистить» удаляет разметку и возвращает кадр в неразмеченные. «Удалить» перемещает кадр в корзину.</p>');
    }).catch(err=>{if(err.status===409)lock(err.message);toast(err.message);});
  });
  document.addEventListener('keydown',e=>{
    if(store.get('projectTab')!=='annotate'||document.querySelector('.auth-screen,.auth-dialog-backdrop'))return;
    if(modal){if(e.key==='Escape')closeModal();return;}
    if(e.target.closest?.('input,textarea,select,[contenteditable="true"]') || document.querySelector('.pd-modal-backdrop'))return;
    const shortcuts = {Space:'aq-finish', Delete:'aq-trash', KeyR:'aq-clear', KeyN:'aq-background'};
    const id = !e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey ? shortcuts[e.code] : (e.ctrlKey||e.metaKey)&&e.code==='Enter'?'aq-finish':null;
    if(!id)return;
    e.preventDefault();e.stopImmediatePropagation();
    const button=document.getElementById(id);
    if(!e.repeat && home.classList.contains('hidden') && button && !button.disabled && !button.hidden)button.click();
  },true);
  store.addEventListener('change:hasUnsavedChanges',()=>{
    sync(); if(!store.get('hasUnsavedChanges')||store.get('annotationReadonly'))return;
    saveDraft(); clearTimeout(autosave); autosave=setTimeout(()=>flush().catch(err=>{if(err.status===409)lock(err.message);sync('Не удалось сохранить изменения. Черновик остаётся на устройстве.');}),900);
  });
  for(const prop of ['annotations','currentImage','saveStatus','annotationReadonly'])store.addEventListener(`change:${prop}`,()=>{sync();if(prop==='annotations'&&store.get('hasUnsavedChanges')){saveDraft();clearTimeout(autosave);autosave=setTimeout(()=>flush().catch(err=>{if(err.status===409)lock(err.message);sync('Не удалось сохранить изменения. Черновик остаётся на устройстве.');}),900);}});
  window.addEventListener('offline',()=>{if(store.get('projectTab')==='annotate')lock('Нет связи. Черновик сохранён локально; завершение кадра недоступно до восстановления связи.');});
  window.addEventListener('beforeunload',saveDraft);
  return {beforeOpen,afterOpen,showHome,finish,async leave(){await flush();await release();homeSeq++;},lock};
}
