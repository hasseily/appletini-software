"""Render the pinned firmware's two SSI-263 bus wrappers with Verilator.

No speech approximation runs here: the emitted PCM is the firmware RTL output.
The test bench compresses idle fabric time to 384 cycles per 48 kHz sample,
while supplying the regional raw Q3 clock enables (the core applies DIV2).
Register events, CTL mode latching, live inflection and FF writes all pass
through the real wrapper. AY chips and the board's final mixer are excluded.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import wave
from typing import Iterable

from .hardware import SSI_RAW_XCK_HZ, firmware_info

SAMPLE_RATE = 48_000
CYCLES_PER_SAMPLE = 384
FABRIC_HZ = SAMPLE_RATE * CYCLES_PER_SAMPLE
XCK_HZ = SSI_RAW_XCK_HZ
SOURCES = (
    "hdl/apple/ssi263_formant_pkg.sv",
    "hdl/apple/sc01a_digital_core.sv",
    "hdl/apple/ssi263_formant_backend.sv",
    "hdl/apple/ssi263_bus_wrapper.sv",
)

# The event file and output paths are runtime plusargs, never generated HDL.
# Sampling after the full fabric budget includes the just-completed sample.
TESTBENCH = r'''`timescale 1ns / 1ps
module phasor_render_tb;
    localparam int CYCLES = 384;
    localparam int FABRIC_HZ = 18432000;
    logic clk = 0, rstn = 0, audio_tick = 0, xck_ce = 0;
    logic [1:0] write_strobe = 0;
    logic [2:0] reg_number = 0;
    logic [7:0] write_value = 0;
    logic signed [15:0] left_audio, right_audio;
    ssi263_bus_wrapper #(.SSI263_TYPE(2), .HAS_SC01(0)) left_ssi (
        .clk(clk), .rstn(rstn), .apple_res(1'b1), .card_enabled(1'b1),
        .card_mode(3'd5), .audio_tick(audio_tick), .xck_ce(xck_ce),
        .ssi_write_strobe(write_strobe[0]), .ssi_reg(reg_number),
        .ssi_wdata(write_value), .ssi_d7(),
        .votrax_write_strobe(1'b0), .votrax_wdata(8'd0), .via_pcr(8'd0),
        .via_ifr_set(), .via_ifr_clr(), .audio(left_audio), .direct_irq(),
        .dbg_backend_done(), .dbg_enable_ints()
    );
    ssi263_bus_wrapper #(.SSI263_TYPE(2), .HAS_SC01(0)) right_ssi (
        .clk(clk), .rstn(rstn), .apple_res(1'b1), .card_enabled(1'b1),
        .card_mode(3'd5), .audio_tick(audio_tick), .xck_ce(xck_ce),
        .ssi_write_strobe(write_strobe[1]), .ssi_reg(reg_number),
        .ssi_wdata(write_value), .ssi_d7(),
        .votrax_write_strobe(1'b0), .votrax_wdata(8'd0), .via_pcr(8'd0),
        .via_ifr_set(), .via_ifr_clr(), .audio(right_audio), .direct_irq(),
        .dbg_backend_done(), .dbg_enable_ints()
    );
    string events_path, audio_path, stats_path, resets_path;
    integer events_fd, audio_fd, stats_fd, resets_fd, fields, reset_fields;
    integer next_target, next_reg, next_value;
    longint unsigned cycle_number, next_cycle, frames, xck_edges = 0;
    longint unsigned next_reset_cycle, reset_count = 0;
    integer xck_phase = 0, xck_hz;
    longint unsigned writes[0:1], starts[0:1], dones[0:1];
    longint unsigned pitch_hist[0:1][0:1023];
    longint unsigned max_event_delay = 0;

    task automatic clock_once;
        #5; clk = 1;
        #5; clk = 0;
    endtask
    task automatic read_event;
        fields = $fscanf(events_fd, "%d %d %d %d\n",
                         next_cycle, next_target, next_reg, next_value);
        if (fields != 4 && fields != -1 && fields != 0)
            $fatal(1, "Malformed register event");
    endtask
    task automatic read_reset;
        reset_fields = $fscanf(resets_fd, "%d\n", next_reset_cycle);
    endtask
    initial begin
        if (!$value$plusargs("events=%s", events_path) ||
            !$value$plusargs("audio=%s", audio_path) ||
            !$value$plusargs("stats=%s", stats_path) ||
            !$value$plusargs("resets=%s", resets_path) ||
            !$value$plusargs("frames=%d", frames) ||
            !$value$plusargs("xck=%d", xck_hz))
            $fatal(1, "Missing render arguments");
        events_fd = $fopen(events_path, "r");
        audio_fd = $fopen(audio_path, "wb");
        stats_fd = $fopen(stats_path, "w");
        resets_fd = $fopen(resets_path, "r");
        if (!events_fd || !audio_fd || !stats_fd || !resets_fd)
            $fatal(1, "Cannot open render files");
        for (int chip = 0; chip < 2; chip++) begin
            writes[chip] = 0; starts[chip] = 0; dones[chip] = 0;
            for (int period = 0; period < 1024; period++) pitch_hist[chip][period] = 0;
        end
        repeat (8) clock_once();
        rstn = 1;
        read_event();
        read_reset();
        for (cycle_number = 0; cycle_number < frames * CYCLES; cycle_number++) begin
            write_strobe = 0;
            if (reset_fields == 1 && next_reset_cycle == cycle_number) begin
                // Dictionary-only power reset: these extra fabric clocks do
                // not consume song time or emit audio. The complete wrapper,
                // interpolation, noise, pitch and tract state start afresh.
                rstn = 0; audio_tick = 0; xck_ce = 0; xck_phase = 0;
                repeat (8) clock_once();
                rstn = 1;
                reset_count++;
                read_reset();
            end
            if (fields == 4 && next_cycle <= cycle_number) begin
                write_strobe = next_target == 4 ? 2'b01 : 2'b10;
                reg_number = 3'(next_reg);
                write_value = 8'(next_value);
                writes[next_target - 4]++;
                if (cycle_number - next_cycle > max_event_delay)
                    max_event_delay = cycle_number - next_cycle;
                read_event();
            end
            audio_tick = (cycle_number % CYCLES == 0);
            if (audio_tick && cycle_number != 0 &&
                (left_ssi.formant_backend_i.synth_state_q != 0 ||
                 right_ssi.formant_backend_i.synth_state_q != 0))
                $fatal(1, "SSI synthesis exceeded 384-cycle sample budget");
            xck_phase += xck_hz;
            xck_ce = xck_phase >= FABRIC_HZ;
            if (xck_ce) begin xck_phase -= FABRIC_HZ; xck_edges++; end
            if (left_ssi.backend_start_q) starts[0]++;
            if (right_ssi.backend_start_q) starts[1]++;
            if (left_ssi.formant_backend_done) dones[0]++;
            if (right_ssi.formant_backend_done) dones[1]++;
            clock_once();
            if (cycle_number % CYCLES == CYCLES - 1) begin
                $fwrite(audio_fd, "%c%c%c%c", left_audio[7:0], left_audio[15:8],
                        right_audio[7:0], right_audio[15:8]);
                if (!left_ssi.ctrl_art_amp_q[7] && left_ssi.ctrl_art_amp_q[3:0] != 0)
                    pitch_hist[0][left_ssi.formant_backend_i.digital_core_i.pitch_limit_q]++;
                if (!right_ssi.ctrl_art_amp_q[7] && right_ssi.ctrl_art_amp_q[3:0] != 0)
                    pitch_hist[1][right_ssi.formant_backend_i.digital_core_i.pitch_limit_q]++;
            end
        end
        if (fields == 4) $fatal(1, "Register events exceeded render duration");
        if (reset_fields == 1) $fatal(1, "Reset event exceeded render duration");
        $fwrite(stats_fd, "xck_edges %0d\nmax_event_delay_cycles %0d\nbank_resets %0d\n",
                xck_edges, max_event_delay, reset_count);
        for (int chip = 0; chip < 2; chip++) begin
            $fwrite(stats_fd, "writes %0d %0d\nstarts %0d %0d\ndones %0d %0d\n",
                    chip, writes[chip], chip, starts[chip], chip, dones[chip]);
            for (int period = 0; period < 1024; period++)
                if (pitch_hist[chip][period] != 0)
                    $fwrite(stats_fd, "pitch %0d %0d %0d\n", chip, period, pitch_hist[chip][period]);
        end
        $fclose(events_fd); $fclose(audio_fd); $fclose(stats_fd); $fclose(resets_fd);
        $finish;
    end
endmodule
'''


def source_fingerprint(firmware_root: Path) -> str:
    """Hash the complete voice model and test bench, for a portable bank key."""
    digest = hashlib.sha256(TESTBENCH.encode())
    for relative in SOURCES:
        digest.update(relative.encode())
        digest.update((Path(firmware_root) / relative).read_bytes())
    return digest.hexdigest()


def _run(command: list[str], cwd: Path, log: Path, timeout: float) -> None:
    try:
        result = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        captured = exc.stdout or b""
        log.write_text(captured.decode(errors="replace") if isinstance(captured, bytes)
                       else captured, encoding="utf-8")
        raise RuntimeError(f"RTL command timed out after {timeout:g}s; see {log}") from exc
    log.write_text(result.stdout, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"RTL command failed ({result.returncode}); see {log}\n"
                           + result.stdout[-4000:])


@contextmanager
def _build_lock(path: Path):
    # Verilator is supported on Linux/macOS; flock also allows concurrent fit jobs
    # to share the cache without observing a partially linked executable.
    import fcntl
    with path.open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def _binary(firmware_root: Path, cache_dir: Path) -> tuple[Path, bool, str]:
    verilator = shutil.which("verilator") or shutil.which("verilator-cli")
    if verilator is None:
        raise RuntimeError("RTL rendering requires Verilator 5+, make and a C++ compiler")
    version = subprocess.run([verilator, "--version"], check=True, capture_output=True,
                             text=True, timeout=10).stdout.strip()
    source_key = source_fingerprint(firmware_root)
    key = hashlib.sha256((source_key + version).encode()).hexdigest()[:24]
    cache_dir.mkdir(parents=True, exist_ok=True)
    build = cache_dir / ("rtl-" + key)
    executable = build / "obj" / "Vphasor_render_tb"
    with _build_lock(cache_dir / ("rtl-" + key + ".lock")):
        if executable.is_file():
            return executable, True, source_key
        build.mkdir(exist_ok=True)
        bench = build / "phasor_render_tb.sv"
        bench.write_text(TESTBENCH, encoding="utf-8")
        command = [verilator, "--binary", "--timing", "-Wno-fatal", "-O3",
                   "--build-jobs", "2", "-CFLAGS", "-O3",
                   "-MAKEFLAGS", "CFG_CXXFLAGS_PCH_I=-include", "--top-module", "phasor_render_tb",
                   "--Mdir", str(build / "obj"),
                   *(str(firmware_root / name) for name in SOURCES), str(bench)]
        _run(command, build, build / "build.log", timeout=300)
        if not executable.is_file():
            raise RuntimeError(f"Verilator did not create {executable}")
        (build / "model.json").write_text(json.dumps({
            "source_fingerprint": source_key, "verilator": version,
        }, indent=2) + "\n", encoding="utf-8")
    return executable, False, source_key


def _prepare_events(events: Iterable[tuple[int, int, int, int]], tick_hz: int,
                    duration_ticks: int) -> list[tuple[int, int, int, int]]:
    for value, name in ((tick_hz, "tick_hz"), (duration_ticks, "duration_ticks")):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if tick_hz > FABRIC_HZ:
        raise ValueError(f"tick_hz cannot exceed the render fabric clock {FABRIC_HZ}")
    result = []
    previous = -1
    for event in events:
        if len(event) != 4 or any(isinstance(v, bool) or not isinstance(v, int) for v in event):
            raise ValueError("Events must contain four integers: tick, target, register, value")
        tick, target, register, value = event
        if not 0 <= tick <= duration_ticks:
            raise ValueError("Event tick falls outside the render duration")
        if tick < previous:
            raise ValueError("Events must be ordered by tick; equal ticks preserve write order")
        previous = tick
        if not 0 <= target <= 5 or not 0 <= value <= 255:
            raise ValueError("Invalid Phasor target or register value")
        if not 0 <= register <= (15 if target < 4 else 7):
            raise ValueError("Invalid Phasor register number")
        # Terminal silence writes at the exact endpoint have no emitted sample.
        if target >= 4 and tick < duration_ticks:
            result.append((tick * FABRIC_HZ // tick_hz, target, register, value))
    return result


def _read_stats(path: Path) -> dict:
    result = {"writes": [0, 0], "starts": [0, 0], "dones": [0, 0],
              "pitch_period_histograms": [{}, {}]}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, *raw = line.split()
        values = list(map(int, raw))
        if key == "pitch":
            chip, period, frames = values
            result["pitch_period_histograms"][chip][str(period)] = frames
        elif key in ("writes", "starts", "dones"):
            chip, count = values
            result[key][chip] = count
        else:
            result[key] = values[0]
    return result


def render(events: Iterable[tuple[int, int, int, int]], tick_hz: int,
           duration_ticks: int, firmware_root: Path, output: Path,
           cache_dir: Path, *, xck_hz: int = XCK_HZ,
           reset_ticks: Iterable[int] = ()) -> dict:
    """Write exact stereo SSI PCM16 at 48 kHz, returning model provenance.

    Targets 4/5 route to the left/right SSI. AY target events are validated and
    ignored. Events at one tick retain stream order, one accepted write per
    fabric cycle; metadata reports their maximum scheduling delay. Initialization
    is the caller's responsibility: no implicit register writes repair a stream.
    Endpoint writes at duration_ticks are validated but fall outside the PCM.
    ``reset_ticks`` adds simulation-only power resets before same-tick writes
    for independent acoustic templates, without advancing song time. Resets
    must lie on 48 kHz sample boundaries. Do not use them for song playback;
    ordinary Phasor register writes cannot perform these whole-chip resets.
    """
    if isinstance(xck_hz, bool) or not isinstance(xck_hz, int) or not 0 < xck_hz <= FABRIC_HZ:
        raise ValueError(f"xck_hz must be an integer in 1..{FABRIC_HZ}")
    prepared = _prepare_events(events, tick_hz, duration_ticks)
    resets = []
    for tick in reset_ticks:
        if isinstance(tick, bool) or not isinstance(tick, int) or not 0 <= tick < duration_ticks:
            raise ValueError("reset_ticks must be integers within the render duration")
        if tick * SAMPLE_RATE % tick_hz:
            raise ValueError("Template resets must fall on 48 kHz sample boundaries")
        resets.append(tick * FABRIC_HZ // tick_hz)
    resets = sorted(set(resets))
    firmware_root = Path(firmware_root).resolve()
    output = Path(output).resolve()
    cache_dir = Path(cache_dir).resolve()
    profile = firmware_info(firmware_root)
    if not profile["verified"]:
        raise ValueError("RTL renderer requires the pinned F1.2.4 firmware sources; "
                         f"version={profile['version']}, mismatches={profile['mismatches']}")
    frames = (duration_ticks * SAMPLE_RATE + tick_hz - 1) // tick_hz
    executable, cache_hit, source_key = _binary(firmware_root, cache_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    # Keep logs outside the temporary run directory so failures remain inspectable.
    with tempfile.TemporaryDirectory(prefix="render-", dir=cache_dir) as temporary:
        run = Path(temporary)
        event_file, raw_audio, stats_file = run / "events.txt", run / "audio.pcm", run / "stats.txt"
        reset_file = run / "resets.txt"
        event_file.write_text("".join("%d %d %d %d\n" % event for event in prepared),
                              encoding="ascii")
        reset_file.write_text("".join(f"{cycle}\n" for cycle in resets), encoding="ascii")
        log = cache_dir / (run.name + ".log")
        _run([str(executable), f"+events={event_file}", f"+audio={raw_audio}",
              f"+stats={stats_file}", f"+frames={frames}", f"+xck={xck_hz}",
              f"+resets={reset_file}"], run, log,
             timeout=max(60.0, frames / SAMPLE_RATE * 60))
        if raw_audio.stat().st_size != frames * 4:
            raise RuntimeError(f"Wrong RTL PCM length; see {log}")
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            with raw_audio.open("rb") as handle:
                while block := handle.read(1024 * 1024):
                    wav.writeframesraw(block)
        statistics = _read_stats(stats_file)
    return {
        "renderer": "verilator-ssi263-bus-wrapper", "sample_rate": SAMPLE_RATE,
        "frames": frames, "channels": ["SSI left (target 4)", "SSI right (target 5)"],
        "scope": "SSI only; excludes AY chips and board output mixer",
        "xck_hz": xck_hz, "clock_assumption": "constant regional average raw Q3; DIV2 in RTL",
        "fabric_cycles_per_sample": CYCLES_PER_SAMPLE,
        "source_fingerprint": source_key, "firmware": profile,
        "binary_cache_hit": cache_hit, "render_seconds": time.monotonic() - started,
        "output": str(output), **statistics,
    }
