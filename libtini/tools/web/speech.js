// SPDX-License-Identifier: GPL-3.0-only
// Speech worker: a second instance of the player module mixes SSI-263 speech
// into the machine's PCM, off the machine's thread, and sends the result to
// the audio worklet. Messages: {port}, {start: [guest_hz, xck_hz, origin,
// gain], epoch}, {playing} and {pcm: Int16Array, events: Uint8Array of 16-byte
// records}. Blocks are mixed in order even while not playing, so speech keeps
// its timeline; they are sent to the worklet only while playing.
import createPlayer from './player.js';

let M, start, render, out = null, epoch = 0, playing = false;
const ready = createPlayer().then(module => {
  M = module;
  start = M.cwrap('tw_speech_start', null, ['number', 'number', 'number', 'number']);
  render = M.cwrap('tw_speech_render', null, ['number', 'number', 'number', 'number']);
});

onmessage = async event => {
  await ready;
  const message = event.data;
  if (message.port) {
    out = message.port;
  } else if ('playing' in message) {
    playing = message.playing;
  } else if (message.start) {
    epoch = message.epoch;
    start(...message.start);
  } else {
    const {pcm, events} = message;
    const frames = pcm.length / 2;
    const pointer = M._malloc(events.byteLength + pcm.byteLength + 16);
    const eventsAt = pointer, pcmAt = pointer + events.byteLength;
    M.HEAPU8.set(events, eventsAt);
    M.HEAP16.set(pcm, pcmAt >> 1);
    render(pcmAt, frames, eventsAt, events.byteLength / 16);
    const mixed = new Float32Array(frames * 2);
    const samples = M.HEAP16.subarray(pcmAt >> 1, (pcmAt >> 1) + frames * 2);
    for (let i = 0; i < mixed.length; i++) mixed[i] = samples[i] / 32768;
    M._free(pointer);
    if (playing) out.postMessage({epoch, samples: mixed}, [mixed.buffer]);
  }
};
