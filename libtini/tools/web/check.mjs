// SPDX-License-Identifier: GPL-3.0-only
// Headless run of a built browser player under Node, for tests/web_validate.py.
// Usage: node check.mjs <build/web/game> <profile 0|1> <script.json>
// The script is a list of {"frames": n} and {"input": [kind, x, y]} steps.
// Prints JSON: a checkpoint per frames step (ticks, PC, AUX $2000-$9FFF and
// RGBA frame SHA-256), the SHA-256 of all mixed PCM, and the host time with
// the part spent mixing speech.
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';

const [directory, profile, scriptPath] = process.argv.slice(2);
const {default: createPlayer} = await import(pathToFileURL(join(directory, 'player.js')).href);
const M = await createPlayer();
const game = JSON.parse(readFileSync(join(directory, 'game.json'), 'utf8'));
const files = readFileSync(join(directory, 'game.bin'));
const script = JSON.parse(readFileSync(scriptPath, 'utf8'));
const f = (name, result, args) => M.cwrap(name, result, args);
const api = {
  create: f('tw_create', 'number', ['number', 'string']),
  volume: f('tw_volume', 'number', ['string', 'string']),
  file: f('tw_file', 'number', ['string', 'number', 'number', 'number', 'number']),
  launch: f('tw_launch', 'number', ['number', 'number']),
  boot: f('tw_boot', 'number', ['string', 'number', 'number', 'number', 'number']),
  run: f('tw_run', 'number', ['number']),
  result: f('tw_result', 'number', []),
  error: f('tw_error', 'string', []),
  get: f('tw_get', 'number', ['string']),
  input: f('tw_input', 'number', ['string', 'number', 'number']),
  read: f('tw_read', 'number', ['number', 'number', 'number', 'number']),
  audioFrames: f('tw_audio_frames', 'number', []),
  audioData: f('tw_audio_data', 'number', []),
  eventCount: f('tw_event_count', 'number', []),
  eventData: f('tw_event_data', 'number', []),
  audioTake: f('tw_audio_take', null, []),
  speechStart: f('tw_speech_start', null, ['number', 'number', 'number', 'number']),
  speechRender: f('tw_speech_render', null, ['number', 'number', 'number', 'number']),
  screen: f('tw_screen', 'number', []),
};
const ok = result => {
  if (!result) throw Error(api.error());
  return result;
};
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
function withBytes(bytes, use) {
  const pointer = M._malloc(Math.max(1, bytes.length));
  M.HEAPU8.set(bytes, pointer);
  const result = use(pointer);
  M._free(pointer);
  return result;
}

if (game.boot) {
  const read = name => readFileSync(join(directory, game.boot[name].path));
  M.FS.writeFile('/apple2e.rom', read('apple2e.rom'));
  M.FS.writeFile('/disk.po', read('disk.po'));
  ok(api.create(Number(profile), '/apple2e.rom'));
  const slot = read('c700.bin'), c8 = read('c800.bin');
  withBytes(slot, p => withBytes(c8, q => ok(api.boot('/disk.po', p, slot.length, q, c8.length))));
} else {
  ok(api.create(Number(profile), ''));
  ok(api.volume(game.volume, game.system));
  for (const entry of game.files) {
    const bytes = files.subarray(entry.offset, entry.offset + entry.length);
    withBytes(bytes, p => ok(api.file(entry.name, entry.type, entry.aux, p, bytes.length)));
  }
  const system = game.files.find(entry => entry.name === game.system);
  withBytes(files.subarray(system.offset, system.offset + system.length),
            p => ok(api.launch(p, system.length)));
}
// Gain 1: the native worker's reference mix, which tests/web_validate.py compares.
api.speechStart(api.get('clock_hz'), api.get('speech_xck_hz'), api.get('audio_origin'), 1);

const pcm = createHash('sha256');
let pcmFrames = 0, frames = 0, stopped = null, speechSeconds = 0;
const checkpoints = [];
const started = performance.now();
for (const step of script) {
  if (step.input) {
    ok(api.input(...step.input));
    continue;
  }
  const done = api.run(step.frames);
  if (done < 0) throw Error(api.error());
  const count = api.audioFrames();
  const start = api.audioData();
  const speechStarted = performance.now();
  api.speechRender(start, count, api.eventData(), api.eventCount());
  speechSeconds += (performance.now() - speechStarted) / 1000;
  pcm.update(M.HEAPU8.subarray(start, start + count * 4));
  pcmFrames += count;
  api.audioTake();
  frames += done;
  const aux = api.read(1, 0, 0x2000, 0x8000);
  const screen = api.screen();
  checkpoints.push({frames, ticks: api.get('ticks'), pc: api.get('pc'),
                    aux_sha256: sha(M.HEAPU8.subarray(aux, aux + 0x8000)),
                    screen_sha256: screen ? sha(M.HEAPU8.subarray(screen, screen + 640 * 200 * 4)) : null});
  if (done < step.frames) {
    stopped = api.result();
    break;
  }
}
const host = (performance.now() - started) / 1000;
const seconds = frames * api.get('frame_ticks') / api.get('clock_hz');
console.log(JSON.stringify({checkpoints, pcm_sha256: pcm.digest('hex'), pcm_frames: pcmFrames,
                            stopped, guest_seconds: seconds, host_seconds: host,
                            speech_seconds: speechSeconds, speed: seconds / host,
                            machine_speed: seconds / (host - speechSeconds)}));
