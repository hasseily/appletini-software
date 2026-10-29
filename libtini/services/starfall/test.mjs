import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {handleStarfall,BASE,validate} from './worker.mjs';
const db=new DatabaseSync(':memory:');
db.exec(readFileSync(new URL('./schema.sql',import.meta.url),'utf8'));
const env={DB:{prepare(sql){let args=[];return {
  bind(...v){args=v;return this;},
  async run(){return db.prepare(sql).run(...args);},
  async first(){return db.prepare(sql).get(...args)||null;},
  async all(){return {results:db.prepare(sql).all(...args)};},
};}}};
let seq=0;
const run=(name='ACE',score=1000,platform='appletini')=>({run_id:(++seq).toString(16).padStart(32,'0'),name,version:'1.0-net1',platform,score,sector:2,kills:10});
async function request(path,method='GET',body,ip='192.0.2.1',type='application/json') {
  return handleStarfall(new Request('https://appletini.org'+path,{method,
    headers:{'CF-Connecting-IP':ip,'Content-Type':type},body:body===undefined?undefined:typeof body==='string'?body:JSON.stringify(body)}),env);
}
let r=await request(BASE+'/api/run-id');assert.equal(r.status,200);assert.match((await r.json()).run_id,/^[a-f0-9]{32}$/);
const ace=run();r=await request(BASE+'/api/runs','POST',ace);assert.equal(r.status,200);
const first=await r.json();assert.equal(first.platform,'appletini');assert.equal(first.rank,1);assert.match(first.submitted_at,/Z$/);
r=await request(BASE+'/api/runs','POST',ace);assert.deepEqual(await r.json(),first);
r=await request(BASE+'/api/runs','POST',{...ace,score:1001});assert.equal(r.status,409);
r=await request(BASE+'/api/runs','POST',{...ace,platform:'web'});assert.equal(r.status,409);
assert.equal(validate({...run(),platform:'emulator'}),null);
for(const bad of [null,[],{}, {...run(),platform:undefined}, {...run(),platform:''}, {...run(),platform:'Web'},
  {...run(),platform:'<script>'}, {...run(),platform:'x'.repeat(25)}, {...run(),platform:[]}, {...run(),run_id:['f'.repeat(32)]}, {...run(),name:'<script>'},
  {...run(),name:'PRIVATE NAME TOO LONG'}, {...run(),score:-1}, {...run(),score:1.1},
  {...run(),score:9999999,kills:0,sector:1}, {...run(),sector:0}, {...run(),kills:1e8}, {...run(),version:'<x>'}]) {
  assert.ok(validate(bad));r=await request(BASE+'/api/runs','POST',bad);assert.equal(r.status,400);
}
r=await request(BASE+'/api/runs','POST','not json');assert.equal(r.status,400);
r=await request(BASE+'/api/runs','POST',run(),'192.0.2.1','text/plain');assert.equal(r.status,400);
r=await request(BASE+'/api/runs','POST',' '.repeat(769));assert.equal(r.status,400);
for(const score of [2000,500]) {r=await request(BASE+'/api/runs','POST',run('ACE',score));assert.equal(r.status,200);}
r=await request(BASE+'/api/runs','POST',run('BOB',1500,'web'));assert.equal(r.status,200);
r=await request(BASE+'/api/ladder');const ladder=await r.json();
assert.equal(ladder.scores.length,2);assert.deepEqual(ladder.scores.map(x=>x.platform),['appletini','web']);assert.deepEqual(ladder.scores.map(x=>[x.name,x.score,x.rank]),[['ACE',2000,1],['BOB',1500,2]]);
r=await request(BASE);assert.equal(r.status,200);assert.match(r.headers.get('Content-Type'),/^text\/html/);
assert.match(await r.text(),/STARFALL leaderboard/);
r=await request(BASE+'/api/runs','PUT',run());assert.equal(r.status,405);
assert.equal(await request('/unrelated'),null);
const origin='https://html.itch.zone';
r=await handleStarfall(new Request('https://appletini.org'+BASE+'/api/runs',{
  method:'OPTIONS',headers:{Origin:origin,'Access-Control-Request-Method':'POST',
    'Access-Control-Request-Headers':'content-type'},
}),{});
assert.equal(r.status,204);assert.equal(await r.text(),'');
assert.equal(r.headers.get('Access-Control-Allow-Origin'),'*');
assert.match(r.headers.get('Access-Control-Allow-Methods'),/POST/);
assert.equal(r.headers.get('Access-Control-Allow-Headers'),'Content-Type');
assert.equal(r.headers.has('Access-Control-Allow-Credentials'),false);
for(const [path,method,body,status] of [
  [BASE+'/api/run-id','GET',undefined,200],
  [BASE+'/api/ladder','GET',undefined,200],
  [BASE+'/api/runs','POST',run('ITCH',1600,'web'),200],
  [BASE+'/api/runs','POST',{},400],
  [BASE+'/api/missing','GET',undefined,404],
]) {
  r=await handleStarfall(new Request('https://appletini.org'+path,{method,
    headers:{Origin:origin,'Content-Type':'application/json','CF-Connecting-IP':'192.0.2.60'},
    body:body===undefined?undefined:JSON.stringify(body)}),env);
  assert.equal(r.status,status);assert.equal(r.headers.get('Access-Control-Allow-Origin'),'*');
}
r=await request(BASE);assert.equal(r.headers.has('Access-Control-Allow-Origin'),false);
for(let i=0;i<12;++i){r=await request(BASE+'/api/runs','POST',run('RATE',i),'192.0.2.50');assert.equal(r.status,200);}
r=await request(BASE+'/api/runs','POST',run('RATE',13),'192.0.2.50');assert.equal(r.status,429);
for(let i=0;i<120;++i){r=await request(BASE+'/api/run-id','GET',undefined,'192.0.2.51');assert.equal(r.status,200);}
r=await request(BASE+'/api/run-id','GET',undefined,'192.0.2.51');assert.equal(r.status,429);
const old=new DatabaseSync(':memory:');
old.exec(`CREATE TABLE starfall_runs(run_id TEXT PRIMARY KEY); INSERT INTO starfall_runs(run_id) VALUES ('legacy')`);
old.exec(readFileSync(new URL('./migrate_platform.sql',import.meta.url),'utf8'));
assert.equal(old.prepare('SELECT platform FROM starfall_runs').get().platform,'unknown');old.close();
console.log('PASS cross-origin preflight and API responses, platform validation/storage/idempotency/ladder and migration; actual SQLite schema and Worker: validation, idempotency, UTC, best-per-player ranks, HTML and rate limits');
