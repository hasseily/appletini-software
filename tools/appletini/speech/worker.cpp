// SPDX-License-Identifier: GPL-3.0-only
// Separate reference executable. Never link this translation unit into a2vm.
#include "reference/native_control.h"
#include "reference/native_source.h"
#include "reference/prototype_tract.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
using namespace ssi_host;

// Current native_pitch.sv listening-model policy: 20kHz mean glide cadence.
struct Pitch {
    int duration{0xc0}, inflect{}, rate{}, control{0x80}, active{}, function{}, cadence{};
    bool seeded{};
    int live() const { return ((rate & 8) << 8) | (inflect << 3) | (rate & 7); }
    int value() const { return function == 3 ? active : live(); }
    void write(int reg, int val) {
        bool start = false;
        if (reg == 0) { duration = val; start = !(control & 0x80); }
        if (reg == 1) inflect = val;
        if (reg == 2) rate = val;
        if (reg == 3) {
            start = (control & 0x80) && !(val & 0x80);
            if (start && (duration >> 6)) function = duration >> 6;
            control = val;
        }
        if (start) {
            int old = active;
            active = live();
            if (function == 3) {
                if (seeded) active = (active & ~0x7c0) | (old & 0x7c0);
                seeded = true;
            }
        }
    }
    void sample() {
        if (cadence < 7) { cadence += 5; return; }
        cadence -= 7;
        static const int steps[] = {1,2,3,4,6,8,12,16};
        int target = (live() >> 6) & 31, field = (active >> 6) & 31;
        int step = steps[(live() >> 3) & 7];
        if (target > field) field += std::min(step, target - field);
        else field -= std::min(step, field - target);
        active = live();
        if (function == 3) active = (active & ~0x7c0) | (field << 6);
    }
};
struct Voice {
    NativeControl control;
    NativeSource source{16384};
    PrototypeTract tract{1};
    Pitch pitch;
    explicit Voice(const Tables& table, int hz): control(table, hz) { control.write(4, 0); }
    void tick() {
        control.set_ampct_zero(source.ampct_zero());
        control.advance_xck(1);
        source.tick(control, pitch.value());
        const auto& s = source.output();
        tract.process({s.phase, s.phase_edge,
            {s.f1,s.f2,s.f2q,s.f3,s.f4,s.filter_amp,s.voice_amp,s.fric_amp},
            s.voice_target_q16,s.fric_drive_q16,s.fric1,s.fric2,s.output_open});
    }
    void warm_reset() {
        control.warm_reset(); source = NativeSource(16384); tract = PrototypeTract(1);
        pitch.control = 0x80; pitch.cadence = 0;
    }
    void write(int reg, int val) { control.write(reg, val); pitch.write(reg, val); }
    int sample() {
        const int sample = tract.sample();
        pitch.sample();
        // Appletini default speech mixer +2dB, socket0 left/socket1 right.
        const int magnitude = (std::abs(sample) * 20626 + 8192) / 16384;
        return sample < 0 ? -magnitude : magnitude;
    }
};
static uint64_t number(const uint8_t *p, unsigned n) {
    uint64_t value = 0;
    for (unsigned i = 0; i < n; ++i) value |= uint64_t(p[i]) << (8*i);
    return value;
}
static void read_exact(char *p, size_t n) {
    std::cin.read(p, static_cast<std::streamsize>(n));
    if (static_cast<size_t>(std::cin.gcount()) != n) throw std::runtime_error("truncated stream packet");
}
static void append(std::vector<uint8_t>& data, uint64_t n, unsigned bytes) {
    for (unsigned i = 0; i < bytes; ++i) data.push_back((n >> (8*i)) & 255);
}
struct Event { uint64_t tick; unsigned chip, reg, value; };
int main(int argc, char **argv) {
    try {
        if (argc != 5 || std::string(argv[1]) != "--stream") {
            std::cerr << "usage: ssi263-speech --stream GUEST_HZ XCK_HZ ORIGIN\n"
                "SSI1 requests: LE uint32 frames, uint32 event_count; then events\n"
                "<uint64 tick,uint8 chip,reg,value,5 padding>, then frames*4 s16le PCM.\n"
                "SSO1 replies: LE uint32 PCM_bytes, then mixed s16le stereo.\n"
                "Registers0..7=write,8=AP warm reset,9=cold reset. See README.md.\n";
            return argc == 2 && std::string(argv[1]) == "--help" ? 0 : 2;
        }
        const uint64_t guest_hz = std::stoull(argv[2]), xck_hz = std::stoull(argv[3]);
        const uint64_t origin = std::stoull(argv[4]);
        if (guest_hz < 48000 || guest_hz > 1000000000 || !xck_hz || xck_hz > 10000000)
            throw std::runtime_error("clock out of range");
#ifdef _WIN32
        _setmode(_fileno(stdin), _O_BINARY); _setmode(_fileno(stdout), _O_BINARY);
#endif
        Tables tables;
        const int rom[] = {
#include "reference/rom.inc"
        };
        std::copy(std::begin(rom), std::end(rom), tables.native_rom.begin());
        std::array<std::unique_ptr<Voice>,2> voices;
        for (auto& voice : voices) voice = std::make_unique<Voice>(tables, int(xck_hz));
        uint64_t frame = 0, xck = 0, previous_tick = origin;
        auto advance = [&](uint64_t guest_tick) {
            uint64_t relative = guest_tick - origin;
            uint64_t target = (relative / guest_hz) * xck_hz +
                              (relative % guest_hz) * xck_hz / guest_hz;
            while (xck < target) { voices[0]->tick(); voices[1]->tick(); ++xck; }
        };
        while (std::cin.peek() != std::char_traits<char>::eof()) {
            uint8_t header[12]; read_exact(reinterpret_cast<char*>(header), 12);
            if (std::string(reinterpret_cast<char*>(header),4) != "SSI1")
                throw std::runtime_error("invalid stream magic");
            uint32_t frames = uint32_t(number(header+4,4)), count = uint32_t(number(header+8,4));
            if (frames > 480000 || count > 1000000) throw std::runtime_error("oversized stream block");
            uint64_t boundary = origin + ((frame + frames) * guest_hz + 47999) / 48000;
            std::vector<Event> events; events.reserve(count);
            uint64_t order = previous_tick;
            for (uint32_t i=0; i<count; ++i) {
                uint8_t b[16]; read_exact(reinterpret_cast<char*>(b),16);
                Event e{number(b,8),b[8],b[9],b[10]};
                if (e.tick < order || e.tick > boundary || e.chip > 1 || e.reg > 9)
                    throw std::runtime_error("invalid or out-of-order speech event");
                order=e.tick; events.push_back(e);
            }
            std::vector<uint8_t> pcm(size_t(frames)*4);
            read_exact(reinterpret_cast<char*>(pcm.data()),pcm.size());
            size_t event = 0;
            auto apply = [&](const Event& e) {
                advance(e.tick);
                if (e.reg == 9) voices[e.chip] = std::make_unique<Voice>(tables,int(xck_hz));
                else if (e.reg == 8) voices[e.chip]->warm_reset();
                else voices[e.chip]->write(int(e.reg),int(e.value));
            };
            for (uint32_t i=0; i<frames; ++i) {
                uint64_t tick = origin + ((frame + 1) * guest_hz + 47999) / 48000;
                while (event < events.size() && events[event].tick < tick) apply(events[event++]);
                advance(tick);
                for (unsigned chip=0; chip<2; ++chip) {
                    size_t offset=size_t(i)*4+chip*2;
                    int input=int(number(pcm.data()+offset,2)); if (input>=32768) input-=65536;
                    int mixed=std::clamp(input+voices[chip]->sample(),-32768,32767);
                    pcm[offset]=mixed&255; pcm[offset+1]=(mixed>>8)&255;
                }
                // Samples represent the elapsed interval ending at this tick.
                // A bus write at that boundary affects the following interval.
                while (event < events.size() && events[event].tick == tick) apply(events[event++]);
                ++frame; previous_tick=tick;
            }
            // Zero-length packets contain no events; the Python client queues them.
            if (event != events.size()) throw std::runtime_error("unconsumed speech events");
            std::vector<uint8_t> response{'S','S','O','1'}; append(response,pcm.size(),4);
            std::cout.write(reinterpret_cast<const char*>(response.data()),response.size());
            std::cout.write(reinterpret_cast<const char*>(pcm.data()),pcm.size()); std::cout.flush();
            if (!std::cout) throw std::runtime_error("speech output closed");
        }
        return 0;
    } catch (const std::exception& e) { std::cerr << "ssi263-speech: " << e.what() << '\n'; return 1; }
}
