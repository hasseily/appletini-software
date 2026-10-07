"""Render four real AY cores and two real SSI cores, then the neutral card mix.

SSI evaluates all 384 fabric cycles per sample with an untimed C++ driver,
verified sample-for-sample against the original timed SV renderer. The AY driver skips fabric clocks
only after all unclocked state has settled, and supplies the two adjacent CE
pulses per Apple CPU tick used by native Phasor. Both use the same compressed
18.432 MHz timeline. The neutral mix reproduces mockingboard.sv pan rounding,
AY scaling and saturation, but excludes the sub-sample mixer pipeline, user EQ,
and the DAC/output path. No peak normalization or DC removal is applied.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import wave
from typing import Iterable

from .hardware import AY_NATIVE_CLOCK_HZ, firmware_info
from .rtl import (FABRIC_HZ, SAMPLE_RATE, XCK_HZ, _build_lock, _prepare_events,
                  _run)
from .fast_rtl import render as render_ssi

# Frontend config_menu_phasor.c and apple_top.sv PHASOR_PAN_RESET, low nibble first.
DEFAULT_PAN = (11, 5, 11, 5, 11, 5, 11, 5, 11, 5, 11, 5)
SOURCES = ("hdl/apple/YM2149.sv",)
TESTBENCH = r'''module phasor_ay_render (
    input logic clk, reset, ce,
    input logic [3:0] bdir, bc,
    input logic [7:0] data,
    output wire [95:0] channels
);
    for (genvar chip = 0; chip < 4; chip++) begin : chips
        YM2149 ay (
            .CLK(clk), .CE(ce), .RESET(reset), .BDIR(bdir[chip]), .BC(bc[chip]),
            .DI(data), .DO(), .CHANNEL_A(channels[chip*24 +: 8]),
            .CHANNEL_B(channels[chip*24+8 +: 8]), .CHANNEL_C(channels[chip*24+16 +: 8]),
            .SEL(1'b0), .MODE(1'b1), .ACTIVE(),
            .IOA_in(8'd0), .IOA_out(), .IOB_in(8'd0), .IOB_out()
        );
    end
endmodule
'''

DRIVER = r'''#include "Vphasor_ay_render.h"
#include "verilated.h"
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <limits>
#include <vector>

struct Event { uint64_t cycle; unsigned target, reg, value; };
int main(int argc, char **argv) {
    if (argc != 6) return 2;
    Verilated::commandArgs(argc, argv);
    std::ifstream input(argv[1]);
    std::ofstream output(argv[2], std::ios::binary);
    const uint64_t frames = std::strtoull(argv[3], nullptr, 10);
    const uint64_t cpu_hz = std::strtoull(argv[4], nullptr, 10) / 2;
    const bool dense = std::strtoull(argv[5], nullptr, 10) != 0;
    if (!input || !output || !cpu_hz) return 3;
    constexpr uint64_t fabric_hz = 18432000, cycles = 384;
    constexpr uint64_t infinity = std::numeric_limits<uint64_t>::max();
    std::vector<Event> events;
    Event event;
    uint64_t available = 0, max_delay = 0;
    while (input >> event.cycle >> event.target >> event.reg >> event.value) {
        const uint64_t actual = std::max(event.cycle, available);
        max_delay = std::max(max_delay, actual - event.cycle);
        event.cycle = actual;
        available = actual + 2; // AY address latch, then data write.
        events.push_back(event);
    }
    Vphasor_ay_render dut;
    dut.clk = 0; dut.reset = 1; dut.ce = 0; dut.bdir = 0; dut.bc = 0; dut.data = 0;
    auto clock_once = [&]() { dut.clk = 0; dut.eval(); dut.clk = 1; dut.eval(); };
    for (int i = 0; i < 8; ++i) clock_once();
    dut.reset = 0;
    size_t index = 0;
    uint64_t ce_ordinal = 1, ce_edges = 0, evaluated = 0;
    uint64_t next_ce = (fabric_hz + cpu_hz - 1) / cpu_hz - 1;
    uint64_t flush = 0, data_cycle = infinity, dense_cycle = dense ? 0 : infinity;
    bool second_ce = false;
    Event pending{};
    char buffer[12 * 1024];
    size_t buffered = 0;
    for (uint64_t frame = 0; frame < frames; ++frame) {
        const uint64_t sample_cycle = (frame + 1) * cycles - 1;
        for (;;) {
            const uint64_t next_event = index < events.size() ? events[index].cycle : infinity;
            const uint64_t at = std::min({next_event, next_ce, flush, data_cycle, dense_cycle});
            if (at > sample_cycle) break;
            dut.ce = at == next_ce;
            dut.bdir = 0; dut.bc = 0;
            if (at == data_cycle) {
                dut.bdir = 1u << pending.target;
                dut.data = pending.value;
                data_cycle = infinity;
            } else if (at == next_event) {
                pending = events[index++];
                dut.bdir = 1u << pending.target;
                dut.bc = dut.bdir;
                dut.data = pending.reg;
                data_cycle = at + 1;
            }
            // The first inactive clock settles output and clears the write
            // strobes. All remaining idle clocks have no state changes.
            flush = (dut.ce || dut.bdir) ? at + 1 : infinity;
            if (dut.ce) {
                ce_edges++;
                if (!second_ce) { next_ce++; second_ce = true; }
                else {
                    ce_ordinal++;
                    next_ce = (ce_ordinal * fabric_hz + cpu_hz - 1) / cpu_hz - 1;
                    second_ce = false;
                }
            }
            clock_once(); evaluated++;
            if (dense) dense_cycle = at + 1;
        }
        for (unsigned channel = 0; channel < 12; ++channel)
            buffer[buffered++] = (dut.channels[channel / 4] >> ((channel % 4) * 8)) & 255;
        if (buffered == sizeof(buffer)) { output.write(buffer, buffered); buffered = 0; }
    }
    output.write(buffer, buffered);
    if (!output || index != events.size() || data_cycle != infinity) return 4;
    std::printf("{\"ce_edges\":%llu,\"evaluated_cycles\":%llu,\"max_event_delay_cycles\":%llu}\n",
        (unsigned long long)ce_edges, (unsigned long long)evaluated, (unsigned long long)max_delay);
    dut.final();
    return 0;
}
'''


def source_fingerprint(firmware_root: Path) -> str:
    digest = hashlib.sha256((TESTBENCH + DRIVER).encode())
    for relative in SOURCES + ("hdl/apple/mockingboard.sv",):
        digest.update(relative.encode())
        digest.update((Path(firmware_root) / relative).read_bytes())
    return digest.hexdigest()


def _binary(firmware_root: Path, cache_dir: Path) -> tuple[Path, bool, str]:
    verilator = shutil.which("verilator") or shutil.which("verilator-cli")
    if verilator is None:
        raise RuntimeError("Full rendering requires Verilator 5+, make and a C++ compiler")
    version = subprocess.run([verilator, "--version"], check=True, capture_output=True,
                             text=True, timeout=10).stdout.strip()
    source_key = source_fingerprint(firmware_root)
    key = hashlib.sha256((source_key + version).encode()).hexdigest()[:24]
    cache_dir.mkdir(parents=True, exist_ok=True)
    build = cache_dir / ("ay-rtl-" + key)
    executable = build / "obj" / "Vphasor_ay_render"
    with _build_lock(cache_dir / ("ay-rtl-" + key + ".lock")):
        if executable.is_file():
            return executable, True, source_key
        build.mkdir(exist_ok=True)
        bench, driver = build / "phasor_ay_render.sv", build / "driver.cpp"
        bench.write_text(TESTBENCH, encoding="utf-8")
        driver.write_text(DRIVER, encoding="utf-8")
        command = [verilator, "--cc", "--exe", "--build", "-Wno-fatal", "-O3",
                   "--build-jobs", "2", "-CFLAGS", "-O3",
                   "-MAKEFLAGS", "CFG_CXXFLAGS_PCH_I=-include",
                   "--top-module", "phasor_ay_render", "--Mdir", str(build / "obj"),
                   *(str(firmware_root / name) for name in SOURCES), str(bench), str(driver)]
        _run(command, build, build / "build.log", timeout=300)
        if not executable.is_file():
            raise RuntimeError(f"Verilator did not create {executable}")
    return executable, False, source_key


def _pan_gains(pan: tuple[int, ...]) -> tuple[list[int], list[int]]:
    if len(pan) != 12 or any(type(value) is not int or not 0 <= value <= 15 for value in pan):
        raise ValueError("pan must contain 12 integers in 0..15, in AY chip/channel order")
    left = [16] * 9 + [14, 11, 9, 7, 5, 2, 0]
    right = [0, 2, 4, 6, 8, 10, 12, 14] + [16] * 8
    return [left[value] for value in pan], [right[value] for value in pan]


def mix_ay(channels, pan=DEFAULT_PAN):
    """Reproduce per-channel shift/add pan rounding and native AY *16 scaling."""
    import numpy as np
    data = np.asarray(channels)
    if data.ndim != 2 or data.shape[1] != 12 or data.dtype != np.uint8:
        raise ValueError("AY channels must be a frames-by-12 uint8 array")
    gains = _pan_gains(tuple(pan))
    # Firmware shifts each term separately; sample*gain//16 rounds differently.
    terms = {0: (), 2: (3,), 4: (2,), 5: (2, 4), 6: (2, 3), 7: (2, 3, 4),
             8: (1,), 9: (1, 4), 10: (1, 3), 11: (1, 3, 4),
             12: (1, 2), 14: (1, 2, 3), 16: (0,)}
    mixed = np.zeros((len(data), 2), dtype=np.int32)
    for side, side_gains in enumerate(gains):
        for channel, gain in enumerate(side_gains):
            for shift in terms[gain]:
                mixed[:, side] += data[:, channel].astype(np.int32) >> shift
    return np.minimum(mixed * 16, 32767).astype("<i2")


def _write_wav(path: Path, audio) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(audio.astype("<i2").tobytes())


def render_ay(events: Iterable[tuple[int, int, int, int]], tick_hz: int,
              duration_ticks: int, firmware_root: Path, output: Path,
              cache_dir: Path, *, ay_clock_hz: int = AY_NATIVE_CLOCK_HZ,
              pan=DEFAULT_PAN, _dense: bool = False) -> dict:
    """Write actual four-chip AY audio with the card's neutral pan/scaling."""
    import numpy as np
    events = list(events)
    _prepare_events(events, tick_hz, duration_ticks)  # Shared strict stream validation.
    _pan_gains(tuple(pan))
    if type(ay_clock_hz) is not int or not 2 <= ay_clock_hz <= FABRIC_HZ // 2 or ay_clock_hz % 2:
        raise ValueError("ay_clock_hz must be a positive even integer <= FABRIC_HZ/2")
    firmware_root, output, cache_dir = map(lambda path: Path(path).resolve(),
                                           (firmware_root, output, cache_dir))
    profile = firmware_info(firmware_root)
    if not profile["verified"]:
        raise ValueError("AY renderer requires the pinned F1.2.4 firmware sources")
    executable, cache_hit, source_key = _binary(firmware_root, cache_dir)
    frames = (duration_ticks * SAMPLE_RATE + tick_hz - 1) // tick_hz
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ay-render-", dir=cache_dir) as temporary:
        run = Path(temporary)
        event_file, raw_file = run / "events.txt", run / "channels.pcm"
        prepared = [(tick * FABRIC_HZ // tick_hz, target, register, value)
                    for tick, target, register, value in events
                    if target < 4 and tick < duration_ticks]
        event_file.write_text("".join("%d %d %d %d\n" % event for event in prepared), encoding="ascii")
        log = cache_dir / (run.name + ".log")
        _run([str(executable), str(event_file), str(raw_file), str(frames), str(ay_clock_hz), str(int(_dense))],
             run, log, timeout=max(60.0, frames / SAMPLE_RATE * 30))
        if raw_file.stat().st_size != frames * 12:
            raise RuntimeError(f"Wrong AY PCM length; see {log}")
        audio = mix_ay(np.fromfile(raw_file, dtype=np.uint8).reshape(-1, 12), pan)
        _write_wav(output, audio)
        statistics = json.loads(log.read_text(encoding="utf-8"))
    return {"renderer": "verilator-four-ym2149", "frames": frames,
            "sample_rate": SAMPLE_RATE, "ay_clock_hz": ay_clock_hz,
            "volume_mode": "AY8913 (MODE=1)", "pan": list(pan),
            "clock_assumption": "constant regional CPU average; two adjacent native AY CE pulses per CPU tick",
            "fabric_hz": FABRIC_HZ, "source_fingerprint": source_key,
            "binary_cache_hit": cache_hit, "render_seconds": time.monotonic() - started,
            "firmware": profile, "output": str(output), **statistics}


def render_full(events: Iterable[tuple[int, int, int, int]], tick_hz: int,
                duration_ticks: int, firmware_root: Path, output: Path,
                cache_dir: Path, *, xck_hz: int = XCK_HZ,
                ay_clock_hz: int = AY_NATIVE_CLOCK_HZ, pan=DEFAULT_PAN,
                vocal_output: Path | None = None, backing_output: Path | None = None) -> dict:
    """Write the native neutral Phasor mix and optional unnormalized stems.

    Stems share the exact event timeline. Vocals are raw hard-panned SSI PCM;
    backing includes AY pan and *16 card scaling. Their saturating sum is the
    mixed WAV. The existing SSI renderer and its speech fitting API are intact.
    """
    import numpy as np
    events = list(events)
    _prepare_events(events, tick_hz, duration_ticks)
    _pan_gains(tuple(pan))
    output, cache_dir = Path(output).resolve(), Path(cache_dir).resolve()
    outputs = [output] + [Path(path).resolve() for path in (vocal_output, backing_output) if path is not None]
    if len(set(outputs)) != len(outputs):
        raise ValueError("Mixed output and stem outputs must use different paths")
    cache_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="full-render-", dir=cache_dir) as temporary:
        run = Path(temporary)
        vocals = Path(vocal_output).resolve() if vocal_output is not None else run / "vocals.wav"
        backing = Path(backing_output).resolve() if backing_output is not None else run / "backing.wav"
        ay_metadata = render_ay(events, tick_hz, duration_ticks, firmware_root, backing,
                                cache_dir, ay_clock_hz=ay_clock_hz, pan=pan)
        ssi_metadata = render_ssi(events, tick_hz, duration_ticks, firmware_root, vocals,
                                  cache_dir, xck_hz=xck_hz)
        def read_pcm(path):
            with wave.open(str(path), "rb") as wav:
                return np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").reshape(-1, 2).astype(np.int32)
        mixed = read_pcm(backing) + read_pcm(vocals)
        clipped = int(np.count_nonzero((mixed < -32768) | (mixed > 32767)))
        _write_wav(output, np.clip(mixed, -32768, 32767))
    # Avoid presenting ephemeral temporary paths as saved artifacts.
    ay_metadata["output"] = str(Path(backing_output).resolve()) if backing_output is not None else None
    ssi_metadata["output"] = str(Path(vocal_output).resolve()) if vocal_output is not None else None
    return {"renderer": "verilator-full-phasor-neutral", "sample_rate": SAMPLE_RATE,
            "frames": len(mixed), "channels": ["Phasor left", "Phasor right"],
            "scope": "actual AY and SSI RTL; neutral card pan/scaling/saturation; excludes sub-sample mixer pipeline, EQ and DAC",
            "normalization": "none; native card gain, no DC removal",
            "mix": "sat16(AY pan-rounded sum * 16 + raw SSI), separately for left/right",
            "saturated_samples": clipped, "peak_pcm": int(np.max(np.abs(np.clip(mixed, -32768, 32767)))),
            "output": str(output), "vocal_output": ssi_metadata["output"],
            "backing_output": ay_metadata["output"], "pan": list(pan),
            "render_seconds": time.monotonic() - started,
            "ay": ay_metadata, "ssi": ssi_metadata}
