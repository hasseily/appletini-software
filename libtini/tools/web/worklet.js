// SPDX-License-Identifier: GPL-3.0-only
// Plays the machine's interleaved 48 kHz stereo samples in order, from the
// page or the speech worker: {epoch, samples}. {epoch} alone starts a new
// session and drops queued or late samples of the old one. At another context
// rate it interpolates linearly. It outputs silence when the queue is empty
// and reports the source frames it has played.
const SOURCE_RATE = 48000;

class Feed extends AudioWorkletProcessor {
  constructor() {
    super();
    this.chunks = [];
    this.offset = 0;
    this.fraction = 0;
    this.step = SOURCE_RATE / sampleRate;
    this.played = 0;
    this.quanta = 0;
    this.epoch = 0;
    const receive = event => {
      const {epoch, samples} = event.data;
      if (!samples) {
        this.epoch = epoch;
        this.chunks = [];
        this.offset = 0;
        this.fraction = 0;
      } else if (epoch === this.epoch) {
        this.chunks.push(samples);
      }
    };
    this.port.onmessage = event => {
      if (event.data.port) event.data.port.onmessage = receive;
      else receive(event);
    };
  }

  process(inputs, outputs) {
    const [left, right] = outputs[0];
    let i = 0;
    while (i < left.length && this.chunks.length) {
      const chunk = this.chunks[0], at = 2 * this.offset;
      const next = this.offset + 1 < chunk.length / 2 ? chunk : this.chunks[1];
      const nextAt = next === chunk ? at + 2 : 0;
      const l = chunk[at], r = chunk[at + 1];
      left[i] = next ? l + (next[nextAt] - l) * this.fraction : l;
      right[i] = next ? r + (next[nextAt + 1] - r) * this.fraction : r;
      ++i;
      this.fraction += this.step;
      const whole = Math.floor(this.fraction);
      this.fraction -= whole;
      this.offset += whole;
      this.played += whole;
      while (this.chunks.length && this.offset >= this.chunks[0].length / 2) {
        this.offset -= this.chunks[0].length / 2;
        this.chunks.shift();
      }
    }
    left.fill(0, i);
    right.fill(0, i);
    if (++this.quanta % 8 === 0) this.port.postMessage(this.played);
    return true;
  }
}

registerProcessor('tini-feed', Feed);
