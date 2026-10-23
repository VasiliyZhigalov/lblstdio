import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import { Window } from "happy-dom";

test("queue completes frames without reviewer, skips without a reason, and preserves drafts on save failure", async () => {
  const win = new Window({ url: "http://127.0.0.1:8000/#/projects/p/annotate" });
  win.document.write(fs.readFileSync(new URL("../../index.html", import.meta.url), "utf8"));
  for(const [name,value] of Object.entries({window:win,history:win.history,location:win.location,document:win.document,HTMLElement:win.HTMLElement,localStorage:win.localStorage,sessionStorage:win.sessionStorage,navigator:win.navigator})) Object.defineProperty(globalThis,name,{configurable:true,writable:true,value});
  const {store}=await import("../store.js");
  const {api}=await import("../api.js?v=annotation-queue-20261022e");
  const {initAnnotationQueue}=await import("./annotationQueue.js");
  const tasks=[{id:"i1",state:"QUEUED"},{id:"i2",state:"QUEUED"}];
  const actions=[];let failedSave=false,saves=0,hub;
  api.annotationQueue=async()=>({items:tasks.map(t=>({image_id:t.id,state:t.state,mine:t.state==="WORKING",image:{id:t.id,file_name:t.id+".png",width:100,height:80,status:"UNANNOTATED"}})),total:2,counts:Object.fromEntries(["QUEUED","WORKING","DONE","ISSUE"].map(state=>[state,tasks.filter(t=>t.state===state).length]))});
  api.claimAnnotation=async(_pid,id)=>{const t=id?tasks.find(t=>t.id===id):tasks.find(t=>t.state==="QUEUED");if(!t)return{image_id:null};t.state="WORKING";return{image_id:t.id,mine:true,readonly:false,state:t.state,revision:0};};
  api.annotationQueueAction=async(_pid,id,action,reason)=>{actions.push({id,action,reason});const t=tasks.find(t=>t.id===id);t.state={finish:"DONE",skip:"QUEUED",release:"QUEUED",heartbeat:"WORKING"}[action];return{image_id:id,state:t.state,revision:1};};
  store.patch({currentProject:{id:"p",task_type:"DETECTION",name:"Test"},projectTab:"annotate",classes:[],currentImage:null,hasUnsavedChanges:false,annotationReadonly:false,annotations:[]});
  hub=initAnnotationQueue({
    openImage:async id=>{await hub.beforeOpen(id);store.patch({currentImage:{id,file_name:id+".png",width:100,height:80},annotations:[],hasUnsavedChanges:false});hub.afterOpen();},
    save:async()=>{if(failedSave){const err=new Error("Server unavailable");err.status=500;throw err;}saves++;store.set("hasUnsavedChanges",false);},confirmModel:async()=>{},toast:()=>{},fit:()=>{}
  });
  const tick=()=>new Promise(r=>setTimeout(r,30));
  const click=selector=>win.document.querySelector(selector).click();
  await hub.showHome();
  assert.match(win.document.querySelector(".aq-counts").textContent,/Ожидают разметки2/);
  click('[data-aq="start"]');await tick();
  assert.equal(store.get("currentImage").id,"i1");
  assert.equal(win.document.querySelector("#aq-finish").disabled,true);
  store.patch({annotations:[{id:"box",verification_status:"VERIFIED"}],hasUnsavedChanges:true});
  const loginOverlay=win.document.createElement('div');loginOverlay.className='auth-screen';win.document.body.append(loginOverlay);
  win.document.body.dispatchEvent(new win.KeyboardEvent('keydown',{code:'Space',bubbles:true}));await tick();
  assert.equal(tasks[0].state,'WORKING');loginOverlay.remove();
  win.document.body.dispatchEvent(new win.KeyboardEvent('keydown',{code:'Space',bubbles:true}));await tick();
  assert.match(win.document.querySelector("#aq-finish").textContent,/Пробел/);
  assert.match(win.document.querySelector("#aq-trash").textContent,/Delete/);
  assert.match(win.document.querySelector("#aq-clear").textContent,/R/);
  assert.match(win.document.querySelector("#aq-background").textContent,/∅ Фон/);
  assert.equal(saves,1);
  assert.equal(tasks[0].state,"DONE");
  assert.equal(store.get("currentImage").id,"i2");
  click('#aq-skip');await tick();
  assert.equal(tasks[1].state,"QUEUED");
  assert.equal(actions.find(a=>a.action==="skip").reason,undefined);
  click('[data-aq="start"]');await tick();
  failedSave=true;store.patch({annotations:[{id:"unsaved",verification_status:"VERIFIED"}],hasUnsavedChanges:true});
  await new Promise(r=>setTimeout(r,1100));
  assert.equal(store.get("annotationReadonly"),true);
  assert.equal(win.document.querySelector('#aq-finish').disabled,true);
  assert.match(localStorage.getItem('lblstdio:annotation-draft:p:i2'),/unsaved/);
  win.happyDOM.abort();
});
