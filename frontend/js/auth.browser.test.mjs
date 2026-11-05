import assert from 'node:assert/strict';
import test from 'node:test';
import {Window} from 'happy-dom';
function dom(){const win=new Window({url:'http://127.0.0.1:8000/'});win.document.write('<div id="app"></div>');for(const [name,value] of Object.entries({window:win,document:win.document,location:win.location,HTMLElement:win.HTMLElement,CustomEvent:win.CustomEvent}))Object.defineProperty(globalThis,name,{configurable:true,writable:true,value});return win;}
const tick=()=>new Promise(r=>setTimeout(r,20));
test('first-run form creates administrator and does not store the password',async()=>{
 const win=dom();const {api}=await import('./api.js');const {initAuth}=await import('./auth.js?test=setup');
 let payload;api.authStatus=async()=>({enabled:true,needs_setup:true});api.authMe=async()=>{const e=new Error('login');e.status=401;throw e;};api.authSetup=async body=>{payload=body;return {id:'admin-id',username:body.username,role:'ADMIN'};};
 const boot=initAuth();await tick();assert.equal(win.document.body.classList.contains('auth-pending'),true);
 const form=win.document.querySelector('.auth-card');assert.match(form.textContent,/Создать администратора/);
 form.elements.username.value='admin';form.elements.password.value='test-password';form.dispatchEvent(new win.Event('submit',{bubbles:true,cancelable:true}));await boot;
 assert.equal(payload.username,'admin');assert.equal(win.document.body.dataset.role,'ADMIN');assert.equal(win.document.querySelector('.auth-screen'),null);assert.ok(win.document.querySelector('[data-auth-users]'));
 assert.equal(win.localStorage.length,0);assert.equal(win.sessionStorage.length,0);
 win.happyDOM.abort();
});
test('annotator account has no user management and expired session shows login',async()=>{
 const win=dom();const {api}=await import('./api.js');const {initAuth,isAnnotator}=await import('./auth.js?test=worker');
 api.authStatus=async()=>({enabled:true,needs_setup:false});api.authMe=async()=>({id:'worker-id',username:'worker',role:'ANNOTATOR'});
 await initAuth();assert.equal(isAnnotator(),true);assert.equal(win.document.body.dataset.role,'ANNOTATOR');assert.equal(win.document.querySelector('[data-auth-users]'),null);
 win.dispatchEvent(new win.CustomEvent('auth-required'));assert.equal(win.document.body.classList.contains('auth-pending'),true);assert.ok(win.document.querySelector('input[type=password]'));
 win.happyDOM.abort();
});
