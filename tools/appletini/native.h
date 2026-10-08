/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef APPLETINI_NATIVE_H
#define APPLETINI_NATIVE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ap_machine ap_machine;

enum ap_run_result {
    AP_RUN_ERROR = -1,
    AP_RUN_STEPS = 0,
    AP_RUN_TICKS = 1,
    AP_RUN_BREAKPOINT = 2,
    AP_RUN_HALT = 3,
    AP_RUN_STP = 4,
    AP_RUN_QUIT = 5,
    AP_RUN_AUDIO_FULL = 6
};

/* NULL ROM means zero-filled ROM. NULL cost means functional CPU timing,
 * without motherboard wait states. A cost file enables its TURBO clock. */
ap_machine *ap_new(const char *rom_path, const char *cost_path,
                   double cpu_hz, double line_us, unsigned lines,
                   unsigned banks, char *error, size_t error_size);
void ap_free(ap_machine *m);
/* Live functional CPU presets: mhz1, ultrawarp, vtw26, vtw33. RAM, PC and
 * device/audio timing persist. The clock_hz timebase stays at launch frequency;
 * cycles counts actual CPU cycles, ticks counts the stable device timeline.
 * Current or requested historical TURBO requires a fresh machine instead.
 * Preset-to-preset ratios are exact; custom launch Hz uses a Q32 ratio. */
int ap_acceleration(ap_machine *m, const char *profile);


/* Bounds are relative to this call; zero disables one bound, never both.
 * Breakpoints stop before executing the instruction, including the initial PC.
 * A tick bound may be exceeded by the final whole instruction. */
int ap_run(ap_machine *m, uint64_t max_steps, uint64_t max_ticks,
           const uint16_t *breakpoints, unsigned count);

/* Names: pc,a,x,y,s,sp,p,cycles,ticks,steps,frame_ticks,io_reads,io_writes,
 * io_accesses,video_writes,shr_writes,bank,banks,newvideo,sw,stopped,waiting,irqs,slot2,slot7.
 * cycles = core bus cycles; ticks = active clock (fabric clocks with cost).
 * sw packs the twelve switches in a2vm_switch order. io_* counts C000-C0FF.
 * Unknown names return UINT64_MAX; ap_error explains invalid operations. */
uint64_t ap_get(ap_machine *m, const char *name);
const char *ap_halt(ap_machine *m);
const char *ap_error(ap_machine *m);
int ap_set_reg(ap_machine *m, const char *name, unsigned value);

/* Raw storage, without I/O side effects. Kinds: main=0, aux=1, lc=2,
 * lc1=3. Main/aux addresses: 0000-FFFF; lc: C000-FFFF; lc1: D000-DFFF.
 * Non-aux kinds require bank 0. Entire transfer is validated first. */
int ap_read(ap_machine *m, unsigned kind, unsigned bank, unsigned address,
            void *buffer, size_t size);
int ap_write(ap_machine *m, unsigned kind, unsigned bank, unsigned address,
             const void *buffer, size_t size);
int ap_bus_read(ap_machine *m, unsigned address);
int ap_bus_write(ap_machine *m, unsigned address, unsigned value);

/* kind: key,hold,release,mouse,mouse-to,buttons,oa,ca,paddle,pad,button.
 * key/hold use x (0..255); button values are 0/1; mouse uses x,y. */
int ap_input(ap_machine *m, const char *kind, int x, int y);

/* A root-directory ProDOS MLI stand-in; file data is copied and owned by m.
 * Replacing the volume closes its files. Mutations remain in memory. */
int ap_prodos(ap_machine *m, const char *volume, const char *launched);
int ap_file(ap_machine *m, const char *name, unsigned type, unsigned aux,
            const void *bytes, size_t length);
int ap_cost_report(ap_machine *m, const char *path);
/* Slot selection is host configuration; SuperSprite replaces SmartPort. */
int ap_slot2(ap_machine *m, const char *mode); /* off, mouse, 4play, snes */
int ap_slot7(ap_machine *m, const char *mode); /* smartport, supersprite */
/* Mount unit 1 from a raw .po/.hdv image. Guest writes remain in RAM. */
int ap_mount_disk(ap_machine *m, const char *path);
/* Fresh-machine boot through the supplied motherboard ROM reset vector and
 * real slot-7 firmware, with the mounted disk and no ProDOS MLI stand-in.
 * Firmware buffers are copied; sizes must be 256 and 2048 bytes. */
int ap_boot(ap_machine *m, const void *slot_rom, size_t slot_size,
              const void *c8_rom, size_t c8_size);
/* kind: phasor-ay (64: four consecutive sets of 16 AY registers),
 * supersprite-vram (16384), supersprite-regs (8), supersprite-ay (16),
 * supersprite-state (8: status,address_lo,address_hi,latch,apple,overlay,ay_reg,mode).
 * The latter status read is observational; it does not acknowledge VBlank. */
int ap_card_read(ap_machine *m, const char *kind, unsigned offset,
                 void *buffer, size_t size);

/* Optional bounded guest-time audio, interleaved signed 16-bit stereo.
 * rate 0 disables capture; otherwise 8000..192000 Hz. Enabling starts a new
 * capture origin. AP_RUN_AUDIO_FULL requires draining both queues then run.
 * Sample n ends at ceil(origin + (n+1)*clock_hz/rate). No host clock is used.
 * SSI synthesis lives in the separately licensed speech worker; these events
 * transport its two controllers' writes (reg8 warm reset, reg9 cold reset). */
typedef struct ap_ssi_event {
    uint64_t tick;
    uint8_t chip, reg, value, reserved[5];
} ap_ssi_event;
int ap_audio_enable(ap_machine *m, unsigned rate);
size_t ap_audio_available(ap_machine *m);
size_t ap_audio_read(ap_machine *m, int16_t *stereo, size_t maxframes);
size_t ap_audio_event_read(ap_machine *m, ap_ssi_event *events, size_t maximum);

#ifdef __cplusplus
}
#endif

#endif
