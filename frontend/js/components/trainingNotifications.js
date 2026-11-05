import {api} from '../api.js';
import {escapeHtml as esc} from '../utils/dom.js';
export function initTrainingNotifications(){
 const button=document.createElement('button');button.id='training-notifications';button.className='fixed top-2 right-4 z-40 text-xs px-3 py-2 rounded-lg border border-indigo-800 bg-zinc-900 text-indigo-200';button.textContent='🔔 Обучение';button.title='Результаты обучения всех проектов';document.body.append(button);
 let panel=null,jobs=[],seen=new Set();try{seen=new Set(JSON.parse(localStorage.getItem('lblstdio:training-notifications')||'[]'));}catch{}
 const terminal=()=>jobs.filter(j=>['COMPLETED','FAILED'].includes(j.status));
 const refreshLabel=()=>{const unread=terminal().filter(j=>!seen.has(j.id)).length;button.textContent=`🔔 Обучение${unread?' · '+unread:''}`;};
 function render(){if(!panel)return;panel.innerHTML=`<div style="display:flex;justify-content:space-between"><strong>Результаты обучения</strong><button data-training-close aria-label="Закрыть">×</button></div>${terminal().map(j=>`<a href="#/projects/${j.project_id}/models" data-training-project="${j.project_id}" data-training-model="${j.model_version_id||''}"><strong>${j.status==='COMPLETED'?'✓ Модель обучена':'! Обучение не завершено'}</strong><small>${esc(j.project_name)} · ${new Date(j.finished_at||j.created_at).toLocaleString('ru-RU')}</small>${j.error_message?`<small>${esc(j.error_message)}</small>`:''}</a>`).join('')||'<p style="padding:20px 0;color:#9badc9">Завершённых обучений пока нет</p>'}`;}
 button.onclick=()=>{if(panel){panel.remove();panel=null;return;}panel=document.createElement('div');panel.className='training-notification-panel';panel.setAttribute('role','dialog');panel.setAttribute('aria-label','Результаты обучения');document.body.append(panel);render();terminal().forEach(j=>seen.add(j.id));localStorage.setItem('lblstdio:training-notifications',JSON.stringify([...seen].slice(-500)));refreshLabel();panel.onclick=e=>{if(e.target.closest('[data-training-close]')){panel.remove();panel=null;return;}const link=e.target.closest('[data-training-project]');if(link){sessionStorage.setItem('lblstdio:open-model',JSON.stringify({project:link.dataset.trainingProject,model:link.dataset.trainingModel}));panel.remove();panel=null;window.dispatchEvent(new CustomEvent('training-result-open'));}};};
 async function poll(){try{jobs=await api.trainingQueue();refreshLabel();render();}catch{}}
 poll();const timer=setInterval(poll,30000);timer.unref?.();
 document.addEventListener('keydown',e=>{if(e.key==='Escape'){panel?.remove();panel=null;}});
}
