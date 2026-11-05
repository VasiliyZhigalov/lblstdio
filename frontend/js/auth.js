import {api} from './api.js';
import {escapeHtml as esc} from './utils/dom.js';
let user=null,screen=null,manager=null,reauth=false,report=()=>{};
export const isAnnotator=()=>user?.role==='ANNOTATOR';
export const authUser=()=>user;
const error=(root,message)=>{const el=root.querySelector('.auth-error');if(el)el.textContent=message;};
function account(beforeLogout){
 document.querySelector('.auth-account')?.remove();
 const el=document.createElement('div');el.className='auth-account';el.innerHTML=`<span>${esc(user.username)} · ${user.role==='ADMIN'?'Админ':'Разметчик'}</span>${user.role==='ADMIN'?'<button data-auth-users>Пользователи</button>':''}<button data-auth-logout>Выйти</button>`;document.body.append(el);
 el.querySelector('[data-auth-users]')?.addEventListener('click',()=>showUsers().catch(e=>report(e.message)));
 el.querySelector('[data-auth-logout]').onclick=async()=>{try{await beforeLogout?.();await api.authLogout();location.reload();}catch(e){report(e.message);}};
}
function loginForm(setup,done){
 screen?.remove();document.body.classList.add('auth-pending');screen=document.createElement('div');screen.className='auth-screen';screen.innerHTML=`<form class="auth-card"><small>LBL_STDIO</small><h1>${setup?'Создать администратора':'Вход в приложение'}</h1><p>${setup?'Первый пользователь станет администратором. Затем можно добавить разметчиков.':'Введите логин и пароль, выданные администратором.'}</p><label>Логин<input name="username" autocomplete="username" required minlength="3" maxlength="40"></label><label>Пароль<input name="password" type="password" autocomplete="${setup?'new-password':'current-password'}" required minlength="${setup?'8':'1'}" maxlength="128"></label><div class="auth-error" role="status"></div><button type="submit">${setup?'Создать и войти':'Войти'}</button></form>`;document.body.append(screen);screen.querySelector('input').focus();
 screen.querySelector('form').onsubmit=async e=>{e.preventDefault();const form=e.currentTarget,button=form.querySelector('button');if(button.disabled)return;button.disabled=true;error(form,'');try{const payload={username:form.elements.username.value.trim(),password:form.elements.password.value};user=await (setup?api.authSetup(payload):api.authLogin(payload));form.elements.password.value='';if(reauth){location.reload();return;}screen.remove();screen=null;document.body.classList.remove('auth-pending');document.body.dataset.role=user.role;done(user);}catch(err){error(form,err.message);button.disabled=false;}};
}
export async function initAuth({beforeLogout,notify}={}){
 report=notify||(()=>{});
 document.body.classList.add('auth-pending');
 try{
  const status=await api.authStatus();
  if(status.enabled===false){document.body.classList.remove('auth-pending');return null;}
  if(status.enabled!==true)throw Error('Не удалось проверить вход. Обновите страницу.');
  try{user=await api.authMe();}catch(err){if(err.status!==401)throw err;}
  if(!user)await new Promise(resolve=>loginForm(status.needs_setup,resolve));
  document.body.dataset.role=user.role;document.body.classList.remove('auth-pending');account(beforeLogout);
  window.addEventListener('auth-required',()=>{if(screen)return;reauth=true;manager?.remove();manager=null;loginForm(false,()=>{});});
  return user;
 }catch(err){screen=document.createElement('div');screen.className='auth-screen';screen.innerHTML=`<div class="auth-card"><h1>Не удалось подключиться</h1><p>${esc(err.message)}</p><button>Повторить</button></div>`;screen.querySelector('button').onclick=()=>location.reload();document.body.append(screen);return new Promise(()=>{});}
}
async function showUsers(){
 const users=await api.authUsers();manager?.remove();manager=document.createElement('div');manager.className='auth-dialog-backdrop';manager.innerHTML=`<section class="auth-users" role="dialog" aria-modal="true" aria-label="Пользователи"><button class="auth-close">Закрыть</button><h2>Пользователи</h2><p>Админ управляет проектами и системой. Разметчик работает только с очередью и своими кадрами.</p><table><thead><tr><th>Логин</th><th>Роль</th><th>Доступ</th><th></th></tr></thead><tbody>${users.map(u=>`<tr><td>${esc(u.username)}${u.id===user.id?' · вы':''}</td><td><select data-auth-role="${u.id}" ${u.id===user.id?'disabled':''}><option value="ADMIN" ${u.role==='ADMIN'?'selected':''}>Админ</option><option value="ANNOTATOR" ${u.role==='ANNOTATOR'?'selected':''}>Разметчик</option></select></td><td><button data-auth-toggle="${u.id}" data-active="${u.is_active}" ${u.id===user.id?'disabled':''}>${u.is_active?'Отключить':'Включить'}</button></td><td><button data-auth-password="${u.id}">Задать пароль</button></td></tr>`).join('')}</tbody></table><h3>Добавить пользователя</h3><form class="auth-add"><label>Логин<input name="username" required minlength="3" maxlength="40" autocomplete="off"></label><label>Пароль<input name="password" type="password" required minlength="8" maxlength="128" autocomplete="new-password"></label><label>Роль<select name="role"><option value="ANNOTATOR">Разметчик</option><option value="ADMIN">Админ</option></select></label><button type="submit">Добавить</button></form><div class="auth-error" role="status"></div><p>Отключение пользователя, смена роли или пароля завершают его активные сеансы.</p></section>`;document.body.append(manager);
 manager.querySelector('.auth-close').onclick=()=>{manager.remove();manager=null;};
 manager.querySelector('form').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget,b=f.querySelector('button');if(b.disabled)return;b.disabled=true;try{await api.authCreateUser({username:f.elements.username.value.trim(),password:f.elements.password.value,role:f.elements.role.value});f.elements.password.value='';await showUsers();}catch(err){error(manager,err.message);b.disabled=false;}};
 manager.querySelectorAll('[data-auth-role]').forEach(el=>el.onchange=async()=>{el.disabled=true;try{await api.authUpdateUser(el.dataset.authRole,{role:el.value});await showUsers();}catch(err){error(manager,err.message);el.disabled=false;}});
 manager.querySelectorAll('[data-auth-toggle]').forEach(el=>el.onclick=async()=>{el.disabled=true;try{await api.authUpdateUser(el.dataset.authToggle,{is_active:el.dataset.active!=='true'});await showUsers();}catch(err){error(manager,err.message);el.disabled=false;}});
 manager.querySelectorAll('[data-auth-password]').forEach(el=>el.onclick=()=>{const target=el.dataset.authPassword;manager.querySelector('section').innerHTML=`<h2>Новый пароль</h2><form><label>Пароль<input name="password" type="password" required minlength="8" maxlength="128" autocomplete="new-password"></label><div class="auth-error" role="status"></div><button type="submit">Сохранить</button> <button type="button" id="auth-back">Назад</button></form>`;manager.querySelector('#auth-back').onclick=()=>showUsers();manager.querySelector('form').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget,b=f.querySelector('button');if(b.disabled)return;b.disabled=true;try{await api.authUpdateUser(target,{password:f.elements.password.value});f.elements.password.value='';if(target===user.id)location.reload();else await showUsers();}catch(err){error(manager,err.message);b.disabled=false;}};});
}
