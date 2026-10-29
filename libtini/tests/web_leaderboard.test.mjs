import assert from 'node:assert/strict';
import {makeSubmission,snapshot,Submission,createLeaderboard} from '../tools/web/leaderboard.js';
const run={version:'1.0-net1',platform:'appletini',score:1234,sector:2,kills:10};
assert.equal(makeSubmission(run,'web player','1'.repeat(32)).platform,'web');
assert.equal(makeSubmission(run,'web player','1'.repeat(32)).name,'WEB PLAYER');
assert.throws(()=>makeSubmission(run,'bad<>','1'.repeat(32)));
const bytes=new Uint8Array(23),v=new DataView(bytes.buffer);v.setUint32(4,1234,true);v.setUint16(10,10,true);bytes[21]=1;bytes[22]=1;
const info={version:run.version,mode_address:1,stage_address:2,state_address:3};
const read=(a,n)=>a===1?Uint8Array.of(2):a===2?Uint8Array.of(7):bytes;
assert.deepEqual(snapshot(read,info),{version:run.version,score:1234,sector:2,kills:10});bytes[21]=0;assert.equal(snapshot(read,info),null);
let ids=0,bodies=[];
const fake=async(url,options)=>{
  if(url.endsWith('/api/run-id')){ids++;return Response.json({run_id:'1'.repeat(32)});}
  const body=JSON.parse(options.body);bodies.push(options.body);assert.equal(body.platform,'web');
  if(bodies.length===1)throw Error('Lost response');
  return Response.json({platform:'web',rank:7});
};
const session=new Submission(run,'/leaderboards/starfall',fake);
await assert.rejects(session.send('WEBTEST'),/Lost response/);
assert.equal((await session.send('CHANGED')).rank,7);assert.equal(ids,1);assert.equal(bodies[0],bodies[1]);

// The name field is outside the fullscreen game container. Scrolling and focus
// must wait for the actual exit, and for the next normal-layout frame.
const calls=[],callbacks=[];
const name={focus(options){calls.push(['focus',options]);}};
const submit={},message={},rows={};
const form={elements:{name},querySelector:()=>submit,addEventListener(){}};
const box={querySelector(selector){return selector==='form'?form:selector==='.score-status'?message:rows;},
  scrollIntoView(options){calls.push(['scroll',options]);}};
let exit;
globalThis.document={createElement:()=>box,fullscreenElement:{},exitFullscreen(){
  calls.push(['exit']);return new Promise(resolve=>{exit=()=>{document.fullscreenElement=null;resolve();};});
}};
globalThis.requestAnimationFrame=callback=>callbacks.push(callback);
const panel=createLeaderboard(read,{...info,endpoint:'/leaderboards/starfall'},{append(){}});
assert.equal(panel.open(),false);assert.deepEqual(calls,[]);
bytes[21]=1;panel.poll();
assert.equal(panel.open(),true);
assert.deepEqual(calls,[['exit']]);
assert.equal(panel.open(),true);assert.equal(calls.length,1);
exit();await new Promise(resolve=>setImmediate(resolve));
assert.deepEqual(calls,[['exit']]);assert.equal(callbacks.length,1);
callbacks.shift()();await new Promise(resolve=>setImmediate(resolve));
assert.deepEqual(calls,[['exit'],['scroll',{block:'center',behavior:'instant'}],['focus',{preventScroll:true}]]);

// Windowed play still scrolls, and a reset during the exit must not steal focus.
calls.length=0;
assert.equal(panel.open(),true);assert.deepEqual(calls,[]);
callbacks.shift()();await new Promise(resolve=>setImmediate(resolve));
assert.equal(calls[0][0],'scroll');assert.equal(calls[1][0],'focus');
calls.length=0;document.fullscreenElement={};
panel.open();panel.reset();exit();await new Promise(resolve=>setImmediate(resolve));
callbacks.shift()();await new Promise(resolve=>setImmediate(resolve));
assert.deepEqual(calls,[['exit']]);assert.equal(panel.open(),false);

// A failed exit is handled, with a visible retry instruction, not a rejected task.
panel.poll();document.fullscreenElement={};
document.exitFullscreen=async()=>{throw Error('Exit failed');};
assert.equal(panel.open(),true);await new Promise(resolve=>setImmediate(resolve));
assert.match(message.textContent,/Exit fullscreen.*press N/i);
assert.equal(callbacks.length,0);
delete globalThis.document;delete globalThis.requestAnimationFrame;
console.log('PASS browser platform=web, real state snapshot, name rules, lost-response retry identity; fullscreen exit before scroll/focus, windowed open, reset during exit and rejected exit');
