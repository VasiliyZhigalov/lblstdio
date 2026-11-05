import test from 'node:test';
import assert from 'node:assert/strict';
import {Window} from 'happy-dom';

test('task center displays live work, filters it and opens its source', async () => {
 const win = new Window({url:'http://localhost:8000/#/tasks'});
 win.document.write('<section id="view-tasks"></section>');
 for(const [key,value] of Object.entries({window:win,document:win.document,location:win.location,localStorage:win.localStorage,CustomEvent:win.CustomEvent})) Object.defineProperty(globalThis,key,{configurable:true,writable:true,value});
 const {api}=await import('../api.js');
 const {initTaskCenter}=await import('./taskCenter.js');
 api.tasks=async()=>({items:[{id:'job1',project_id:'p1',project_name:'Склад',kind:'auto_label',title:'Авторазметка',status:'RUNNING',raw_status:'RUNNING',processed:3,total:10,unit:'кадров',predictions:7,created_at:'2026-10-27T08:00:00Z'}],has_more:false});
 let route;
 initTaskCenter({navigate:path=>{route=path;}});
 await new Promise(resolve=>setTimeout(resolve,0));
 assert.match(win.document.querySelector('#view-tasks').textContent,/3 из 10 кадров/);
 assert.match(win.document.querySelector('#view-tasks').textContent,/30%/);
 win.document.querySelector('[data-tc-filter="FAILED"]').click();
 assert.match(win.document.querySelector('#view-tasks').textContent,/не найдены/);
 win.document.querySelector('[data-tc-filter="ALL"]').click();
 win.document.querySelector('[data-tc-open]').click();
 assert.equal(route,'/projects/p1/models?section=auto&task=job1');
 win.close();
});
