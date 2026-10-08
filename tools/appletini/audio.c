/* SPDX-License-Identifier: GPL-2.0-only
 * Deterministic, event-timestamped PSG and one-bit speaker synthesis.
 * Independently implemented register/timing behavior; gain tables follow
 * Appletini's permissively licensed YM2149.sv. Original table-source notice:
 *
 * Copyright (c) MikeJ - Jan 2005
 * Copyright (c) 2016-2018 Sorgelig
 *
 * All rights reserved
 *
 * Redistribution and use in source and synthesized forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * Redistributions of source code must retain the above copyright notice,
 * this list of conditions and the following disclaimer.
 *
 * Redistributions in synthesized form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the distribution.
 *
 * Neither the name of the author nor the names of other contributors may
 * be used to endorse or promote products derived from this software without
 * specific prior written permission.
 *
 * THIS CODE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
 * THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 * PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE
 * LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
 * CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 *
 */
#include "audio.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    uint8_t r[16], tone[3], noise, noise_div, env, up, held;
    uint16_t tone_count[3];
    uint32_t noise_count, env_count, lfsr;
    double phase;                 /* Fraction of a clock/8 generator tick. */
} psg;

struct ap_audio {
    unsigned rate, mode, speaker, overflow;
    uint64_t hz, origin, generated, cursor, sample_start;
    double bus_hz, highpass, area[2], speaker_area, speaker_dc, dc[2];
    size_t head, count, capacity;
    int16_t *pcm;
    psg chips[5];
};
static const uint8_t ym_gain[32] = {
    0,1,1,2,2,3,3,4,6,7,9,10,12,14,17,19,
    23,27,32,37,44,53,62,71,84,102,119,136,161,192,224,255
};
static const uint8_t ay_gain[16] = {
    0,3,4,6,10,15,21,34,40,65,91,114,144,181,215,255
};
static const uint8_t masks[16] = {
    255,15,255,15,255,15,31,255,31,31,31,255,255,15,255,255
};

static void reset(psg *p)
{
    memset(p, 0, sizeof *p);
    p->lfsr = 1;
    p->noise = 1;
    p->env = 31;
}
static void envelope_reset(psg *p)
{
    p->up = !!(p->r[13] & 4);
    p->env = p->up ? 0 : 31;
    p->held = 0;
    p->env_count = 0;
}
static void generator_tick(psg *p)
{
    for (unsigned c = 0; c < 3; c++) {
        unsigned period = p->r[2*c] | ((unsigned)p->r[2*c+1] << 8);
        if (!period) {
            /* Appletini's YM core treats zero as a static mixer input. */
            p->tone[c] = (p->r[7] >> (c + 1)) & 1;
            p->tone_count[c] = 0;
        } else if (++p->tone_count[c] >= period) {
            p->tone_count[c] = 0;
            p->tone[c] ^= 1;
        }
    }
    p->noise_div ^= 1;
    if (!p->noise_div) {
        unsigned period = p->r[6] ? p->r[6] : 1;
        if (++p->noise_count >= period) {
            p->noise_count = 0;
            if ((p->lfsr ^ (p->lfsr >> 1)) & 1) p->noise ^= 1;
            p->lfsr = (p->lfsr >> 1) | (((p->lfsr ^ (p->lfsr >> 2)) & 1) << 16);
        }
    }
    unsigned period = p->r[11] | ((unsigned)p->r[12] << 8);
    if (++p->env_count >= (period ? period : 1)) {
        p->env_count = 0;
        if (!p->held) {
            int next = (int)p->env + (p->up ? 1 : -1);
            if (next >= 0 && next <= 31) p->env = (uint8_t)next;
            else if (!(p->r[13] & 8)) { p->env = 0; p->held = 1; }
            else if (p->r[13] & 1) {
                p->env = (p->r[13] & 2) ? (p->up ? 0 : 31) : (p->up ? 31 : 0);
                p->held = 1;
            } else if (p->r[13] & 2) {
                p->up ^= 1;
                p->env = p->up ? 0 : 31;
            } else p->env = p->up ? 0 : 31;
        }
    }
}
static void levels(const ap_audio *a, unsigned chip, double out[2])
{
    const psg *p = &a->chips[chip];
    out[0] = out[1] = 0;
    if (chip < 4 && ((a->mode != 5 && a->mode != 7 && (chip & 1)) ||
                     (a->mode == 7 && chip < 2))) return;
    for (unsigned c = 0; c < 3; c++) {
        if (!(((p->r[7] >> c) & 1) || p->tone[c]) ||
            !(((p->r[7] >> (c+3)) & 1) || p->noise)) continue;
        unsigned volume = p->r[8+c];
        unsigned gain;
        if (chip == 4) {
            unsigned index = (volume & 16) ? p->env :
                             ((volume & 15) * 2 + ((volume >> 3) & 1));
            gain = ym_gain[index];
            out[0] += gain * 16; out[1] += gain * 16;
        } else {
            gain = ay_gain[(volume & 16) ? (p->env >> 1) : (volume & 15)];
            /* Default Appletini pan 0x5B5B5B5B5B5B: B/5/B on the
               VIA0 pair and 5/B/5 on the VIA1 pair. Gain units are /16. */
            unsigned pan_b = ((chip < 2) == !(c & 1));
            out[0] += gain * (pan_b ? 9 : 16);
            out[1] += gain * (pan_b ? 16 : 10);
        }
    }
}
static void integrate(ap_audio *a, uint64_t to)
{
    double span = (double)(to - a->cursor);
    for (unsigned chip = 0; chip < 5; chip++) {
        psg *p = &a->chips[chip];
        double step = a->hz * 8.0 / (a->bus_hz * ((chip < 4 && a->mode == 5) ? 2 : 1));
        double left = span;
        while (left > 0) {
            double until = (1 - p->phase) * step;
            double take = left < until ? left : until;
            double mix[2]; levels(a, chip, mix);
            a->area[0] += mix[0] * take;
            a->area[1] += mix[1] * take;
            left -= take;
            p->phase += take / step;
            if (p->phase >= 1 - 1e-12) { p->phase = 0; generator_tick(p); }
        }
    }
    a->speaker_area += (a->speaker ? 12000 : -12000) * span;
    a->cursor = to;
}
static int16_t clip(double value)
{
    if (value > 32767) return 32767;
    if (value < -32768) return -32768;
    return (int16_t)lrint(value);
}
void ap_audio_sync(ap_audio *a, uint64_t tick)
{
    if (!a || a->overflow || tick < a->cursor) return;
    for (;;) {
        /* Quotient/remainder keeps sample boundaries exact without a
           per-sample floating-point clock, including nonintegral ratios. */
        uint64_t n = a->generated + 1;
        uint64_t next = a->origin + (n / a->rate) * a->hz +
                        ((n % a->rate) * a->hz + a->rate - 1) / a->rate;
        if (tick < next) { integrate(a, tick); return; }
        if (a->count == a->capacity) { a->overflow = 1; return; }
        integrate(a, next);
        double width = (double)(next - a->sample_start);
        double sp = a->speaker_area / width;
        a->speaker_dc += (sp - a->speaker_dc) / 256.0;
        sp -= a->speaker_dc;
        size_t at = ((a->head + a->count) % a->capacity) * 2;
        for (unsigned c = 0; c < 2; c++) {
            double raw = a->area[c] / width;
            /* DC coupling is a host playback model, not the hardware's
               configurable four-band EQ/analog amplifier transfer curve. */
            a->dc[c] += (raw - a->dc[c]) * a->highpass;
            a->pcm[at+c] = clip(raw - a->dc[c] + sp);
            a->area[c] = 0;
        }
        a->speaker_area = 0; a->sample_start = next;
        a->generated++; a->count++;
    }
}
ap_audio *ap_audio_new(unsigned rate, uint64_t hz, double bus_hz,
                       uint64_t origin, unsigned mode, unsigned speaker)
{
    if (rate < 8000 || rate > 192000 || hz < rate || !isfinite(bus_hz) || bus_hz <= 0) return NULL;
    ap_audio *a = calloc(1, sizeof *a);
    if (!a) return NULL;
    a->rate = rate; a->hz = hz; a->bus_hz = bus_hz;
    a->highpass = 1 - exp(-125.66370614359173 / rate);
    a->origin = a->cursor = a->sample_start = origin;
    a->mode = mode; a->speaker = speaker;
    a->speaker_dc = speaker ? 12000 : -12000;
    a->capacity = (size_t)rate * 4;
    a->pcm = calloc(a->capacity * 2, sizeof *a->pcm);
    if (!a->pcm) { free(a); return NULL; }
    for (unsigned i = 0; i < 5; i++) reset(&a->chips[i]);
    return a;
}
void ap_audio_free(ap_audio *a) { if (a) { free(a->pcm); free(a); } }
void ap_audio_seed(ap_audio *a, unsigned chip, const uint8_t registers[16])
{
    if (!a || chip > 4) return;
    for (unsigned r = 0; r < 16; r++) a->chips[chip].r[r] = registers[r] & masks[r];
    envelope_reset(&a->chips[chip]);
}
void ap_audio_event(ap_audio *a, uint64_t tick, unsigned kind,
                    unsigned chip, unsigned reg, unsigned value)
{
    if (!a) return;
    ap_audio_sync(a, tick);
    if (kind == 2) a->mode = value;
    else if (kind == 3) a->speaker = !!value;
    else if (chip < 5) {
        psg *p = &a->chips[chip];
        if (kind == 1) reset(p);
        else if (kind == 0 && reg < 16) {
            p->r[reg] = value & masks[reg];
            if (reg == 6) p->noise_count = 0;
            if (reg == 13) envelope_reset(p);
        }
    }
}
size_t ap_audio_count(const ap_audio *a) { return a ? a->count : 0; }
size_t ap_audio_take(ap_audio *a, int16_t *stereo, size_t frames)
{
    if (!a || (!stereo && frames)) return 0;
    if (frames > a->count) frames = a->count;
    size_t first = a->capacity - a->head;
    if (first > frames) first = frames;
    if (first) memcpy(stereo, a->pcm + 2*a->head, first * 2 * sizeof *stereo);
    if (frames > first) memcpy(stereo + 2*first, a->pcm, (frames-first)*2*sizeof *stereo);
    a->head = (a->head + frames) % a->capacity;
    a->count -= frames;
    return frames;
}
unsigned ap_audio_rate(const ap_audio *a) { return a ? a->rate : 0; }
uint64_t ap_audio_frames(const ap_audio *a) { return a ? a->generated : 0; }
int ap_audio_full(const ap_audio *a) { return a && a->count >= (size_t)a->rate * 3; }
int ap_audio_overflow(const ap_audio *a) { return a && a->overflow; }
