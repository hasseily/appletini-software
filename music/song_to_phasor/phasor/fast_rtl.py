"""Untimed C++ clock driver for the exact pinned SSI-263 RTL.

Every one of the original 384 fabric cycles per audio sample is evaluated.
Only host scheduling and file I/O change: no hardware state is approximated or
skipped. ``render`` has the same interface as :mod:`phasor.rtl`.
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

from .hardware import firmware_info
from .rtl import (CYCLES_PER_SAMPLE, FABRIC_HZ, SAMPLE_RATE, SOURCES, XCK_HZ,
                  _build_lock, _prepare_events, _read_stats, _run)

TESTBENCH = r'''module phasor_fast_ssi (
    input logic clk, rstn, audio_tick, xck_ce,
    input logic [1:0] write_strobe,
    input logic [2:0] reg_number,
    input logic [7:0] write_value,
    output logic [31:0] audio,
    output logic [1:0] starts, dones, active, busy,
    output logic [19:0] pitch
);
    for (genvar chip = 0; chip < 2; chip++) begin : chips
        ssi263_bus_wrapper #(.SSI263_TYPE(2), .HAS_SC01(0)) ssi (
            .clk(clk), .rstn(rstn), .apple_res(1'b1), .card_enabled(1'b1),
            .card_mode(3'd5), .audio_tick(audio_tick), .xck_ce(xck_ce),
            .ssi_write_strobe(write_strobe[chip]), .ssi_reg(reg_number),
            .ssi_wdata(write_value), .ssi_d7(),
            .votrax_write_strobe(1'b0), .votrax_wdata(8'd0), .via_pcr(8'd0),
            .via_ifr_set(), .via_ifr_clr(), .audio(audio[chip*16 +: 16]),
            .direct_irq(), .dbg_backend_done(), .dbg_enable_ints()
        );
        assign starts[chip] = ssi.backend_start_q;
        assign dones[chip] = ssi.formant_backend_done;
        assign active[chip] = !ssi.ctrl_art_amp_q[7] && ssi.ctrl_art_amp_q[3:0] != 0;
        assign busy[chip] = ssi.formant_backend_i.synth_state_q != 0;
        assign pitch[chip*10 +: 10] = ssi.formant_backend_i.digital_core_i.pitch_limit_q;
    end
endmodule
'''

DRIVER = r'''#include "Vphasor_fast_ssi.h"
#include "verilated.h"
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <vector>

struct Event { uint64_t cycle; unsigned target, reg, value; };
int main(int argc, char **argv) {
    if (argc != 7) return 2;
    Verilated::commandArgs(argc, argv);
    std::ifstream input(argv[1]), reset_input(argv[4]);
    std::ofstream output(argv[2], std::ios::binary), stats(argv[3]);
    const uint64_t frames = std::strtoull(argv[5], nullptr, 10);
    const uint64_t xck_hz = std::strtoull(argv[6], nullptr, 10);
    if (!input || !reset_input || !output || !stats) return 3;
    constexpr uint64_t fabric_hz = 18432000, cycles = 384;
    std::vector<Event> events;
    std::vector<uint64_t> resets;
    Event event;
    uint64_t reset_cycle;
    while (input >> event.cycle >> event.target >> event.reg >> event.value) events.push_back(event);
    while (reset_input >> reset_cycle) resets.push_back(reset_cycle);
    Vphasor_fast_ssi dut;
    dut.clk = 0; dut.rstn = 0; dut.audio_tick = 0; dut.xck_ce = 0;
    dut.write_strobe = 0; dut.reg_number = 0; dut.write_value = 0;
    auto clock_once = [&]() { dut.clk = 0; dut.eval(); dut.clk = 1; dut.eval(); };
    for (int i = 0; i < 8; ++i) clock_once();
    dut.rstn = 1;
    size_t index = 0, reset_index = 0;
    uint64_t xck_phase = 0, xck_edges = 0, max_delay = 0;
    uint64_t writes[2]{}, starts[2]{}, dones[2]{}, pitch_hist[2][1024]{};
    char buffer[4 * 1024];
    size_t buffered = 0;
    for (uint64_t cycle = 0; cycle < frames * cycles; ++cycle) {
        dut.write_strobe = 0;
        if (reset_index < resets.size() && resets[reset_index] == cycle) {
            dut.rstn = 0; dut.audio_tick = 0; dut.xck_ce = 0; xck_phase = 0;
            for (int i = 0; i < 8; ++i) clock_once();
            dut.rstn = 1;
            reset_index++;
        }
        if (index < events.size() && events[index].cycle <= cycle) {
            const auto &event = events[index++];
            dut.write_strobe = 1u << (event.target - 4);
            dut.reg_number = event.reg; dut.write_value = event.value;
            writes[event.target - 4]++;
            max_delay = std::max(max_delay, cycle - event.cycle);
        }
        dut.audio_tick = cycle % cycles == 0;
        if (dut.audio_tick && cycle && dut.busy) {
            std::fprintf(stderr, "SSI synthesis exceeded 384-cycle sample budget\n");
            return 5;
        }
        xck_phase += xck_hz;
        dut.xck_ce = xck_phase >= fabric_hz;
        if (dut.xck_ce) { xck_phase -= fabric_hz; xck_edges++; }
        for (unsigned chip = 0; chip < 2; ++chip) {
            starts[chip] += (dut.starts >> chip) & 1;
            dones[chip] += (dut.dones >> chip) & 1;
        }
        clock_once();
        if (cycle % cycles == cycles - 1) {
            for (unsigned byte = 0; byte < 4; ++byte) buffer[buffered++] = (dut.audio >> (8 * byte)) & 255;
            if (buffered == sizeof(buffer)) { output.write(buffer, buffered); buffered = 0; }
            for (unsigned chip = 0; chip < 2; ++chip)
                if ((dut.active >> chip) & 1) pitch_hist[chip][(dut.pitch >> (10 * chip)) & 1023]++;
        }
    }
    output.write(buffer, buffered);
    if (!output || index != events.size() || reset_index != resets.size()) return 4;
    stats << "xck_edges " << xck_edges << "\nmax_event_delay_cycles " << max_delay
          << "\nbank_resets " << reset_index << "\n";
    for (unsigned chip = 0; chip < 2; ++chip) {
        stats << "writes " << chip << ' ' << writes[chip] << '\n'
              << "starts " << chip << ' ' << starts[chip] << '\n'
              << "dones " << chip << ' ' << dones[chip] << '\n';
        for (unsigned period = 0; period < 1024; ++period)
            if (pitch_hist[chip][period]) stats << "pitch " << chip << ' ' << period << ' ' << pitch_hist[chip][period] << '\n';
    }
    dut.final();
    return stats ? 0 : 6;
}
'''


def source_fingerprint(firmware_root: Path) -> str:
    digest = hashlib.sha256((TESTBENCH + DRIVER).encode())
    for relative in SOURCES:
        digest.update(relative.encode())
        digest.update((Path(firmware_root) / relative).read_bytes())
    return digest.hexdigest()


def _binary(firmware_root: Path, cache_dir: Path) -> tuple[Path, bool, str]:
    verilator = shutil.which("verilator") or shutil.which("verilator-cli")
    if verilator is None:
        raise RuntimeError("SSI rendering requires Verilator 5+, make and a C++ compiler")
    version = subprocess.run([verilator, "--version"], check=True, capture_output=True,
                             text=True, timeout=10).stdout.strip()
    source_key = source_fingerprint(firmware_root)
    key = hashlib.sha256((source_key + version).encode()).hexdigest()[:24]
    cache_dir.mkdir(parents=True, exist_ok=True)
    build = cache_dir / ("fast-ssi-rtl-" + key)
    executable = build / "obj" / "Vphasor_fast_ssi"
    with _build_lock(cache_dir / ("fast-ssi-rtl-" + key + ".lock")):
        if executable.is_file():
            return executable, True, source_key
        build.mkdir(exist_ok=True)
        bench, driver = build / "phasor_fast_ssi.sv", build / "driver.cpp"
        bench.write_text(TESTBENCH, encoding="utf-8")
        driver.write_text(DRIVER, encoding="utf-8")
        command = [verilator, "--cc", "--exe", "--build", "-Wno-fatal", "-O3",
                   "--build-jobs", "2", "-CFLAGS", "-O3",
                   "-MAKEFLAGS", "CFG_CXXFLAGS_PCH_I=-include",
                   "--top-module", "phasor_fast_ssi", "--Mdir", str(build / "obj"),
                   *(str(firmware_root / name) for name in SOURCES), str(bench), str(driver)]
        _run(command, build, build / "build.log", timeout=300)
        if not executable.is_file():
            raise RuntimeError(f"Verilator did not create {executable}")
        (build / "model.json").write_text(json.dumps({"source_fingerprint": source_key,
                                                      "verilator": version}, indent=2) + "\n")
    return executable, False, source_key


def render(events: Iterable[tuple[int, int, int, int]], tick_hz: int,
           duration_ticks: int, firmware_root: Path, output: Path,
           cache_dir: Path, *, xck_hz: int = XCK_HZ,
           reset_ticks: Iterable[int] = ()) -> dict:
    """Render exact SSI PCM using all original fabric cycles without SV delays.

    Ordering, endpoint handling and simulation-only bank resets match rtl.render.
    The latter are for independent acoustic templates, never song playback.
    """
    if type(xck_hz) is not int or not 0 < xck_hz <= FABRIC_HZ:
        raise ValueError(f"xck_hz must be an integer in 1..{FABRIC_HZ}")
    prepared = _prepare_events(events, tick_hz, duration_ticks)
    resets = []
    for tick in reset_ticks:
        if type(tick) is not int or not 0 <= tick < duration_ticks:
            raise ValueError("reset_ticks must be integers within the render duration")
        if tick * SAMPLE_RATE % tick_hz:
            raise ValueError("Template resets must fall on 48 kHz sample boundaries")
        resets.append(tick * FABRIC_HZ // tick_hz)
    resets = sorted(set(resets))
    firmware_root, output, cache_dir = (Path(path).resolve() for path in
                                       (firmware_root, output, cache_dir))
    profile = firmware_info(firmware_root)
    if not profile["verified"]:
        raise ValueError("SSI renderer requires the pinned F1.2.4 firmware sources")
    frames = (duration_ticks * SAMPLE_RATE + tick_hz - 1) // tick_hz
    executable, cache_hit, source_key = _binary(firmware_root, cache_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="fast-ssi-render-", dir=cache_dir) as temporary:
        run = Path(temporary)
        event_file, raw_file, stats_file, reset_file = (run / name for name in
            ("events.txt", "audio.pcm", "stats.txt", "resets.txt"))
        event_file.write_text("".join("%d %d %d %d\n" % event for event in prepared), encoding="ascii")
        reset_file.write_text("".join(f"{cycle}\n" for cycle in resets), encoding="ascii")
        log = cache_dir / (run.name + ".log")
        _run([str(executable), str(event_file), str(raw_file), str(stats_file),
              str(reset_file), str(frames), str(xck_hz)], run, log,
             timeout=max(60.0, frames / SAMPLE_RATE * 60))
        if raw_file.stat().st_size != frames * 4:
            raise RuntimeError(f"Wrong SSI PCM length; see {log}")
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(2); wav.setsampwidth(2); wav.setframerate(SAMPLE_RATE)
            with raw_file.open("rb") as handle:
                while block := handle.read(1024 * 1024): wav.writeframesraw(block)
        statistics = _read_stats(stats_file)
    return {"renderer": "verilator-ssi263-bus-wrapper-cpp", "sample_rate": SAMPLE_RATE,
            "frames": frames, "channels": ["SSI left (target 4)", "SSI right (target 5)"],
            "scope": "SSI only; excludes AY chips and board output mixer",
            "xck_hz": xck_hz, "clock_assumption": "constant regional average raw Q3; DIV2 in RTL",
            "fabric_cycles_per_sample": CYCLES_PER_SAMPLE,
            "source_fingerprint": source_key, "firmware": profile,
            "binary_cache_hit": cache_hit, "render_seconds": time.monotonic() - started,
            "output": str(output), **statistics}
