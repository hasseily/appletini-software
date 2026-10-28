/* MIT. Public scores are claims from an unauthenticated game client. */
export const BASE = '/leaderboards/starfall';
const json = (value, status = 200) => new Response(JSON.stringify(value), {
  status, headers: {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store'},
});
const BEST = `WITH players AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY name ORDER BY score DESC, submitted_at, run_id) AS personal
  FROM starfall_runs
), ranked AS (
  SELECT *, ROW_NUMBER() OVER (ORDER BY score DESC, submitted_at, run_id) AS rank
  FROM players WHERE personal=1
)`;
export function validate(b) {
  if (!b || typeof b !== 'object' || Array.isArray(b)) return 'Expected an object';
  if (typeof b.run_id !== 'string' || !/^[a-f0-9]{32}$/.test(b.run_id)) return 'Invalid run_id';
  if (typeof b.name !== 'string' || !/^[A-Z0-9][A-Z0-9 ._-]{0,11}$/.test(b.name) || b.name !== b.name.trim()) return 'Invalid name';
  if (typeof b.version !== 'string' || !/^[A-Za-z0-9._-]{1,24}$/.test(b.version)) return 'Invalid version';
  if (typeof b.platform !== 'string' || !/^[a-z0-9][a-z0-9_-]{0,23}$/.test(b.platform)) return 'Invalid platform';
  for (const [key, low, high] of [['score',0,9999999],['sector',1,256],['kills',0,999999]])
    if (!Number.isInteger(b[key]) || b[key] < low || b[key] > high) return `Invalid ${key}`;
  if (b.score > b.kills * 50000 + b.sector * 100000) return 'Implausible score';
  return null;
}
async function rate(request, env, kind, limit) {
  const minute = Math.floor(Date.now()/60000);
  const ip = request.headers.get('CF-Connecting-IP') || 'local';
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(kind+'\0'+ip));
  const key = [...new Uint8Array(hash)].map(x=>x.toString(16).padStart(2,'0')).join('');
  await env.DB.prepare('DELETE FROM starfall_rate WHERE minute < ?1').bind(minute-1440).run();
  const row = await env.DB.prepare(`INSERT INTO starfall_rate(rate_key,minute,hits) VALUES (?1,?2,1)
    ON CONFLICT(rate_key,minute) DO UPDATE SET hits=hits+1 RETURNING hits`).bind(key,minute).first();
  return row.hits <= limit;
}
async function readBody(request) {
  if (!/^application\/json(?:\s*;|$)/i.test(request.headers.get('Content-Type') || '')) throw new Error('JSON Content-Type required');
  if (Number(request.headers.get('Content-Length')) > 768) throw new Error('Body exceeds 768 bytes');
  const reader=request.body?.getReader();
  if (!reader) throw new Error('Empty body');
  let size=0;const parts=[];
  try {
    for (;;) {
      const {done,value}=await reader.read();if(done)break;
      size+=value.length;if(size>768)throw new Error('Body exceeds 768 bytes');parts.push(value);
    }
  } finally { await reader.cancel(); }
  const bytes=new Uint8Array(size);let at=0;
  for(const p of parts){bytes.set(p,at);at+=p.length;}
  return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
}
async function submit(request,env) {
  let b;
  try {b=await readBody(request);} catch {return json({error:'Invalid JSON request or body size'},400);}
  const error=validate(b);if(error)return json({error},400);
  if(!await rate(request,env,'submit',12))return json({error:'Submission rate exceeded'},429);
  const now=Math.floor(Date.now()/1000);
  await env.DB.prepare(`INSERT INTO starfall_runs(run_id,name,version,platform,score,sector,kills,submitted_at)
    VALUES (?1,?2,?3,?4,?5,?6,?7,?8) ON CONFLICT(run_id) DO NOTHING`)
    .bind(b.run_id,b.name,b.version,b.platform,b.score,b.sector,b.kills,now).run();
  const stored=await env.DB.prepare('SELECT * FROM starfall_runs WHERE run_id=?1').bind(b.run_id).first();
  for(const key of ['name','version','platform','score','sector','kills'])
    if(stored[key]!==b[key])return json({error:'run_id already belongs to a different run'},409);
  const best=await env.DB.prepare(BEST+' SELECT rank,score FROM ranked WHERE name=?1').bind(b.name).first();
  return json({run_id:b.run_id,platform:stored.platform,rank:best.rank,best_score:best.score,submitted_at:new Date(stored.submitted_at*1000).toISOString()});
}
async function scores(env) {
  const rows=await env.DB.prepare(BEST+' SELECT rank,name,score,sector,kills,version,platform,submitted_at FROM ranked ORDER BY rank LIMIT 10').all();
  return rows.results.map(r=>({...r,submitted_at:new Date(r.submitted_at*1000).toISOString()}));
}
const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export async function handleStarfall(request,env) {
  const url=new URL(request.url);
  if(url.pathname!==BASE&&!url.pathname.startsWith(BASE+'/'))return null;
  try {
    if(url.pathname===BASE+'/api/runs'&&request.method==='POST')return await submit(request,env);
    if(request.method!=='GET')return json({error:'Method not allowed'},405);
    if(!await rate(request,env,'read',120))return json({error:'Read rate exceeded'},429);
    if(url.pathname===BASE+'/api/run-id')return json({run_id:crypto.randomUUID().replaceAll('-','')});
    if(url.pathname===BASE+'/api/ladder')return json({scores:await scores(env)});
    if(url.pathname===BASE||url.pathname===BASE+'/') {
      const rows=await scores(env);
      return new Response(`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>STARFALL leaderboard</title>
<body><h1>STARFALL leaderboard</h1><p>Best run for each player name. Scores are submitted by the game; player names have no accounts.</p>
<table><tr><th>Rank</th><th>Player</th><th>Score</th><th>Sector</th><th>Kills</th><th>Platform</th><th>UTC</th></tr>
${rows.map(r=>`<tr><td>${r.rank}</td><td>${escape(r.name)}</td><td>${r.score}</td><td>${r.sector}</td><td>${r.kills}</td><td>${escape(r.platform)}</td><td>${escape(r.submitted_at)}</td></tr>`).join('\n')}</table>
<p>Play offline whenever the network is unavailable. Rankings use the server's submission time.</p><p><a href="/">Appletini</a></p></body></html>`,
        {headers:{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','Content-Security-Policy':"default-src 'none'; base-uri 'none'; frame-ancestors 'none'"}});
    }
    return json({error:'Not found'},404);
  } catch {return json({error:'Ranking service unavailable; continue offline'},503);}
}
export default {async fetch(request,env){return await handleStarfall(request,env) || json({error:'Not found'},404);}};
