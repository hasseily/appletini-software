/* SPDX-License-Identifier: GPL-2.0-only
 * Functional protocol implemented from the observable Appletini SSI contract.
 * Counts effective XCK edges; omits FPGA fabric pipeline/propagation latency.
 * Analog speech synthesis runs in a separate GPL3 reference process. */
#include "speech_state.h"
#include <stdlib.h>
#include <string.h>

struct socket_state {
    uint8_t reg[5], function, enabled, ready, active, pcr, ca1;
    uint8_t response_phase, duration_phase;
    uint32_t response_left, duration_left;
    uint64_t ca1_tick;
};
struct ap_ssi_state {
    struct socket_state socket[2];
    uint64_t guest_hz, last_tick, fraction, origin, xck_ticks;
    uint32_t xck_hz;
    unsigned mode;
};
static uint32_t response_period(const struct socket_state *s) {
    return (16u - (s->reg[2] >> 4)) * 256u;
}
static uint32_t duration_period(const struct socket_state *s) {
    return response_period(s) * (4u - (s->reg[0] >> 6));
}
static void reset_socket(struct socket_state *s, int cold) {
    uint8_t saved[5], function = s->function, pcr = s->pcr;
    memcpy(saved, s->reg, sizeof(saved));
    memset(s, 0, sizeof(*s));
    s->pcr = pcr;
    if (cold) s->reg[0] = 0xc0;
    else {
        memcpy(s->reg, saved, sizeof(saved));
        s->function = function;
    }
    s->reg[3] = 0x80;
}
ap_ssi_state *ap_ssi_new(uint64_t hz, uint32_t xck, uint64_t origin) {
    ap_ssi_state *s;
    if (!hz || hz > 1000000000u || !xck || xck > 10000000u) return NULL;
    s = calloc(1, sizeof(*s));
    if (s) {
        s->guest_hz = hz; s->xck_hz = xck; s->last_tick = s->origin = origin;
        reset_socket(&s->socket[0], 1); reset_socket(&s->socket[1], 1);
    }
    return s;
}
void ap_ssi_free(ap_ssi_state *s) { free(s); }
static void complete(ap_ssi_state *s, struct socket_state *v, uint64_t xck_tick) {
    if (v->reg[3] & 0x80) return;
    if (!v->ready && v->enabled && s->mode == 0 && !(v->pcr & 1) && !v->ca1) {
        v->ca1 = 1;
        v->ca1_tick = s->origin + (xck_tick / s->xck_hz) * s->guest_hz +
            ((xck_tick % s->xck_hz) * s->guest_hz + s->xck_hz - 1) / s->xck_hz;
    }
    v->ready = 1;
}
static void advance_socket(ap_ssi_state *s, struct socket_state *v, uint64_t ticks) {
    uint64_t cursor = s->xck_ticks;
    if (!v->active) return;
    while (ticks) {
        uint32_t next = v->response_left < v->duration_left ?
                        v->response_left : v->duration_left;
        uint32_t elapsed = ticks < next ? (uint32_t)ticks : next;
        ticks -= elapsed; cursor += elapsed;
        v->response_left -= elapsed; v->duration_left -= elapsed;
        if (!v->response_left) {
            v->response_left = response_period(v);
            v->response_phase = (v->response_phase + 1) & 15;
            if (!v->response_phase && v->function == 1) complete(s, v, cursor);
        }
        if (!v->duration_left) {
            v->duration_left = duration_period(v);
            v->duration_phase = (v->duration_phase + 1) & 15;
            if (!v->duration_phase && v->function >= 2) complete(s, v, cursor);
        }
    }
}
void ap_ssi_advance(ap_ssi_state *s, uint64_t tick) {
    uint64_t delta, ticks, fraction;
    if (!s || tick <= s->last_tick) return;
    delta = tick - s->last_tick; s->last_tick = tick;
    /* Normal calls are instruction-sized. Division first keeps long runs
     * safe without a compiler-specific 128-bit integer requirement. */
    ticks = (delta / s->guest_hz) * s->xck_hz;
    fraction = (delta % s->guest_hz) * s->xck_hz + s->fraction;
    ticks += fraction / s->guest_hz; s->fraction = fraction % s->guest_hz;
    advance_socket(s, &s->socket[0], ticks);
    advance_socket(s, &s->socket[1], ticks);
    s->xck_ticks += ticks;
}
static void start(struct socket_state *v) {
    v->active = 1; v->response_phase = v->duration_phase = 0;
    v->response_left = response_period(v); v->duration_left = duration_period(v);
}
void ap_ssi_write(ap_ssi_state *s, unsigned chip, unsigned reg, uint8_t val, uint64_t tick) {
    struct socket_state *v; uint8_t old;
    if (!s || chip > 1 || reg > 7) return;
    ap_ssi_advance(s, tick); v = &s->socket[chip];
    if (reg >= 4) reg = 4;
    old = v->reg[reg]; v->reg[reg] = val;
    /* The register acknowledgement wins over a coincident response edge.
     * Earlier unconsumed CA1 pulses still belong to the VIA. */
    if ((reg <= 2 || (reg == 3 && (val & 0x80))) && v->ca1 && v->ca1_tick == tick)
        v->ca1 = 0;
    if (reg <= 2) v->ready = 0;
    if (reg == 0 && !(v->reg[3] & 0x80)) start(v);
    if (reg == 3) {
        if (val & 0x80) v->ready = 0;
        else if (old & 0x80) {
            unsigned function = v->reg[0] >> 6;
            v->enabled = function != 0;
            if (function) v->function = (uint8_t)function;
            start(v);
        }
    }
}
void ap_ssi_reset(ap_ssi_state *s, unsigned chip, int cold, uint64_t tick) {
    if (!s || chip > 1) return;
    ap_ssi_advance(s, tick); reset_socket(&s->socket[chip], cold);
}
uint8_t ap_ssi_read(ap_ssi_state *s, unsigned chip, uint64_t tick) {
    if (!s || chip > 1) return 0;
    ap_ssi_advance(s, tick); return s->socket[chip].ready ? 0x80 : 0;
}
void ap_ssi_route(ap_ssi_state *s, unsigned mode, uint8_t pcr0, uint8_t pcr1, uint64_t tick) {
    unsigned i;
    if (!s) return;
    ap_ssi_advance(s, tick);
    s->socket[0].pcr = pcr0; s->socket[1].pcr = pcr1;
    if (mode != s->mode && mode == 0) for (i = 0; i < 2; ++i) {
        struct socket_state *v = &s->socket[i];
        if (v->ready && v->enabled && !(v->reg[3] & 0x80) && !(v->pcr & 1) && !v->ca1) {
            v->ca1 = 1; v->ca1_tick = tick;
        }
    }
    s->mode = mode;
}
int ap_ssi_irq(const ap_ssi_state *s) {
    unsigned i;
    if (!s || s->mode != 5) return 0;
    for (i = 0; i < 2; ++i) {
        const struct socket_state *v = &s->socket[i];
        if (v->ready && v->enabled && !(v->reg[3] & 0x80)) return 1;
    }
    return 0;
}
int ap_ssi_take_ca1(ap_ssi_state *s, unsigned chip) {
    int result;
    if (!s || chip > 1) return 0;
    result = s->socket[chip].ca1; s->socket[chip].ca1 = 0; return result;
}
