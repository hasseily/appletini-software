// SPDX-License-Identifier: GPL-3.0-only
// Browser front end of the libtini player. It loads the game's files into the
// machine, runs whole video frames paced by the audio clock (or the wall clock
// without audio), draws each SHR frame and sends keyboard and gamepad input.
import createPlayer from './player.js';
import {createLeaderboard} from './leaderboard.js';

const $ = id => document.getElementById(id);
// Frames arrive as 640x200 and are drawn with doubled rows on the 640x400
// screen, so the canvas keeps the Appletini's 16:10 shape when it is scaled.
const canvas = $('screen'), context = canvas.getContext('2d');
const source = Object.assign(document.createElement('canvas'), {width: 640, height: 200});
const sourceContext = source.getContext('2d');
const picture = sourceContext.createImageData(640, 200);
context.imageSmoothingEnabled = false;
const RATE = 48000, AHEAD = 0.1, MAX_FRAMES = 4;
// The board's speech is louder than the reference model's mix; doubled by ear.
const SPEECH_GAIN = 2;
const RESULTS = {3: 'halted', 4: 'stopped', 5: 'quit'};
const NAMED = {Enter: 13, Escape: 27, Backspace: 127, Delete: 127, Tab: 9,
               ArrowLeft: 8, ArrowRight: 21, ArrowUp: 11, ArrowDown: 10};
let M, api, game, files, leaderboard;
const bootFiles = {};
let audio = null, feed = null, gain = null, speech = null, epoch = 0;
let running = false, sent = 0, consumed = 0, debt = 0, last = 0, frameSeconds = 1 / 60;
let pad = null, speedFrames = 0, speedStart = 0, profileName = '';
const guestKeys = new Set();

function fail(message) {
  running = false;
  $('status').textContent = message;
}

function ok(result) {
  if (!result) throw Error(api.error() || 'machine error');
  return result;
}

async function load() {
  const bytes = path => fetch(path).then(r => {
    if (!r.ok) throw Error(path + ': ' + r.status);
    return r.arrayBuffer();
  }).then(data => new Uint8Array(data));
  const [manifest, blob, module] = await Promise.all([
    fetch('game.json').then(r => r.json()), bytes('game.bin'), createPlayer()]);
  game = manifest;
  if (game.profile === 'turbo-f122') {
    $('profile').value = '1';
    $('speed').hidden = true;
  }
  files = blob;
  M = module;
  if (game.boot) {
    const names = ['apple2e.rom', 'c700.bin', 'c800.bin', 'disk.po'];
    const loaded = await Promise.all(names.map(name => bytes(game.boot[name].path)));
    names.forEach((name, i) => { bootFiles[name] = loaded[i]; });
    $('origin').textContent = 'It boots the game disk, with ProDOS, through the Apple //e ROM ' +
      'and the Appletini SmartPort firmware.';
  }
  const f = (name, result, args) => M.cwrap(name, result, args);
  api = {
    create: f('tw_create', 'number', ['number', 'string']),
    volume: f('tw_volume', 'number', ['string', 'string']),
    file: f('tw_file', 'number', ['string', 'number', 'number', 'number', 'number']),
    launch: f('tw_launch', 'number', ['number', 'number']),
    boot: f('tw_boot', 'number', ['string', 'number', 'number', 'number', 'number']),
    run: f('tw_run', 'number', ['number']),
    result: f('tw_result', 'number', []),
    error: f('tw_error', 'string', []),
    halt: f('tw_halt', 'string', []),
    get: f('tw_get', 'number', ['string']),
    read: f('tw_read', 'number', ['number','number','number','number']),
    input: f('tw_input', 'number', ['string', 'number', 'number']),
    audioFrames: f('tw_audio_frames', 'number', []),
    audioData: f('tw_audio_data', 'number', []),
    eventCount: f('tw_event_count', 'number', []),
    eventData: f('tw_event_data', 'number', []),
    audioTake: f('tw_audio_take', null, []),
    speechStart: f('tw_speech_start', null, ['number', 'number', 'number', 'number']),
    speechRender: f('tw_speech_render', null, ['number', 'number', 'number', 'number']),
    screen: f('tw_screen', 'number', []),
  };
  leaderboard=createLeaderboard((address,length)=>{
    const p=api.read(0,0,address,length);return M.HEAPU8.slice(p,p+length);
  },game.leaderboard,document.querySelector('main'));
  document.title = game.title;
  if (game.download) {
    $('download').href = game.download.path;
    $('download').download = game.download.path;
    $('download').textContent = `Download ${game.download.path} (${Math.round(game.download.bytes / 1024)} KB)`;
    $('download').hidden = false;
  }
  $('title').textContent = game.title;
  $('play').disabled = false;
  $('status').textContent = 'Ready';
}

function withBytes(bytes, use) {
  const pointer = M._malloc(Math.max(1, bytes.length));
  try {
    M.HEAPU8.set(bytes, pointer);
    return use(pointer);
  } finally {
    M._free(pointer);
  }
}

// With boot files, the native runner's --boot: a fresh copy of the disk as
// SmartPort unit 1, started through the //e ROM and slot-7 firmware. Otherwise
// its --disk --system launch: every file except PRODOS through the MLI
// stand-in, then the SYSTEM program at $2000.
function boot(turbo) {
  leaderboard?.reset();
  if (game.boot) {
    M.FS.writeFile('/apple2e.rom', bootFiles['apple2e.rom']);
    M.FS.writeFile('/disk.po', bootFiles['disk.po']);
    ok(api.create(turbo, '/apple2e.rom'));
    const slot = bootFiles['c700.bin'], c8 = bootFiles['c800.bin'];
    withBytes(slot, p => withBytes(c8, q => ok(api.boot('/disk.po', p, slot.length, q, c8.length))));
  } else {
    ok(api.create(turbo, ''));
    ok(api.volume(game.volume, game.system));
    for (const entry of game.files) {
      const bytes = files.subarray(entry.offset, entry.offset + entry.length);
      withBytes(bytes, p => ok(api.file(entry.name, entry.type, entry.aux, p, bytes.length)));
    }
    const system = game.files.find(entry => entry.name === game.system);
    const program = files.subarray(system.offset, system.offset + system.length);
    withBytes(program, p => ok(api.launch(p, program.length)));
  }
  frameSeconds = api.get('frame_ticks') / api.get('clock_hz');
  // A new session: the worklet drops the old one's samples, even late ones.
  epoch++;
  sent = consumed;
  if (feed) feed.port.postMessage({epoch});
  const start = [api.get('clock_hz'), api.get('speech_xck_hz'), api.get('audio_origin'), SPEECH_GAIN];
  if (speech) speech.postMessage({start, epoch});
  else api.speechStart(...start);
}

// Speech runs in a worker when it can; the page mixes it itself otherwise.
// iOS starts sound only inside the tap itself, so the context is created and
// resumed before anything is awaited. The context runs at the device's rate;
// the worklet converts from the machine's 48 kHz.
async function startAudio() {
  if (!audio) {
    try {
      // Safari 17+: play like a video, even with the silent switch on.
      if (navigator.audioSession) navigator.audioSession.type = 'playback';
    } catch {}
    try {
      audio = new AudioContext({latencyHint: 'interactive'});
    } catch (error) {
      audio = null;
      $('status').textContent = 'No sound: ' + error.message;
      return;
    }
  }
  const resumed = audio.resume();
  if (!feed) {
    try {
      await audio.audioWorklet.addModule('worklet.js');
      feed = new AudioWorkletNode(audio, 'tini-feed', {numberOfInputs: 0, outputChannelCount: [2]});
      feed.port.onmessage = event => { consumed = event.data; };
      gain = audio.createGain();
      gain.gain.value = Number($('volume').value);
      feed.connect(gain).connect(audio.destination);
      try {
        const channel = new MessageChannel();
        speech = new Worker('speech.js', {type: 'module'});
        speech.onerror = () => { speech = null; };
        feed.port.postMessage({port: channel.port1}, [channel.port1]);
        speech.postMessage({port: channel.port2}, [channel.port2]);
      } catch {
        speech = null;
      }
      audio.onstatechange = playingChanged;
    } catch (error) {
      feed = gain = speech = null;
      $('status').textContent = 'No sound: ' + error.message;
    }
  }
  try {
    await resumed;
  } catch {}
  playingChanged();
}

// Samples reach the worklet only while the context runs; speech is mixed
// either way, so its timeline stays whole. A suspended or interrupted context
// (iOS after a call or an app switch) resumes on the next tap or key.
let playing = false;
function playingChanged() {
  const now = !!(feed && audio.state === 'running');
  if (now === playing) return;
  playing = now;
  sent = consumed;
  if (speech) speech.postMessage({playing});
}
function wake() {
  if (audio && audio.state !== 'running') audio.resume().then(playingChanged, () => {});
}
for (const kind of ['pointerup', 'touchend', 'keydown']) document.addEventListener(kind, wake);

function pushAudio() {
  const count = api.audioFrames();
  if (count && feed) {
    const events = api.eventCount();
    if (speech) {
      const pcm = M.HEAP16.slice(api.audioData() >> 1, (api.audioData() >> 1) + count * 2);
      const records = M.HEAPU8.slice(api.eventData(), api.eventData() + events * 16);
      speech.postMessage({pcm, events: records}, [pcm.buffer, records.buffer]);
    } else {
      api.speechRender(api.audioData(), count, api.eventData(), events);
      if (playing) {
        const start = api.audioData() >> 1;
        const samples = M.HEAP16.subarray(start, start + count * 2);
        const mixed = new Float32Array(count * 2);
        for (let i = 0; i < mixed.length; i++) mixed[i] = samples[i] / 32768;
        feed.port.postMessage({epoch, samples: mixed}, [mixed.buffer]);
      }
    }
    if (playing) sent += count;
  }
  api.audioTake();
}

function draw() {
  const pointer = api.screen();
  if (!pointer) {
    context.fillStyle = '#000';
    context.fillRect(0, 0, 640, 400);
    return;
  }
  picture.data.set(M.HEAPU8.subarray(pointer, pointer + 640 * 200 * 4));
  sourceContext.putImageData(picture, 0, 0);
  context.drawImage(source, 0, 0, 640, 400);
}

// One joystick from the first gamepad and the touch controls. The touch stick
// overrides the gamepad axes while held; buttons combine. The machine starts
// centred with buttons up, so nothing is sent until the state changes.
const touch = {held: false, x: 128, y: 128, buttons: [0, 0, 0]};
const NEUTRAL = [128, 128, 0, 0, 0];

function pollControls() {
  const pads = navigator.getGamepads ? [...navigator.getGamepads()].filter(Boolean) : [];
  const g = pads[0];
  const paddle = value => Math.max(0, Math.min(255, Math.round((value + 1) * 127.5)));
  let state = [...NEUTRAL];
  if (g) {
    const axis = (value, low, high) =>
      g.buttons[low]?.pressed ? -1 : g.buttons[high]?.pressed ? 1 : Math.abs(value) < 0.15 ? 0 : value;
    state = [paddle(axis(g.axes[0] || 0, 14, 15)), paddle(axis(g.axes[1] || 0, 12, 13)),
             ...[0, 1, 2].map(i => g.buttons[i]?.pressed ? 1 : 0)];
  }
  if (touch.held) state = [touch.x, touch.y, ...state.slice(2)];
  for (let i = 0; i < 3; i++) state[2 + i] |= touch.buttons[i];
  const previous = pad || NEUTRAL;
  pad = state;
  if (state.every((value, i) => value === previous[i])) return;
  api.input('paddle', 0, state[0]);
  api.input('paddle', 1, state[1]);
  for (let i = 0; i < 3; i++) api.input('button', i, state[2 + i]);
}

const stick = $('stick'), knob = $('knob');
let stickPointer = null;

function moveStick(event) {
  const box = stick.getBoundingClientRect(), radius = box.width / 2;
  let dx = (event.clientX - box.left - radius) / radius, dy = (event.clientY - box.top - radius) / radius;
  const length = Math.hypot(dx, dy);
  if (length > 1) {
    dx /= length;
    dy /= length;
  }
  knob.style.transform = `translate(${dx * radius * 0.6}px, ${dy * radius * 0.6}px)`;
  const axis = value => Math.abs(value) < 0.15 ? 128 : Math.max(0, Math.min(255, Math.round((value + 1) * 127.5)));
  touch.x = axis(dx);
  touch.y = axis(dy);
}

function releaseStick(event) {
  if (event.pointerId !== stickPointer) return;
  stickPointer = null;
  touch.held = false;
  touch.x = touch.y = 128;
  knob.style.transform = '';
}

stick.addEventListener('pointerdown', event => {
  event.preventDefault();
  stickPointer = event.pointerId;
  stick.setPointerCapture(event.pointerId);
  touch.held = true;
  moveStick(event);
});
stick.addEventListener('pointermove', event => { if (event.pointerId === stickPointer) moveStick(event); });
stick.addEventListener('pointerup', releaseStick);
stick.addEventListener('pointercancel', releaseStick);

for (const button of document.querySelectorAll('.pad')) {
  const index = Number(button.dataset.button);
  const press = down => event => {
    event.preventDefault();
    if (down) button.setPointerCapture(event.pointerId);
    touch.buttons[index] = down;
    button.classList.toggle('down', !!down);
  };
  button.addEventListener('pointerdown', press(1));
  for (const kind of ['pointerup', 'pointercancel']) button.addEventListener(kind, press(0));
}

// Return and Esc as held Apple //e keys, like the keyboard.
for (const button of document.querySelectorAll('.key[data-key]')) {
  const up = () => {
    if (!button.classList.contains('down')) return;
    button.classList.remove('down');
    if (running && guestKeys.size === 0) api.input('release', 0, 0);
  };
  button.addEventListener('pointerdown', event => {
    event.preventDefault();
    if (!running) return;
    button.setPointerCapture(event.pointerId);
    button.classList.add('down');
    api.input('hold', Number(button.dataset.key), 0);
  });
  for (const kind of ['pointerup', 'pointercancel']) button.addEventListener(kind, up);
}

// The device's own keyboard: a hidden text field whose typing reaches the
// Apple //e as key presses. Composed words (Android keyboards) are sent when
// the composition ends; Return and Backspace send Return and DELETE.
const typing = $('typing');
function typeKeys(text) {
  if (!running) return;
  for (const character of text.toUpperCase()) {
    const code = character.charCodeAt(0);
    if (code < 128) api.input('key', code, 0);
  }
}
function flushTyping() {
  typeKeys(typing.value);
  typing.value = '';
}
$('keyboard').addEventListener('click', () => {
  if (document.activeElement === typing) typing.blur();
  else typing.focus();
});
typing.addEventListener('focus', () => $('keyboard').classList.add('down'));
typing.addEventListener('blur', () => $('keyboard').classList.remove('down'));
typing.addEventListener('input', event => { if (!event.isComposing) flushTyping(); });
typing.addEventListener('compositionend', flushTyping);
typing.addEventListener('keydown', event => {
  const special = {Enter: 13, Backspace: 127, Escape: 27, Tab: 9,
                   ArrowLeft: 8, ArrowRight: 21, ArrowUp: 11, ArrowDown: 10}[event.key];
  if (special === undefined || event.isComposing) return;
  event.preventDefault();
  if (running) api.input('key', special, 0);
});

function showTouch(show) {
  $('touch').hidden = !show;
  $('touchToggle').textContent = show ? 'Hide touch controls' : 'Touch controls';
}
const touchParam = new URLSearchParams(location.search).get('touch');
showTouch(touchParam ? touchParam === '1' : matchMedia('(pointer: coarse)').matches);
if (!touchParam) {
  window.addEventListener('touchstart', () => showTouch(true), {once: true, passive: true});
}
$('touchToggle').onclick = () => showTouch($('touch').hidden);

function finish() {
  running = false;
  releaseKeys();
  const result = api.result(), halt = api.halt();
  $('message').textContent = `${game.title} ${RESULTS[result] || 'stopped'}.` +
    (result === 3 && halt ? ' ' + halt : '');
  $('finished').hidden = false;
}

function frame(now) {
  if (!running) return;
  requestAnimationFrame(frame);
  const elapsed = Math.min((now - last) / 1000, 0.25);
  last = now;
  let frames;
  if (playing) {
    frames = Math.ceil((AHEAD - (sent - consumed) / RATE) / frameSeconds);
  } else {
    debt += elapsed;
    frames = Math.floor(debt / frameSeconds);
    debt -= frames * frameSeconds;
  }
  frames = Math.max(0, Math.min(MAX_FRAMES, frames));
  pollControls();
  if (frames) {
    const done = api.run(frames);
    if (done < 0) return fail(api.error());
    pushAudio();
    draw();
    leaderboard?.poll();
    speedFrames += done;
    if (done < frames) return finish();
  }
  if (now - speedStart >= 1000) {
    const speed = speedFrames * frameSeconds / ((now - speedStart) / 1000);
    const sound = !feed ? ' · no sound' : playing ? '' : ' · tap for sound';
    $('status').textContent = `${profileName} · ${Math.round(speed * 100)}% speed${sound}`;
    speedFrames = 0;
    speedStart = now;
  }
}

function appleKey(event) {
  if (event.key in NAMED) return NAMED[event.key];
  if (event.key.length === 1 && event.key.charCodeAt(0) < 128) {
    const code = event.key.toUpperCase().charCodeAt(0);
    return event.ctrlKey ? code & 31 : code;
  }
  return null;
}

function releaseKeys() {
  if (guestKeys.size && api) api.input('release', 0, 0);
  guestKeys.clear();
}

// Apple //e keys while the screen has focus: one latched key and any-key-down.
canvas.addEventListener('keydown', event => {
  if (!running || event.metaKey || event.altKey) return;
  const key = appleKey(event);
  if (key === null) return;
  event.preventDefault();
  if (event.repeat) return;
  if(key===78&&leaderboard?.open()){releaseKeys();return;}
  guestKeys.add(event.code);
  api.input('hold', key, 0);
});
canvas.addEventListener('keyup', event => {
  if (!guestKeys.delete(event.code)) return;
  event.preventDefault();
  if (guestKeys.size === 0 && running) api.input('release', 0, 0);
});
canvas.addEventListener('blur', releaseKeys);
canvas.addEventListener('click', () => canvas.focus());
document.addEventListener('visibilitychange', () => {
  releaseKeys();
  last = performance.now();
  debt = 0;
});

$('play').onclick = async () => {
  $('play').disabled = true;
  try {
    await startAudio();
    boot(Number($('profile').value));
    profileName = $('profile').selectedOptions[0].textContent;
    $('start').hidden = $('finished').hidden = true;
    $('reset').disabled = false;
    running = true;
    pad = null;
    last = speedStart = performance.now();
    debt = speedFrames = 0;
    $('status').textContent = profileName;
    canvas.focus();
    requestAnimationFrame(frame);
  } catch (error) {
    fail(error.message);
  } finally {
    $('play').disabled = false;
  }
};
$('restart').onclick = $('reset').onclick = () => {
  running = false;
  releaseKeys();
  if (feed) feed.port.postMessage({epoch: ++epoch});
  $('finished').hidden = true;
  $('start').hidden = false;
};
$('volume').oninput = () => { if (gain) gain.gain.value = Number($('volume').value); };
$('full').onclick = () => $('frame').requestFullscreen?.();

load().catch(error => fail('Could not load the player: ' + error.message));
