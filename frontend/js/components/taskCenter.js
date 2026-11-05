import { api } from '../api.js?v=task-controls-20261029';
import { escapeHtml as esc } from '../utils/dom.js';

const names = { QUEUED:'В очереди', RUNNING:'Выполняется', CANCELLING:'Останавливается', ACTION_REQUIRED:'Нужно действие', COMPLETED:'Готово', FAILED:'Ошибка', CANCELLED:'Отменено' };
const typeNames = { upload:'Передача файлов', training:'Обучение', auto_label:'Авторазметка', import:'Импорт', quality:'Анализ качества', dataset:'Датасет', audit:'Проверка разметки' };
const active = j => ['RUNNING','CANCELLING','QUEUED','ACTION_REQUIRED'].includes(j.status);
const date = value => value ? new Date(value).toLocaleString('ru-RU') : '';
const percent = j => j.total > 0 ? Math.max(0,Math.min(100,Math.round(j.processed / j.total * 100))) : null;
function details(j) {
  if(j.kind==='upload') return j.stage==='receiving' ? 'Сервер принимает файлы' : j.total ? `Передано ${(j.processed / 1048576).toFixed(1)} из ${(j.total / 1048576).toFixed(1)} МБ · не закрывайте вкладку` : 'Передача файлов · не закрывайте вкладку';
  if(j.raw_status==='CHECKING') return j.total ? `Проверено ${j.processed} из ${j.total} файлов` : 'Проверка файлов';
  if(j.status==='ACTION_REQUIRED') return 'Проверка завершена · продолжите импорт';
  if(j.kind==='training' && j.status==='QUEUED') return j.schedule_mode==='night' ? 'Ожидает ночного окна и свободной GPU' : 'Ожидает свободной GPU';
  if(j.kind==='training' && j.status==='CANCELLING') return `Остановка после текущей эпохи · ${Math.min(j.processed,j.total || j.processed)} эпох`;
  if(j.kind==='training' && j.stopped_early && j.status==='COMPLETED') return `Ранняя остановка на эпохе ${Math.min(j.processed,j.total || j.processed)}`;
  if(j.kind==='training' && j.status==='COMPLETED') return `Обучение завершено · эпох: ${Math.min(j.processed,j.total || j.processed)}`;
  if(j.total>0) return `${j.processed} из ${j.total} ${j.unit}${j.kind==='auto_label' ? ` · найдено объектов: ${j.predictions || 0}` : ''}`;
  return j.status==='RUNNING' ? 'Идёт обработка' : (names[j.status] || j.status);
}
function link(j) {
  const p=encodeURIComponent(j.project_id);
  if(j.kind==='upload' && j.destination==='streams') return '/streams';
  if(j.kind==='import'||j.kind==='quality'||j.kind==='upload') return `/projects/${p}/data?section=imports${j.status==='ACTION_REQUIRED' ? '&import='+encodeURIComponent(j.id) : ''}`;
  if(j.kind==='dataset') return `/projects/${p}/models?section=datasets`;
  if(j.kind==='auto_label') return `/projects/${p}/models?section=auto&task=${encodeURIComponent(j.id)}`;
  return `/projects/${p}/models?section=queue`;
}
function markup(j, compact=false) {
 const p=percent(j), showProgress=['RUNNING','CANCELLING'].includes(j.status) && p!==null;
 return `<article class="tc-task"><div class="tc-main"><div class="tc-task-title">${esc(j.title)} <span class="tc-status ${esc(j.status.toLowerCase())}">${esc(names[j.status]||j.status)}</span></div><div class="tc-muted">${esc(j.project_name)} · ${esc(typeNames[j.kind]||j.kind)}${compact?'':' · '+esc(date(j.created_at))}</div><div class="tc-description">${esc(details(j))}</div>${showProgress?`<div class="tc-progress-row"><progress value="${p}" max="100"></progress><span>${p}%</span></div>`:''}${j.error?`<div class="tc-error">${esc(j.error)}</div>`:''}</div><button class="tc-link" data-tc-open="${esc(j.kind)}:${esc(j.id)}">${j.status==='ACTION_REQUIRED'?'Продолжить':'Открыть'} →</button></article>`;
}
export function initTaskCenter({navigate}) {
 let jobs=[], serverJobs=[], uploads=new Map(), panel=null, selected='ALL', query='', type='', project='', connected=false, polling=false, pages=1, hasMore=false;
 const merge=()=>{jobs=[...uploads.values(),...serverJobs];};
 const root=document.getElementById('view-tasks');
 const button=document.createElement('button');button.id='training-notifications';button.className='tc-top-button';button.type='button';button.setAttribute('aria-label','Задачи');document.body.append(button);
 let seen=new Set();try{seen=new Set(JSON.parse(localStorage.getItem('lblstdio:task-notifications')||'[]'));}catch{}
 function label(){const count=jobs.filter(active).length, unread=jobs.filter(j=>['COMPLETED','FAILED'].includes(j.status)&&!seen.has(`${j.kind}:${j.id}`)).length;button.textContent=`◷ Задачи${count ? ' · '+count : ''}${unread?' •':''}`;button.title=connected?'Задачи всех проектов':'Не удалось обновить задачи';}
 function page(){if(!root || root.classList.contains('hidden'))return;
  const visible=jobs.filter(j=>(selected==='ALL'||j.status===selected||(selected==='RUNNING'&&j.status==='CANCELLING')||(selected==='WAITING'&&['QUEUED','ACTION_REQUIRED'].includes(j.status)))&&(!type||j.kind===type)&&(!project||j.project_id===project)&&(!query||`${j.title} ${j.project_name}`.toLowerCase().includes(query.toLowerCase())));
  const counts={ALL:jobs.length,RUNNING:jobs.filter(j=>['RUNNING','CANCELLING'].includes(j.status)).length,WAITING:jobs.filter(j=>['QUEUED','ACTION_REQUIRED'].includes(j.status)).length,COMPLETED:jobs.filter(j=>j.status==='COMPLETED').length,FAILED:jobs.filter(j=>j.status==='FAILED').length};
  const projects=[...new Map(jobs.map(j=>[j.project_id,j.project_name])).entries()];
  root.innerHTML=`<div class="tc-page"><div class="tc-heading"><div><div class="tc-eyebrow">МОНИТОРИНГ / ВСЕ ПРОЕКТЫ</div><h1>Центр задач</h1><p>Следите за процессами и результатами проектов в одном месте.</p></div><a href="#/projects" class="tc-button">← К проектам</a></div><div class="tc-metrics">${[['ALL','Все задачи'],['RUNNING','Выполняются'],['WAITING','Ожидают'],['FAILED','С ошибкой']].map(([id,title])=>`<button data-tc-filter="${id}" class="tc-metric ${selected===id?'active':''}"><span>${title}</span><strong>${counts[id]}</strong></button>`).join('')}</div><section class="tc-panel"><div class="tc-panel-head"><h2>Все задачи <span>${visible.length}</span></h2><button class="tc-button" data-tc-refresh>Обновить</button></div><div class="tc-filters"><input data-tc-search placeholder="Поиск по задаче или проекту" value="${esc(query)}"><select data-tc-project><option value="">Все проекты</option>${projects.map(([id,name])=>`<option value="${esc(id)}" ${project===id?'selected':''}>${esc(name)}</option>`).join('')}</select><select data-tc-type><option value="">Все типы</option>${Object.entries(typeNames).map(([id,name])=>`<option value="${id}" ${type===id?'selected':''}>${name}</option>`).join('')}</select></div><div class="tc-tabs">${[['ALL','Все'],['RUNNING','Выполняются'],['WAITING','Ожидают'],['COMPLETED','Завершены'],['FAILED','Ошибки']].map(([id,title])=>`<button data-tc-filter="${id}" class="${selected===id?'active':''}">${title} ${counts[id]}</button>`).join('')}</div>${visible.map(j=>markup(j)).join('')||'<div class="tc-empty">Задачи по этим условиям не найдены</div>'}<div class="tc-footer">${connected?(hasMore?'Показана часть задач · ':'')+'обновляется автоматически':'Не удалось обновить список. Проверьте соединение.'}${hasMore?' <button class="tc-link" data-tc-more>Загрузить ещё</button>':''}</div></section></div>`;
 }
 function renderPanel(){if(!panel)return;const current=jobs.filter(active);const recent=jobs.filter(j=>!active(j)).slice(0,4);panel.innerHTML=`<div class="tc-panel-head"><h2>Задачи</h2><button data-tc-close aria-label="Закрыть">✕</button></div><div class="tc-pop-content"><h3>Выполняются и ожидают · ${current.length}</h3>${current.map(j=>markup(j,true)).join('')||'<p class="tc-muted">Нет активных задач</p>'}<h3>Недавние результаты</h3>${recent.map(j=>markup(j,true)).join('')||'<p class="tc-muted">Завершённых задач пока нет</p>'}</div><button class="tc-all" data-tc-all>Все задачи →</button>`;}
 async function refresh(){if(polling)return;polling=true;try{const results=await Promise.all(Array.from({length:pages},(_,index)=>api.tasks(index*100,100)));serverJobs=[...new Map(results.flatMap(result=>result.items||[]).map(j=>[`${j.kind}:${j.id}`,j])).values()];hasMore=!!results.at(-1)?.has_more;merge();connected=true;}catch{connected=false;}finally{polling=false;label();renderPanel();if(!document.activeElement?.matches('[data-tc-search]'))page();}}
 button.onclick=()=>{if(panel){panel.remove();panel=null;return;}panel=document.createElement('div');panel.className='tc-popover';panel.setAttribute('role','dialog');panel.setAttribute('aria-label','Задачи');document.body.append(panel);renderPanel();jobs.filter(j=>['COMPLETED','FAILED'].includes(j.status)).forEach(j=>seen.add(`${j.kind}:${j.id}`));try{localStorage.setItem('lblstdio:task-notifications',JSON.stringify([...seen].slice(-500)))}catch{}label();refresh();};
 document.addEventListener('click',e=>{const open=e.target.closest('[data-tc-open]');if(open){const j=jobs.find(x=>`${x.kind}:${x.id}`===open.dataset.tcOpen);if(j){panel?.remove();panel=null;navigate(link(j));}return;}if(e.target.closest('[data-tc-close]')){panel?.remove();panel=null;return;}if(e.target.closest('[data-tc-all]')){panel?.remove();panel=null;navigate('/tasks');return;}const f=e.target.closest('[data-tc-filter]');if(f){selected=f.dataset.tcFilter;page();return;}if(e.target.closest('[data-tc-more]')){pages+=1;refresh();return;}if(e.target.closest('[data-tc-refresh]'))refresh();});
 root?.addEventListener('input',e=>{if(e.target.matches('[data-tc-search]')){query=e.target.value;const pos=e.target.selectionStart;page();const input=root.querySelector('[data-tc-search]');input?.focus();input?.setSelectionRange(pos,pos);}});
 root?.addEventListener('change',e=>{if(e.target.matches('[data-tc-project]'))project=e.target.value;if(e.target.matches('[data-tc-type]'))type=e.target.value;page();});
 window.addEventListener('lblstdio:upload-task',e=>{if(e.detail.remove)uploads.delete(e.detail.id);else uploads.set(e.detail.id,{...e.detail});merge();label();renderPanel();page();});
 document.addEventListener('keydown',e=>{if(e.key==='Escape'){panel?.remove();panel=null;}});
 refresh();const timer=setInterval(refresh,4000);timer.unref?.();return {refresh};
}
