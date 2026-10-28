import assert from 'node:assert/strict';
import {makeSubmission,snapshot,Submission} from '../tools/web/leaderboard.js';
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
console.log('PASS browser platform=web, real state snapshot, name rules, lost-response retry identity');
