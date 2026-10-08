/* SPDX-License-Identifier: GPL-2.0-only
 * A small ABI around the existing a2vm machine. CPU execution stays in C.
 */
#include "native.h"
#include "a2vm.h"
#include "cards.h"
#include "audio.h"
#include "speech_state.h"

#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct ap_machine {
    a2vm *vm;
    ap_cards *cards;
    ap_audio *audio;
    ap_ssi_state *speech;
    ap_ssi_event *events;
    size_t event_head, event_count;
    unsigned event_overflow;
    uint64_t clock_hz, audio_origin, audio_sync_tick;
    uint32_t speech_xck_hz;
    double launch_cpu_hz;
    uint64_t nominal_cpu_hz;
    uint64_t rate_origin_raw, rate_origin_tick, rate_fraction;
    uint64_t rate_numerator, rate_denominator;
    unsigned launch_rate_units;
    uint8_t pcr[2];
    uint64_t io_writes;
    uint8_t joystick_buttons[3], apple_keys[2];
    char error[256];
};

static int fail(ap_machine *m, const char *message)
{
    if (m)
        snprintf(m->error, sizeof m->error, "%s", message);
    return 0;
}

static void copy_error(char *out, size_t size, const char *message)
{
    if (out && size)
        snprintf(out, size, "%s", message);
}

static void observe_write(a2vm *vm, uint16_t address, uint8_t *storage,
                           uint8_t value)
{
    (void)storage;
    (void)value;
    if ((address & 0xff00u) == 0xc000u) {
        ap_machine *m = vm->hook_context;
        m->io_writes++;
    }
}

static void speech_event(ap_machine *m, unsigned chip, unsigned reg, unsigned value)
{
    if (!m->audio) return;
    if (m->event_count == 4096) { m->event_overflow = 1; return; }
    size_t at = (m->event_head + m->event_count++) % 4096;
    m->events[at] = (ap_ssi_event){ a2vm_now(m->vm), (uint8_t)chip,
                                   (uint8_t)reg, (uint8_t)value, {0} };
}
static void service_speech(a2vm *vm)
{
    ap_machine *m = vm->sound_context;
    if (!m || !m->speech) return;
    ap_ssi_route(m->speech, vm->phasor.mode, m->pcr[0], m->pcr[1], a2vm_now(vm));
    for (unsigned i = 0; i < 2; i++)
        if (ap_ssi_take_ca1(m->speech, i)) vm->phasor.t1[i].ifr |= 2;
    cpu65c02_set_irq(&vm->cpu, 4, ap_ssi_irq(m->speech));
}
static void sound_event(a2vm *vm, unsigned kind, unsigned chip,
                         unsigned reg, unsigned value)
{
    ap_machine *m = vm->sound_context;
    if (m->audio) ap_audio_event(m->audio, a2vm_now(vm), kind, chip, reg, value);
    if (kind == 2) service_speech(vm);
}
static unsigned sound_vias(a2vm *vm, unsigned address)
{
    if (vm->phasor.mode == 5) return ((address & 16) ? 1 : 0) | ((address & 128) ? 2 : 0);
    if (vm->phasor.mode == 7) return 2;
    return (address & 128) ? 2 : 1;
}
static void speech_write(a2vm *vm, unsigned address, uint8_t value)
{
    ap_machine *m = vm->sound_context;
    unsigned vias = sound_vias(vm, address);
    for (unsigned i = 0; i < 2; i++) if (vias & (1u << i)) {
        if ((address & 15) == 12) m->pcr[i] = value;
        if ((address & 15) == 1) vm->phasor.t1[i].ifr &= (uint8_t)~2;
    }
    if (vm->phasor.mode == 0 || vm->phasor.mode == 5) {
        for (unsigned chip = 0; chip < 2; chip++) if (address & (chip ? 64 : 32)) {
            ap_ssi_write(m->speech, chip, address & 7, value, a2vm_now(vm));
            speech_event(m, chip, address & 7, value);
            if (!(address & 7)) vm->phasor.ssi_phonemes++;
        }
    }
    service_speech(vm);
}
static int speech_read(a2vm *vm, unsigned address)
{
    ap_machine *m = vm->sound_context;
    service_speech(vm);
    if (vm->phasor.mode == 5 && !(address & 0x90) && (address & 0x60))
        return ap_ssi_read(m->speech, (address & 32) ? 0 : 1, a2vm_now(vm));
    unsigned vias = sound_vias(vm, address);
    for (unsigned i = 0; i < 2; i++) if (vias & (1u << i)) {
        if ((address & 15) == 12) return m->pcr[i];
        if ((address & 15) == 1) vm->phasor.t1[i].ifr &= (uint8_t)~2;
    }
    return -1;
}
static int audio_ready(ap_machine *m)
{
    if (!m->audio) return 1;
    ap_audio_sync(m->audio, a2vm_now(m->vm));
    if (ap_audio_overflow(m->audio) || m->event_overflow)
        return fail(m, "audio capture overflow; restart capture after draining more frequently");
    if (ap_audio_full(m->audio) || m->event_count >= 3072)
        return fail(m, "audio queue full; drain PCM and speech events before advancing the machine");
    return 1;
}

/* Preset CPU frequencies are rational fractions of the same fabric clock.
 * Units are 1/3 MHz: 1 MHz=3, UltraWarp=40, vTW26=80, vTW33=100. */
static unsigned rate_units(double hz)
{
    const unsigned units[] = {3, 40, 80, 100};
    for (unsigned i = 0; i < sizeof units / sizeof *units; i++)
        if (fabs(hz - units[i] * (1000000.0 / 3)) < 0.01) return units[i];
    return 0;
}
static uint64_t mapped_at(const ap_machine *m, uint64_t raw, uint64_t *fraction)
{
    uint64_t delta = raw - m->rate_origin_raw;
    uint64_t whole, tail;
    if (m->rate_denominator == (UINT64_C(1) << 32)) {
        /* Split the Q32 product so long custom-clock runs need no nonstandard
           128-bit integer type. The low product plus remainder fits uint64. */
        uint64_t low = m->rate_numerator & UINT32_MAX;
        whole = delta * (m->rate_numerator >> 32) + (delta >> 32) * low;
        tail = (delta & UINT32_MAX) * low + m->rate_fraction;
        whole += tail >> 32;
        if (fraction) *fraction = tail & UINT32_MAX;
    } else {
        /* For presets the denominator is 1200, with a numerator <=40000. */
        whole = (delta / m->rate_denominator) * m->rate_numerator;
        tail = (delta % m->rate_denominator) * m->rate_numerator + m->rate_fraction;
        whole += tail / m->rate_denominator;
        if (fraction) *fraction = tail % m->rate_denominator;
    }
    return m->rate_origin_tick + whole;
}
static uint64_t mapped_clock(const a2vm *vm)
{
    return mapped_at(vm->clock_context, *vm->clock, NULL);
}
static void mapped_advance(a2vm *vm, uint64_t target)
{
    ap_machine *m = vm->clock_context;
    uint64_t now = mapped_clock(vm), fraction;
    if (target <= now) return;
    mapped_at(m, *vm->clock, &fraction);
    long double amount = ceill(((long double)(target - now) * m->rate_denominator -
                               fraction) / m->rate_numerator);
    uint64_t before = *vm->clock;
    uint64_t delta = amount >= UINT64_MAX - before ? UINT64_MAX - before : (uint64_t)amount;
    *vm->clock += delta;
    /* Correct possible long-double boundary rounding, including platforms
       where long double has the same precision as double. */
    while (*vm->clock < UINT64_MAX && mapped_clock(vm) < target) ++*vm->clock;
    while (*vm->clock > before && mapped_at(m, *vm->clock - 1, NULL) >= target) --*vm->clock;
}
int ap_acceleration(ap_machine *m, const char *profile)
{
    if (!m) return 0;
    m->error[0] = 0;
    unsigned units = 0;
    if (profile && !strcmp(profile, "mhz1")) units = 3;
    else if (profile && !strcmp(profile, "ultrawarp")) units = 40;
    else if (profile && !strcmp(profile, "vtw26")) units = 80;
    else if (profile && !strcmp(profile, "vtw33")) units = 100;
    else if (profile && !strcmp(profile, "turbo-f122"))
        return fail(m, "switching to historical TURBO requires restarting the machine");
    else return fail(m, "acceleration must be mhz1, ultrawarp, vtw26 or vtw33");
    if (m->vm->cost)
        return fail(m, "switching from historical TURBO requires restarting the machine");
    uint64_t numerator = m->launch_rate_units ?
        m->launch_rate_units * (1200 / units) :
        (uint64_t)llroundl((long double)m->launch_cpu_hz * m->rate_denominator /
                          (units * (1000000.0L / 3)));
    if (numerator == m->rate_numerator) return 1;
    a2vm *vm = m->vm;
    /* First finish events at the old rate. Neither their deadlines nor audio
       oscillator phases change; subsequent CPU cycles advance time differently. */
    a2vm_service_events(vm);
    ap_cards_tick(m->cards);
    ap_audio_sync(m->audio, a2vm_now(vm));
    uint64_t fraction = 0, now = vm->clock_read ?
        mapped_at(m, *vm->clock, &fraction) : *vm->clock;
    m->rate_origin_raw = *vm->clock;
    m->rate_origin_tick = now;
    m->rate_fraction = fraction;
    m->rate_numerator = numerator;
    m->nominal_cpu_hz = (uint64_t)llround(units * (1000000.0 / 3));
    vm->clock_context = m;
    vm->clock_read = mapped_clock;
    vm->clock_advance = mapped_advance;
    return 1;
}

ap_machine *ap_new(const char *rom_path, const char *cost_path,
                   double cpu_hz, double line_us, unsigned lines,
                   unsigned banks, char *error, size_t error_size)
{
    copy_error(error, error_size, "");
    if (!isfinite(cpu_hz) || cpu_hz <= 0 || !isfinite(line_us) ||
        line_us <= 0 || lines <= 192 || lines > 1024 ||
        banks < 1 || banks > A2VM_MAX_BANKS) {
        copy_error(error, error_size, "invalid clock, video standard or bank count");
        return NULL;
    }
    long double line_ticks = (long double)cpu_hz * line_us / 1000000.0L;
    long double frame_ticks = roundl(line_ticks * lines);
    long double vbl_ticks = roundl(line_ticks * 192);
    if (!isfinite(frame_ticks) || frame_ticks < 1 ||
        frame_ticks > (long double)UINT64_MAX / 4 || vbl_ticks < 1 ||
        vbl_ticks >= frame_ticks) {
        copy_error(error, error_size, "clock produces an invalid frame duration");
        return NULL;
    }
    ap_machine *m = calloc(1, sizeof *m);
    if (!m) {
        copy_error(error, error_size, "out of memory");
        return NULL;
    }
    a2vm_config config;
    a2vm_default_config(&config);
    config.rom_path = rom_path;
    config.core = A2VM_CORE_W65C02S;
    config.turbo = 0;
    config.speed = 1;               /* Replaced by the clock below. */
    config.io_cycles = 0;
    config.ramworks_banks = banks;
    config.amem = 1;
    m->vm = a2vm_new(&config, m->error, sizeof m->error);
    if (!m->vm)
        goto failed;
    a2vm *vm = m->vm;
    m->clock_hz = (uint64_t)llround(cpu_hz);
    m->launch_cpu_hz = cpu_hz;
    m->nominal_cpu_hz = m->clock_hz;
    m->launch_rate_units = rate_units(cpu_hz);
    m->rate_denominator = m->launch_rate_units ? 1200 : (UINT64_C(1) << 32);
    m->rate_numerator = m->rate_denominator;
    vm->via_timers = 1;
    vm->via_ora_nh = 1;
    a2vm_amem_options(vm, 1, 1, cost_path != NULL);
    vm->frame_cycles = (uint64_t)frame_ticks;
    vm->frame_1mhz = 65u * lines;
    vm->vbl_start = (uint64_t)vbl_ticks;
    vm->next_vbl = vm->vbl_start;
    vm->write_hook = observe_write;
    vm->hook_context = m;
    if (cost_path) {
        a2vm_cost_params params;
        if (!a2vm_cost_load(&params, cost_path, m->error, sizeof m->error))
            goto failed;
        if (!isfinite(params.fabric_mhz) || !isfinite(params.line_us) ||
            params.fabric_mhz <= 0 || params.line_us <= 0 ||
            params.lines <= params.vbl_line || params.lines > 1024) {
            fail(m, "invalid cost profile clock");
            goto failed;
        }
        a2vm_cost *cost = a2vm_cost_new(&params);
        if (!cost) {
            fail(m, "out of memory creating cost model");
            goto failed;
        }
        a2vm_attach_cost(vm, cost, 1);
        m->clock_hz = (uint64_t)llround(params.fabric_mhz * 1000000.0);
        if (params.zp_pair &&
            !a2vm_zpbank_arm(vm, 1, m->error, sizeof m->error))
            goto failed;
    }
    m->speech_xck_hz = (uint32_t)llround((double)m->clock_hz * vm->frame_1mhz / vm->frame_cycles);
    m->speech = ap_ssi_new(m->clock_hz, m->speech_xck_hz, a2vm_now(vm));
    if (!m->speech) { fail(m, "cannot initialize speech clock"); goto failed; }
    vm->sound_context = m;
    vm->sound_event = sound_event;
    vm->speech_read = speech_read;
    vm->speech_write = speech_write;
    vm->service_hook = service_speech;
    m->cards = ap_cards_new(vm);
    if (!m->cards) {
        fail(m, "out of memory creating slot-7 cards");
        goto failed;
    }
    return m;
failed:
    copy_error(error, error_size, m->error);
    ap_free(m);
    return NULL;
}

void ap_free(ap_machine *m)
{
    if (m) {
        ap_cards_free(m->cards);
        ap_audio_free(m->audio);
        ap_ssi_free(m->speech);
        free(m->events);
        a2vm_free(m->vm);
        free(m);
    }
}

int ap_run(ap_machine *m, uint64_t max_steps, uint64_t max_ticks,
           const uint16_t *breakpoints, unsigned count)
{
    if (!m)
        return AP_RUN_ERROR;
    m->error[0] = 0;
    if ((!max_steps && !max_ticks) || (count && !breakpoints) || count > 65536) {
        fail(m, "run requires a bound and a valid breakpoint list");
        return AP_RUN_ERROR;
    }
    uint8_t stops[8192] = {0};
    for (unsigned i = 0; i < count; i++)
        stops[breakpoints[i] >> 3] |= (uint8_t)(1u << (breakpoints[i] & 7));
    a2vm *vm = m->vm;
    uint64_t initial_steps = vm->instructions;
    uint64_t initial_ticks = a2vm_now(vm);
    for (;;) {
        if (vm->halt[0])
            return AP_RUN_HALT;
        if (vm->prodos && vm->prodos->quit)
            return AP_RUN_QUIT;
        if (vm->cpu.state == CPU65C02_STOPPED)
            return AP_RUN_STP;
        uint16_t pc = a2vm_pc(vm);
        if (count && (stops[pc >> 3] & (1u << (pc & 7))))
            return AP_RUN_BREAKPOINT;
        if (max_ticks && a2vm_now(vm) - initial_ticks >= max_ticks)
            return AP_RUN_TICKS;
        if (max_steps && vm->instructions - initial_steps >= max_steps)
            return AP_RUN_STEPS;
        if (m->audio && (a2vm_now(vm) >= m->audio_sync_tick || m->event_count >= 3072)) {
            ap_audio_sync(m->audio, a2vm_now(vm));
            m->audio_sync_tick = a2vm_now(vm) + m->clock_hz / 1000;
            if (ap_audio_overflow(m->audio) || m->event_overflow) {
                fail(m, "audio capture overflow; restart capture after draining more frequently");
                return AP_RUN_ERROR;
            }
            if (ap_audio_full(m->audio) || m->event_count >= 3072)
                return AP_RUN_AUDIO_FULL;
        }
        a2vm_service_events(vm);
        ap_cards_tick(m->cards);
        if (!ap_cards_step(m->cards))
            a2vm_step(vm);
    }
}

uint64_t ap_get(ap_machine *m, const char *name)
{
    if (!m || !name)
        return UINT64_MAX;
    m->error[0] = 0;
    a2vm *vm = m->vm;
    if (!strcmp(name, "pc")) return vm->cpu.pc;
    if (!strcmp(name, "sp")) return vm->cpu.s;
    if (name[0] && !name[1] && strchr("axysp", name[0]))
        return a2vm_register(vm, name[0]);
    if (!strcmp(name, "cycles")) return vm->cpu.cycles;
    if (!strcmp(name, "ticks")) return a2vm_now(vm);
    if (!strcmp(name, "steps")) return vm->instructions;
    if (!strcmp(name, "dhires")) return vm->dhires;
    if (!strcmp(name, "clock_hz")) return m->clock_hz;
    if (!strcmp(name, "nominal_cpu_hz")) return m->nominal_cpu_hz;
    if (!strcmp(name, "clock_scaled")) return vm->clock_read != NULL;
    if (!strcmp(name, "speech_xck_hz")) return m->speech_xck_hz;
    if (!strcmp(name, "audio_origin")) return m->audio_origin;
    if (!strcmp(name, "audio_rate")) return ap_audio_rate(m->audio);
    if (!strcmp(name, "audio_frames")) return ap_audio_frames(m->audio);
    if (!strcmp(name, "audio_events")) return m->event_count;
    if (!strcmp(name, "audio_overflow")) return ap_audio_overflow(m->audio) || m->event_overflow;
    if (!strcmp(name, "frame_ticks")) return vm->frame_cycles;
    if (!strcmp(name, "io_reads")) return vm->io_accesses - m->io_writes;
    if (!strcmp(name, "io_writes")) return m->io_writes;
    if (!strcmp(name, "io_accesses")) return vm->io_accesses;
    if (!strcmp(name, "video_writes")) return vm->video_writes;
    if (!strcmp(name, "shr_writes")) return vm->shr_writes;
    if (!strcmp(name, "bank")) return vm->bank;
    if (!strcmp(name, "banks")) return vm->ramworks_banks;
    if (!strcmp(name, "newvideo")) return vm->newvideo;
    if (!strcmp(name, "stopped")) return vm->cpu.state == CPU65C02_STOPPED;
    if (!strcmp(name, "waiting")) return vm->cpu.state == CPU65C02_WAITING;
    if (!strcmp(name, "irqs")) return vm->irqs;
    if (!strcmp(name, "slot2")) return (uint64_t)vm->slot2_mode;
    if (!strcmp(name, "slot7")) return ap_cards_slot7(m->cards);
    if (!strcmp(name, "sw")) {
        uint64_t switches = 0;
        for (unsigned i = 0; i < SW_COUNT; i++)
            if (vm->sw[i]) switches |= UINT64_C(1) << i;
        return switches;
    }
    fail(m, "unknown state field");
    return UINT64_MAX;
}

const char *ap_halt(ap_machine *m)
{
    return m ? m->vm->halt : "invalid machine";
}

const char *ap_error(ap_machine *m)
{
    return m ? m->error : "invalid machine";
}

int ap_set_reg(ap_machine *m, const char *name, unsigned value)
{
    if (!m)
        return 0;
    m->error[0] = 0;
    if (!name)
        return fail(m, "missing register name");
    if (!strcmp(name, "pc")) {
        if (value > 0xffff) return fail(m, "PC must fit in 16 bits");
        a2vm_set_register(m->vm, 'c', value);
        return 1;
    }
    if (!strcmp(name, "sp")) name = "s";
    if (!name[0] || name[1] || !strchr("axysp", name[0]))
        return fail(m, "unknown register");
    if (value > 0xff)
        return fail(m, "register must fit in 8 bits");
    a2vm_set_register(m->vm, name[0], value);
    return 1;
}

static uint8_t *storage(ap_machine *m, unsigned kind, unsigned bank,
                        unsigned address, size_t size)
{
    unsigned low = kind == 2 ? 0xc000 : kind == 3 ? 0xd000 : 0;
    unsigned end = kind == 3 ? 0xe000 : 0x10000;
    if (kind > 3 || (kind == 1 ? bank >= m->vm->ramworks_banks : bank != 0) ||
        address < low || address >= end || size > (size_t)(end - address)) {
        fail(m, "raw memory range is outside the selected storage");
        return NULL;
    }
    return a2vm_storage(m->vm, (int)kind, bank, (uint16_t)address);
}

int ap_read(ap_machine *m, unsigned kind, unsigned bank, unsigned address,
            void *buffer, size_t size)
{
    if (!m)
        return 0;
    m->error[0] = 0;
    if (size && !buffer)
        return fail(m, "missing read buffer");
    uint8_t *source = storage(m, kind, bank, address, size);
    if (!source)
        return 0;
    if (size) memcpy(buffer, source, size);
    return 1;
}

int ap_write(ap_machine *m, unsigned kind, unsigned bank, unsigned address,
             const void *buffer, size_t size)
{
    if (!m)
        return 0;
    m->error[0] = 0;
    if (size && !buffer)
        return fail(m, "missing write buffer");
    uint8_t *destination = storage(m, kind, bank, address, size);
    if (!destination)
        return 0;
    if (size) memcpy(destination, buffer, size);
    return 1;
}

int ap_bus_read(ap_machine *m, unsigned address)
{
    if (m && !audio_ready(m)) return -1;
    if (!m)
        return -1;
    m->error[0] = 0;
    if (address > 0xffff) {
        fail(m, "bus address must fit in 16 bits");
        return -1;
    }
    return a2vm_read(m->vm, (uint16_t)address);
}

int ap_bus_write(ap_machine *m, unsigned address, unsigned value)
{
    if (m && !audio_ready(m)) return 0;
    if (!m)
        return 0;
    m->error[0] = 0;
    if (address > 0xffff || value > 0xff)
        return fail(m, "bus address or value is out of range");
    a2vm_write(m->vm, (uint16_t)address, (uint8_t)value);
    return 1;
}

int ap_input(ap_machine *m, const char *kind, int x, int y)
{
    if (!m)
        return 0;
    m->error[0] = 0;
    if (!kind)
        return fail(m, "missing input kind");
    a2vm *vm = m->vm;
    if (!strcmp(kind, "key") || !strcmp(kind, "hold")) {
        if (x < 0 || x > 255)
            return fail(m, "key must fit in 8 bits");
        if (!strcmp(kind, "hold"))
            a2vm_hold(vm, (uint8_t)x);
        else {
            if (vm->key_count >= A2VM_MAX_KEYS)
                return fail(m, "key queue is full");
            a2vm_press(vm, (uint8_t)x, a2vm_now(vm));
        }
    } else if (!strcmp(kind, "release")) {
        a2vm_release(vm);
    } else if (!strcmp(kind, "mouse")) {
        a2vm_mouse_delta(vm, x, y);
    } else if (!strcmp(kind, "mouse-to")) {
        a2vm_mouse_move(vm, x, y);
    } else if (!strcmp(kind, "paddle")) {
        if (x < 0 || x > 3 || y < 0 || y > 255 ||
            !a2vm_set_paddle(vm, (unsigned)x, (unsigned)y))
            return fail(m, "paddle requires index 0..3 and value 0..255");
    } else if (!strcmp(kind, "pad")) {
        if (x < 0 || x > 3 || !a2vm_set_pad(vm, (unsigned)x, y))
            return fail(m, "pad requires index 0..3 and mask -1..4095");
    } else if (!strcmp(kind, "button")) {
        if (x < 0 || x > 2 || (y != 0 && y != 1))
            return fail(m, "button requires index 0..2 and value 0/1");
        m->joystick_buttons[x] = (uint8_t)y;
        vm->buttons[x] = (y || (x < 2 && m->apple_keys[x])) ? 0x80 : 0;
    } else if (!strcmp(kind, "buttons")) {
        if ((x != 0 && x != 1) || (y != 0 && y != 1))
            return fail(m, "buttons must be 0 or 1");
        a2vm_mouse_buttons(vm, x, y);
    } else if (!strcmp(kind, "oa") || !strcmp(kind, "ca")) {
        if (x != 0 && x != 1)
            return fail(m, "button must be 0 or 1");
        unsigned button = kind[0] == 'o' ? 0 : 1;
        m->apple_keys[button] = (uint8_t)x;
        vm->buttons[button] = (x || m->joystick_buttons[button]) ? 0x80 : 0;
    } else {
        return fail(m, "unknown input kind");
    }
    return 1;
}

static int valid_name(const char *name)
{
    if (!name || !name[0] || strlen(name) > 15 ||
        !isalpha((unsigned char)name[0]))
        return 0;
    for (const unsigned char *p = (const unsigned char *)name; *p; p++)
        if (!isalnum(*p) && *p != '.') return 0;
    return 1;
}

int ap_prodos(ap_machine *m, const char *volume, const char *launched)
{
    if (!m)
        return 0;
    m->error[0] = 0;
    if (!valid_name(volume) || !valid_name(launched))
        return fail(m, "volume and launched file must be ProDOS names");
    a2vm_prodos *next = prodos_new(volume, launched);
    if (!next)
        return fail(m, "out of memory creating ProDOS volume");
    prodos_free(m->vm->prodos);
    a2vm_attach_prodos(m->vm, next);
    return 1;
}

int ap_file(ap_machine *m, const char *name, unsigned type, unsigned aux,
            const void *bytes, size_t length)
{
    if (!m)
        return 0;
    m->error[0] = 0;
    if (!m->vm->prodos)
        return fail(m, "attach a ProDOS volume before adding files");
    if (!valid_name(name) || type > 0xff || aux > 0xffff ||
        length > 0xffffff || (length && !bytes))
        return fail(m, "invalid ProDOS file metadata or data");
    /* Open handles reference entries in the reallocatable file table. */
    if (m->vm->prodos->open_count)
        return fail(m, "cannot add files while ProDOS handles are open");
    static const uint8_t empty = 0;
    return prodos_add(m->vm->prodos, name, (uint8_t)type, (uint16_t)aux,
                       length ? bytes : &empty, length,
                       m->error, sizeof m->error);
}

int ap_cost_report(ap_machine *m, const char *path)
{
    if (!m)
        return 0;
    m->error[0] = 0;
    if (!m->vm->cost || !path || !path[0])
        return fail(m, "cost report requires a cost model and output path");
    FILE *out = fopen(path, "w");
    if (!out)
        return fail(m, "cannot open cost report");
    fputs("{\n", out);
    a2vm_cost_final(m->vm, out);
    fputs("  \"format\": \"appletini-cost-report-1\"\n}\n", out);
    int bad = ferror(out);
    if (fclose(out)) bad = 1;
    return bad ? fail(m, "cannot write cost report") : 1;
}

int ap_slot2(ap_machine *m, const char *mode)
{
    if (!m) return 0;
    m->error[0] = 0;
    int value;
    if (mode && !strcmp(mode, "off")) value = A2VM_SLOT2_OFF;
    else if (mode && !strcmp(mode, "mouse")) value = A2VM_SLOT2_MOUSE;
    else if (mode && !strcmp(mode, "4play")) value = A2VM_SLOT2_FOUR_PLAY;
    else if (mode && !strcmp(mode, "snes")) value = A2VM_SLOT2_SNES_MAX;
    else return fail(m, "slot 2 must be off, mouse, 4play or snes");
    return a2vm_set_slot2(m->vm, value);
}

int ap_slot7(ap_machine *m, const char *mode)
{
    if (m && !audio_ready(m)) return 0;
    if (!m) return 0;
    m->error[0] = 0;
    return ap_cards_mode(m->cards, mode) ||
             fail(m, "slot 7 must be smartport or supersprite");
}

int ap_mount_disk(ap_machine *m, const char *path)
{
    if (!m) return 0;
    m->error[0] = 0;
    return ap_cards_mount(m->cards, path, m->error, sizeof m->error);
}

int ap_card_read(ap_machine *m, const char *kind, unsigned offset,
                 void *buffer, size_t size)
{
    if (!m) return 0;
    m->error[0] = 0;
    return ap_cards_read(m->cards, kind, offset, buffer, size) ||
             fail(m, "unknown card memory or invalid range");
}

int ap_audio_enable(ap_machine *m, unsigned rate)
{
    if (!m) return 0;
    m->error[0] = 0;
    if (rate && (rate < 8000 || rate > 192000 || rate > m->clock_hz))
        return fail(m, "audio rate must be 8000..192000 Hz and no greater than the guest clock");
    ap_audio *next = NULL;
    ap_ssi_event *events = NULL;
    if (rate) {
        next = ap_audio_new(rate, m->clock_hz,
                (double)m->clock_hz * m->vm->frame_1mhz / m->vm->frame_cycles,
                a2vm_now(m->vm), m->vm->phasor.mode, m->vm->speaker_toggles & 1);
        events = calloc(4096, sizeof *events);
        if (!next || !events) { ap_audio_free(next); free(events); return fail(m, "out of memory creating audio capture"); }
        for (unsigned i = 0; i < 4; i++) ap_audio_seed(next, i, m->vm->phasor.ay[i]);
        uint8_t ay[16];
        if (ap_cards_read(m->cards, "supersprite-ay", 0, ay, sizeof ay)) ap_audio_seed(next, 4, ay);
    }
    ap_audio_free(m->audio); free(m->events);
    m->audio = next; m->events = events;
    m->event_head = m->event_count = m->event_overflow = 0;
    m->audio_origin = m->audio_sync_tick = a2vm_now(m->vm);
    return 1;
}
size_t ap_audio_available(ap_machine *m)
{
    if (!m) return 0;
    ap_audio_sync(m->audio, a2vm_now(m->vm));
    return ap_audio_count(m->audio);
}
size_t ap_audio_read(ap_machine *m, int16_t *stereo, size_t maxframes)
{
    if (!m) return 0;
    if (!stereo && maxframes) { fail(m, "audio output buffer is NULL"); return 0; }
    ap_audio_sync(m->audio, a2vm_now(m->vm));
    return ap_audio_take(m->audio, stereo, maxframes);
}
size_t ap_audio_event_read(ap_machine *m, ap_ssi_event *events, size_t maximum)
{
    if (!m) return 0;
    if (!events && maximum) { fail(m, "speech event output buffer is NULL"); return 0; }
    if (maximum > m->event_count) maximum = m->event_count;
    for (size_t i = 0; i < maximum; i++) events[i] = m->events[(m->event_head+i) % 4096];
    m->event_head = (m->event_head+maximum) % 4096;
    m->event_count -= maximum;
    return maximum;
}

int ap_boot(ap_machine *m, const void *slot_rom, size_t slot_size,
              const void *c8_rom, size_t c8_size)
{
    if (!m) return 0;
    a2vm *vm = m->vm;
    if (vm->instructions || vm->cpu.cycles || vm->prodos)
        return fail(m, "ROM boot requires a fresh machine without a ProDOS MLI stand-in");
    unsigned vector = vm->rom[0x3ffc] | (unsigned)vm->rom[0x3ffd] << 8;
    if (vector < 0xd000 || vector == 0xffff)
        return fail(m, "ROM boot requires a valid enhanced //e motherboard ROM reset vector");
    if (!ap_cards_boot(m->cards, slot_rom, slot_size, c8_rom, c8_size))
        return fail(m, "ROM boot needs mounted disk, SmartPort slot 7 and 256/2048-byte firmware");
    /* Initial construction provides convenience monitor ZP vectors for raw
     * programs. Let the real reset firmware initialize its own cold RAM. */
    memset(vm->main, 0, sizeof vm->main);
    memset(vm->sw, 0, sizeof vm->sw);
    vm->sw[SW_TEXT] = 1;
    vm->lc_bank2 = vm->lc_write = 1;
    vm->lc_read = vm->lc_prewrite = 0;
    vm->dhires = 0;
    a2vm_select_bank(vm, 0);
    a2vm_cpu_reset(vm);
    return 1;
}
