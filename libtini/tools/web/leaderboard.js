// SPDX-License-Identifier: GPL-3.0-only
// The browser submits the same game's final state through its own HTTPS client.
export const PLATFORM = 'web';
export function makeSubmission(run, name, run_id) {
  name = name.trim().toUpperCase();
  if (!/^[A-Z0-9][A-Z0-9 ._-]{0,11}$/.test(name)) throw Error('Use 1–12 letters, numbers, spaces, . _ or -.');
  if (!/^[a-f0-9]{32}$/.test(run_id)) throw Error('Invalid server run ID.');
  return Object.freeze({run_id, name, version:run.version, platform:PLATFORM,
    score:run.score, sector:run.sector, kills:run.kills});
}
export function snapshot(read, info) {
  if (read(info.mode_address, 1)[0] !== 2 || read(info.stage_address, 1)[0] !== 7) return null;
  const b = read(info.state_address, 23);
  if (b.length !== 23 || b[21] !== 1) return null;
  const v = new DataView(b.buffer, b.byteOffset, b.byteLength);
  return {version:info.version, score:v.getUint32(4,true), kills:v.getUint16(10,true), sector:b[22]+1};
}
async function getJSON(fetcher, url, options) {
  const response = await fetcher(url, options);
  const body = await response.json();
  if (!response.ok) throw Error(body.error || 'HTTP '+response.status);
  return body;
}
// Each finished run owns one immutable POST body, including after a lost reply.
export class Submission {
  constructor(run, endpoint, fetcher=fetch) { this.run=run;this.endpoint=endpoint;this.fetcher=fetcher;this.payload=null; }
  async send(name) {
    if (!this.payload) {
      // Check the name before consuming a server ID.
      makeSubmission(this.run,name,'0'.repeat(32));
      const id = await getJSON(this.fetcher,this.endpoint+'/api/run-id');
      this.payload=makeSubmission(this.run,name,id.run_id);
    }
    const result=await getJSON(this.fetcher,this.endpoint+'/api/runs',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(this.payload)});
    if (result.platform !== PLATFORM) throw Error('The server returned a different platform.');
    return result;
  }
}
export function createLeaderboard(read, info, parent) {
  if (!info) return null;
  const box=document.createElement('section');box.className='leaderboard';
  box.innerHTML='<h2>STARFALL online leaderboard</h2><p class="score-status" role="status">Finish a run to submit your score.</p>'+
    '<form><label>Public game name <input name="name" maxlength="12" value="PLAYER" autocomplete="off" spellcheck="false" required></label>'+
    '<button type="submit" disabled>Submit run</button> <button type="button">Top 10</button></form>'+
    '<p>Browser runs use platform <code>web</code>. Scores and names are public.</p><div class="scores"></div>';
  parent.append(box);
  const form=box.querySelector('form'),name=form.elements.name,submit=form.querySelector('[type=submit]');
  const message=box.querySelector('.score-status'),rows=box.querySelector('.scores');
  let current=null,ended=false,busy=false,generation=0;
  function reset() { generation++;current=null;ended=false;busy=false;name.disabled=false;submit.disabled=true;message.textContent='Finish a run to submit your score.'; }
  function poll() {
    const run=snapshot(read,info);
    if (!run) { if (ended) reset();return; }
    if (ended) return;
    ended=true;current=new Submission(run,info.endpoint);submit.disabled=false;
    message.textContent='Final score: '+run.score+'. Enter a name, then submit.';
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault();if (!current||busy)return;
    const active=current,stamp=generation;busy=true;submit.disabled=true;name.disabled=true;
    message.textContent='Sending run…';
    try {
      const result=await active.send(name.value);
      if (stamp===generation)message.textContent='Submitted as web. Best rank: '+result.rank+'.';
    } catch(error) { if(stamp===generation)message.textContent=error.message+' Press Submit run to retry.'; }
    finally { if(stamp===generation){busy=false;submit.disabled=false;name.disabled=!!active.payload;} }
  });
  form.querySelector('[type=button]').onclick=async()=>{
    try {
      const data=await getJSON(fetch,info.endpoint+'/api/ladder');
      const table=document.createElement('table');
      for (const fields of [['Rank','Name','Score','Platform'],...data.scores.map(r=>[r.rank,r.name,r.score,r.platform])]) {
        const row=table.insertRow();for (const value of fields)row.insertCell().textContent=String(value);
      }
      rows.replaceChildren(table);
    } catch(error) { rows.textContent=error.message; }
  };
  return {poll,reset,open(){if(!ended)return false;box.scrollIntoView({block:'center'});name.focus();return true;}};
}
