// SPDX-License-Identifier: GPL-3.0-only
// The browser player: the vendored Appletini machine, its SSI-263 reference
// speech and an SHR frame, built with Emscripten by tools/web.py.
//
// The machine runs whole video frames. Audio is enabled from the start so the
// speech model sees every register write. tw_run collects the machine's PCM
// and SSI register events; tw_speech_render then mixes speech into that PCM,
// following speech.py's queue and worker.cpp's stream loop exactly. The page
// runs speech in a second instance of this module in a Web Worker, as the
// native runner runs it in a separate process; block sizes do not change PCM.
#include <emscripten/emscripten.h>

#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <memory>
#include <string>
#include <vector>

#include "native.h"

// worker.cpp defines the reference Voice model beside its separate-process
// stdin/stdout protocol. Only the Voice model is used here.
#define main ssi263_worker_main
#include "worker.cpp"
#undef main

namespace {

constexpr unsigned RATE = 48000;
constexpr unsigned WIDTH = 640, HEIGHT = 200;
constexpr double LINE_US = 63.695246;  // NTSC, as the runner's default
constexpr unsigned LINES = 262;
constexpr unsigned BANKS = 128;

struct Speech {
    Tables tables;
    std::array<std::unique_ptr<Voice>, 2> voices;
    uint64_t guest_hz = 0, xck_hz = 0, origin = 0, frame = 0, xck = 0;
    int gain = 1;
    std::deque<ap_ssi_event> pending;

    void start(uint64_t hz, uint64_t xck_rate, uint64_t first, int multiplier)
    {
        const int rom[] = {
#include "reference/rom.inc"
        };
        std::copy(std::begin(rom), std::end(rom), tables.native_rom.begin());
        for (auto& voice : voices) voice = std::make_unique<Voice>(tables, int(xck_rate));
        guest_hz = hz;
        gain = multiplier;
        xck_hz = xck_rate;
        origin = first;
        frame = xck = 0;
        pending.clear();
    }

    void advance(uint64_t guest_tick)
    {
        uint64_t relative = guest_tick - origin;
        uint64_t target = (relative / guest_hz) * xck_hz + (relative % guest_hz) * xck_hz / guest_hz;
        while (xck < target) { voices[0]->tick(); voices[1]->tick(); ++xck; }
    }

    void apply(const ap_ssi_event& e)
    {
        advance(e.tick);
        if (e.reg == 9) voices[e.chip] = std::make_unique<Voice>(tables, int(xck_hz));
        else if (e.reg == 8) voices[e.chip]->warm_reset();
        else voices[e.chip]->write(int(e.reg), int(e.value));
    }

    // Mixes speech into frames of interleaved stereo PCM in place.
    void render(int16_t *pcm, size_t frames)
    {
        const uint64_t boundary = origin + ((frame + frames) * guest_hz + 47999) / 48000;
        size_t count = 0;
        while (count < pending.size() && pending[count].tick <= boundary) ++count;
        size_t event = 0;
        for (size_t i = 0; i < frames; ++i) {
            uint64_t tick = origin + ((frame + 1) * guest_hz + 47999) / 48000;
            while (event < count && pending[event].tick < tick) apply(pending[event++]);
            advance(tick);
            for (unsigned chip = 0; chip < 2; ++chip) {
                int mixed = std::clamp(pcm[2 * i + chip] + gain * voices[chip]->sample(), -32768, 32767);
                pcm[2 * i + chip] = int16_t(mixed);
            }
            while (event < count && pending[event].tick == tick) apply(pending[event++]);
            ++frame;
        }
        pending.erase(pending.begin(), pending.begin() + std::ptrdiff_t(event));
    }
};

ap_machine *machine;
uint64_t frame_ticks;
int last_result;
char error[1024];
Speech speech;
std::vector<int16_t> out;
std::vector<ap_ssi_event> out_events;
std::array<ap_ssi_event, 256> events;
std::array<uint8_t, 0x8000> shr;
std::array<uint32_t, WIDTH * HEIGHT> rgba;

int fail(const char *message)
{
    std::snprintf(error, sizeof error, "%s", message);
    return 0;
}

int check(int result)
{
    if (!result) std::snprintf(error, sizeof error, "%s", ap_error(machine));
    return result;
}

void drain()
{
    size_t count;
    while ((count = ap_audio_event_read(machine, events.data(), events.size())) > 0) {
        out_events.insert(out_events.end(), events.begin(), events.begin() + std::ptrdiff_t(count));
        if (count < events.size()) break;
    }
    size_t frames = ap_audio_available(machine);
    if (!frames) return;
    const size_t start = out.size();
    out.resize(start + frames * 2);
    frames = ap_audio_read(machine, out.data() + start, frames);
    out.resize(start + frames * 2);
}

uint32_t pixel(unsigned r, unsigned g, unsigned b)
{
    return 0xff000000u | (b << 16) | (g << 8) | r;
}

}  // namespace

extern "C" {

// Profiles: 0 vtw33 (functional 33.33 MHz), 1 turbo-f122 (historical cost model).
// rom is the path of a 16 KiB enhanced //e ROM in the module's file system, or
// "" for the zero-filled ROM of a ProDOS MLI stand-in launch.
EMSCRIPTEN_KEEPALIVE int tw_create(int turbo, const char *rom)
{
    if (machine) ap_free(machine);
    out.clear();
    out_events.clear();
    error[0] = 0;
    last_result = 0;
    const double cpu_hz = turbo ? 133333333.333333 / 10 : 133333333.333333 / 4;
    machine = ap_new(rom && rom[0] ? rom : nullptr, turbo ? "/turbo-f122.cost" : nullptr, cpu_hz,
                     LINE_US, LINES, BANKS, error, sizeof error);
    if (!machine) return 0;
    frame_ticks = ap_get(machine, "frame_ticks");
    return check(ap_slot2(machine, "mouse"));
}

EMSCRIPTEN_KEEPALIVE int tw_volume(const char *volume, const char *system)
{
    return machine ? check(ap_prodos(machine, volume, system)) : fail("no machine");
}

EMSCRIPTEN_KEEPALIVE int tw_file(const char *name, int type, int aux, const uint8_t *data, int length)
{
    return machine ? check(ap_file(machine, name, unsigned(type), unsigned(aux), data, size_t(length)))
                   : fail("no machine");
}

// Loads the SYSTEM program at $2000, as the runner's ProDOS launch does, then
// selects SmartPort and starts audio capture. Start speech with this
// machine's clock_hz, speech_xck_hz and audio_origin.
EMSCRIPTEN_KEEPALIVE int tw_launch(const uint8_t *data, int length)
{
    if (!machine) return fail("no machine");
    if (length <= 0 || 0x2000 + length > 0xc000) return fail("program must fit at $2000-$BFFF");
    return check(ap_write(machine, 0, 0, 0x2000, data, size_t(length))) &&
           check(ap_set_reg(machine, "pc", 0x2000)) && check(ap_set_reg(machine, "s", 0xff)) &&
           check(ap_slot7(machine, "smartport")) && check(ap_audio_enable(machine, RATE));
}

// Boots a raw .po image as SmartPort unit 1 through the machine's ROM and the
// supplied 256-byte C700 and 2048-byte C800 firmware, as the runner's --boot
// does, with no MLI stand-in. Then selects SmartPort and starts audio capture.
EMSCRIPTEN_KEEPALIVE int tw_boot(const char *disk, const uint8_t *slot, int slot_size,
                                 const uint8_t *c8, int c8_size)
{
    if (!machine) return fail("no machine");
    return check(ap_mount_disk(machine, disk)) &&
           check(ap_boot(machine, slot, size_t(slot_size), c8, size_t(c8_size))) &&
           check(ap_slot7(machine, "smartport")) && check(ap_audio_enable(machine, RATE));
}

// Speech needs no machine; the page calls these in its speech worker.
// gain multiplies the reference speech output before mixing; 1 is the native
// worker's mix.
EMSCRIPTEN_KEEPALIVE void tw_speech_start(double guest_hz, double xck_hz, double origin, int gain)
{
    speech.start(uint64_t(guest_hz), uint64_t(xck_hz), uint64_t(origin), gain);
}

// Queues events (16-byte ap_ssi_event records, in tick order) and mixes speech
// into frames of interleaved stereo PCM in place.
EMSCRIPTEN_KEEPALIVE void tw_speech_render(int16_t *pcm, int frames, const ap_ssi_event *queued, int count)
{
    speech.pending.insert(speech.pending.end(), queued, queued + count);
    speech.render(pcm, size_t(frames));
}

// Runs whole video frames, ending each at a frame boundary. Returns the frames
// completed; stops early when the program halts or quits (see tw_result).
EMSCRIPTEN_KEEPALIVE int tw_run(int frames)
{
    if (!machine) {
        fail("no machine");
        return -1;
    }
    for (int done = 0; done < frames; ++done) {
        uint64_t now = ap_get(machine, "ticks");
        const uint64_t target = (now / frame_ticks + 1) * frame_ticks;
        while (now < target) {
            const int result = ap_run(machine, 0, target - now, nullptr, 0);
            drain();
            if (result == AP_RUN_ERROR) {
                check(0);
                return -1;
            }
            if (result == AP_RUN_HALT || result == AP_RUN_STP || result == AP_RUN_QUIT) {
                last_result = result;
                return done;
            }
            now = ap_get(machine, "ticks");
        }
    }
    return frames;
}

EMSCRIPTEN_KEEPALIVE int tw_result() { return last_result; }
EMSCRIPTEN_KEEPALIVE const char *tw_error() { return error; }
EMSCRIPTEN_KEEPALIVE const char *tw_halt() { return machine ? ap_halt(machine) : ""; }
EMSCRIPTEN_KEEPALIVE double tw_get(const char *name) { return machine ? double(ap_get(machine, name)) : -1; }

EMSCRIPTEN_KEEPALIVE int tw_input(const char *kind, int x, int y)
{
    return machine ? check(ap_input(machine, kind, x, y)) : fail("no machine");
}

// Raw storage for checks (kinds as ap_read). Returns NULL on error.
EMSCRIPTEN_KEEPALIVE const uint8_t *tw_read(int kind, int bank, int address, int length)
{
    static std::vector<uint8_t> buffer;
    if (!machine || length < 0) return nullptr;
    buffer.resize(size_t(length));
    return check(ap_read(machine, unsigned(kind), unsigned(bank), unsigned(address), buffer.data(),
                         buffer.size())) ? buffer.data() : nullptr;
}

// Audio produced since the last tw_audio_take: interleaved signed 16-bit stereo
// PCM without speech, and the SSI register events for tw_speech_render.
EMSCRIPTEN_KEEPALIVE int tw_audio_frames() { return int(out.size() / 2); }
EMSCRIPTEN_KEEPALIVE int16_t *tw_audio_data() { return out.data(); }
EMSCRIPTEN_KEEPALIVE int tw_event_count() { return int(out_events.size()); }
EMSCRIPTEN_KEEPALIVE const ap_ssi_event *tw_event_data() { return out_events.data(); }
EMSCRIPTEN_KEEPALIVE void tw_audio_take()
{
    out.clear();
    out_events.clear();
}

// The current SHR screen from AUX $2000-$9FFF as 640x200 RGBA, following the
// runner's preview decoder (video.py): 320-pixel rows are doubled. Returns
// NULL when SHR is off.
EMSCRIPTEN_KEEPALIVE const uint32_t *tw_screen()
{
    if (!machine || (ap_get(machine, "newvideo") & 0xc0) != 0xc0) return nullptr;
    if (!ap_read(machine, 1, 0, 0x2000, shr.data(), shr.size())) return nullptr;
    const bool gray = ap_get(machine, "newvideo") & 0x20;
    uint32_t palettes[16][16];
    for (unsigned p = 0; p < 16; ++p)
        for (unsigned i = 0; i < 16; ++i) {
            const unsigned off = 0x7e00 + 32 * p + 2 * i;
            const unsigned value = shr[off] | (shr[off + 1] << 8);
            unsigned r = (value >> 8 & 15) * 16, g = (value >> 4 & 15) * 16, b = (value & 15) * 16;
            if (gray) r = g = b = (77 * r + 150 * g + 29 * b) >> 8;
            palettes[p][i] = pixel(r, g, b);
        }
    for (unsigned y = 0; y < HEIGHT; ++y) {
        const unsigned scb = shr[0x7d00 + y];
        const uint32_t *palette = palettes[scb & 15];
        const uint8_t *row = &shr[y * 160];
        uint32_t *dst = &rgba[y * WIDTH];
        uint32_t previous = pixel(0, 0, 0);
        for (unsigned x = 0; x < 160; ++x) {
            const unsigned byte = row[x];
            if (scb & 0x80) {
                *dst++ = palette[8 + (byte >> 6 & 3)];
                *dst++ = palette[12 + (byte >> 4 & 3)];
                *dst++ = palette[0 + (byte >> 2 & 3)];
                *dst++ = palette[4 + (byte & 3)];
            } else {
                for (const unsigned value : {byte >> 4, byte & 15}) {
                    const uint32_t color = (scb & 0x20) && value == 0 ? previous : palette[value];
                    *dst++ = color;
                    *dst++ = color;
                    previous = color;
                }
            }
        }
    }
    return rgba.data();
}

}  // extern "C"
