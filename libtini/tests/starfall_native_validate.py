#!/usr/bin/env python3
"""Observe STARFALL through real keyboard input after an actual ProDOS boot.

The program image, game state, timer and inputs are never patched. Only the
frontend's exported diagnostic snapshots and the native machine are read.
Timing below belongs to two different emulator models, not to a board.
"""
from __future__ import annotations

import argparse
from collections import Counter
import ctypes as C
import json
from pathlib import Path
import re
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import native_emulator
from apple2_model import read_labels
import music
import scene_reference

AUDIO_RATE = 8000
WAV_SECONDS = 90


def song_periods():
    """Each STARFALL song track's AY base periods."""
    song = json.loads((ROOT / "assets/starfall/music/song.json").read_text(encoding="utf-8"))["song"]
    patterns = {name: music.parse_pattern(name, text) for name, text in song["patterns"].items()}
    return [{music.note_period(token[1]) for name in track["order"] for token in patterns[name]
             if token[0] == "row" and isinstance(token[1], int)} for track in song["tracks"]]


class SpeechEvent(C.Structure):
    _fields_ = [("tick", C.c_uint64), ("chip", C.c_uint8),
                ("reg", C.c_uint8), ("value", C.c_uint8),
                ("reserved", C.c_uint8 * 5)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="C:/msys64/ucrt64/bin/gcc.exe")
    parser.add_argument("--phasor", action="store_true", help="start through P with native Phasor audio")
    parser.add_argument("--profile", choices=("vtw33", "turbo-f122"))
    parser.add_argument("--gameover-seconds", type=int, default=480,
                        help="bounded model-time budget for an unattended survival run")
    args = parser.parse_args()
    if args.gameover_seconds < 1:
        parser.error("--gameover-seconds must be positive")
    library = native_emulator.build(args.cc)
    sys.path.insert(0, str(native_emulator.FRONT))
    import cli
    from video import screenshot
    cli.build_library = lambda: library

    build_dir = ROOT / "build"
    output = ROOT / ("build/starfall/native-ui-phasor" if args.phasor else "build/starfall/native-ui")
    output.mkdir(parents=True, exist_ok=True)
    labels = read_labels(build_dir / "starfall.lbl")
    disk_path = build_dir / "starfall.po"
    image = (build_dir / "starfall.system").read_bytes()
    speech_header = (build_dir / "starfall_speech.h").read_text()
    phrases = {
        int(phrase): [int(value) for value in values.split(",")]
        for phrase, values in re.findall(
            r"sf_speech_p(\d+)\[\]\s*=\s*\{([\d,]+)\}", speech_header)
    }
    evidence = {
        "board_evidence": False,
        "audio_personality": "phasor" if args.phasor else "mockingboard",
        "state_mutations": False,
        "disk_sha256": native_emulator.digest(disk_path),
        "system_sha256": native_emulator.digest(build_dir / "starfall.system"),
        "runs": [],
    }
    profiles = [args.profile] if args.profile else ("vtw33", "turbo-f122")
    previous_path = output / "validation.json"
    if args.profile and previous_path.is_file():
        previous = json.loads(previous_path.read_text())
        if (previous.get("disk_sha256") == evidence["disk_sha256"] and
                previous.get("system_sha256") == evidence["system_sha256"] and
                previous.get("audio_personality") == evidence["audio_personality"]):
            evidence["runs"] = [run for run in previous["runs"]
                                if run["profile"] != args.profile]
    for profile in profiles:
        rom = ROOT / "build-inputs/native-roms"
        options = cli.parser().parse_args([
            "debug", "--boot", "--disk", str(disk_path), "--profile", profile,
            "--rom", str(rom / "Apple2e_Enhanced.rom"),
            "--slot7-rom", str(rom / "smartport_a2retronet_style_c700.mem"),
            "--slot7-c8-rom", str(rom / "smartport_a2retronet_style_c800.mem"),
            "--video-rom", str(rom / "apple2e-video.bin"),
        ])
        machine = cli.Machine(options)
        trace = []
        screens = {}
        observations = []
        timing = {}
        speech_events = []
        captions_seen = set()
        capturing_audio = False
        pcm_frames = bytearray()
        # Per voice, how often each tone period was heard while playing.
        voice_periods = [Counter() for _ in range(12)]
        minimum_hardware_sp = 255
        minimum_software_sp = 0xBF00
        poll_address = labels["_ti_input_poll"]
        playfield_checks = 0

        def playfield():
            # Between frames the playfield must show exactly the last drawn
            # sprite list, rendered independently from the arrays in memory.
            nonlocal playfield_checks
            problem = scene_reference.mismatch(lambda address, length: machine.read("main", address, length),
                                               lambda address, length: machine.read("aux", address, length),
                                               labels)
            assert problem is None, (profile, "playfield differs from its sprite list", problem)
            playfield_checks += 1

        def drain():
            if not capturing_audio:
                return
            available = machine.lib.ap_audio_available(machine.handle)
            if available:
                pcm = C.create_string_buffer(available * 4)
                machine.lib.ap_audio_read(machine.handle, pcm, available)
                if len(pcm_frames) < WAV_SECONDS * AUDIO_RATE * 4:
                    pcm_frames.extend(pcm.raw)
            if number("_sf_mode") == 1:
                # Phasor voice v is channel v % 3 of AY v / 3. Mockingboard
                # voices 3-5 are on the card's second AY, index 2 here.
                ay = machine.card_read("phasor-ay", 0, 64)
                native = number("_ti_audio_native")
                for voice in range(12 if native else 6):
                    chip = voice // 3 if native else 2 * (voice // 3)
                    channel = voice % 3
                    regs = ay[chip * 16:chip * 16 + 16]
                    if regs[8 + channel] & 15:
                        voice_periods[voice][regs[2 * channel] | (regs[2 * channel + 1] & 15) << 8] += 1
            events = (SpeechEvent * 4096)()
            count = machine.lib.ap_audio_event_read(machine.handle, events, 4096)
            speech_events.extend({"tick": event.tick, "chip": event.chip,
                                  "reg": event.reg, "value": event.value}
                                 for event in events[:count])

        def run(**kwargs):
            result = machine.run(**kwargs)
            drain()
            return result

        def phrase_observed(index):
            wanted = phrases[index]
            # A real phoneme write remains distinct even when values repeat.
            # Test each physical SSI socket's ordered register-zero stream.
            for chip in (0, 1):
                values = [event["value"] for event in speech_events
                          if event["chip"] == chip and event["reg"] == 0 and
                          event["value"] != 0xC0]
                if any(values[i:i + len(wanted)] == wanted
                       for i in range(len(values) - len(wanted) + 1)):
                    return True
            return False

        def number(name, size=1, signed=False):
            return int.from_bytes(machine.read("main", labels[name], size),
                                  "little", signed=signed)

        def state():
            value = {
                "mode": number("_sf_mode"),
                "error": number("_ti_error_kept", 1),
                "player": [number("_sf_player_x", 2, True),
                           number("_sf_player_y", 2, True)],
                "hull": number("_sf_hull"),
                "weapon": number("_sf_weapon"),
                "enemies": number("_sf_enemy_count"),
                "bullets": number("_sf_bullet_count"),
                "tick": number("_sf_tick", 4),
                "score": number("_sf_score", 4),
                "rendered_frames": number("_sf_frames", 4),
                "simulation_steps": number("_sf_steps", 4),
                "audio_ticks": number("_ti_clock_counter", 4),
                "amem_hook_active": bool(number("_ti_accel_rw_hook", 2)),
                "model_ticks": machine.get("ticks"),
                "irqs": machine.get("irqs"),
                "caption": number("_sf_caption"),
            }
            for label, name in (("_sf_enemy_types_seen", "enemy_types_seen"),
                                ("_sf_enemy_peak", "enemy_peak"),
                                ("_sf_bullet_peak", "bullet_peak"),
                                ("_sf_lag", "lag"), ("_sf_stick", "stick"),
                                ("_sf_sector", "sector")):
                if label in labels:
                    value[name] = number(label)
            if "_sf_joystick" in labels:
                value["joystick"] = list(machine.read("main", labels["_sf_joystick"], 2))
            return value

        def sample():
            nonlocal minimum_hardware_sp, minimum_software_sp
            observed = state()
            captions_seen.add(observed["caption"])
            assert observed["error"] == 0, (profile, "runtime error", observed)
            hardware = machine.get("s")
            minimum_hardware_sp = min(minimum_hardware_sp, hardware)
            assert hardware >= 128, (profile, "sampled hardware stack", hardware)
            software = number("c_sp", 2)
            assert 0xB700 <= software <= 0xBF00, (profile, "sampled C stack", software)
            minimum_software_sp = min(minimum_software_sp, software)
            return observed

        def settle():
            # Every observation is at a complete frontend-loop boundary. A
            # rendered frame may take several model video frames to finish.
            if machine.get("pc") == poll_address:
                run(steps=1)
            result = run(frames=360, breakpoints=[poll_address], timeout=30)
            assert result["reason"] == "breakpoint", (profile, "input poll deadline", result)
            return sample()

        def advance(frames=1):
            if machine.get("pc") == poll_address:
                run(steps=1)
            while frames:
                count = min(frames, 6)
                result = run(frames=count, timeout=30)
                assert result["reason"] == "cycles", (profile, result)
                frames -= count
            return settle()

        def key(value):
            machine.check(machine.lib.ap_input(machine.handle, b"key",
                          ord(value) if isinstance(value, str) else value, 0))
            observed = settle()
            assert not machine.lib.ap_bus_read(machine.handle, 0xC000) & 128, (
                profile, "keyboard strobe not consumed", value, observed)
            return observed

        def hold(value):
            # The keyboard latch with its strobe, and any-key-down until release.
            machine.check(machine.lib.ap_input(machine.handle, b"hold", ord(value), 0))

        def release():
            machine.check(machine.lib.ap_input(machine.handle, b"release", 0, 0))

        def until(predicate, model_frames=1800):
            start = machine.get("ticks")
            budget = model_frames * machine.get("frame_ticks")
            observed = sample()
            while not predicate(observed):
                assert machine.get("ticks") - start < budget, (
                    profile, "UI deadline", observed)
                observed = advance(1)
            return observed

        def step_for(count):
            start = sample()["simulation_steps"]
            return until(lambda value: value["mode"] != 1 or
                         value["simulation_steps"] - start >= count)

        def capture(name):
            path = output / f"{name}-{profile}.png"
            screenshot(machine, path)
            screens[name] = {"path": path.relative_to(ROOT).as_posix(),
                             "sha256": native_emulator.digest(path)}

        try:
            # Stop at the true SYS entry and compare every loaded byte before
            # allowing startup to alter BSS, the video state or interrupt setup.
            for _ in range(8):
                entry = run(frames=600, breakpoints=[0x2000], timeout=30)
                assert entry["reason"] == "breakpoint", entry
                if machine.read("main", 0x2000, 16) == image[:16]:
                    assert machine.read("main", 0x2000, len(image)) == image, (
                        profile, "ProDOS SYS load differs")
                    trace.append({"event": "entire-sys-loaded", "bytes": len(image), "equal": True})
                    run(steps=1)
                    break
                run(steps=1)
            else:
                raise AssertionError("STARFALL SYS entry was not observed")

            observed = settle()
            assert observed["mode"] == 0 and machine.get("newvideo") == 0xC1, observed
            # STARFALL has no optional-AMEM build.
            assert not observed["amem_hook_active"], (profile, "AMEM hooks active", observed)
            capture("title")
            trace.append({"event": "title", **observed})
            machine.check(machine.lib.ap_audio_enable(machine.handle, AUDIO_RATE))
            capturing_audio = True
            observed = key("P" if args.phasor else 13)
            assert observed["mode"] == 1, ("launch did not enter play", observed)
            assert bool(number("_ti_audio_native")) == args.phasor, (
                "audio personality did not probe as requested", args.phasor, observed)
            assert observed["hull"] > 0, observed
            initial_hull = observed["hull"]
            trace.append({"event": "started-by-phasor-key" if args.phasor else "started-by-enter",
                          **observed})

            # Autofire, and keys that move the ship while held through the
            # Apple keyboard latch and any-key-down bit. Release stops it; a
            # tap shorter than a frame still moves it once.
            until(lambda value: value["bullets"] > 0)
            initial = sample()["player"]
            hold("A")
            observed = step_for(6)
            assert observed["mode"] == 1 and observed["player"][0] < initial[0], observed
            release()
            step_for(2)
            stopped = sample()["player"]
            observed = step_for(4)
            assert observed["player"] == stopped, ("release did not stop movement", stopped, observed)
            hold("D")
            observed = step_for(6)
            assert observed["player"][0] > stopped[0], observed
            release()
            hold("W")
            before = sample()["player"][1]
            observed = step_for(4)
            assert observed["player"][1] < before, observed
            release()
            hold("S")
            before = sample()["player"][1]
            observed = step_for(4)
            assert observed["player"][1] > before, observed
            release()
            step_for(2)
            before = sample()["player"]
            key("A")
            observed = step_for(4)
            assert before[0] > observed["player"][0] >= before[0] - 12, ("tap", before, observed)
            stopped = observed["player"]
            assert step_for(4)["player"] == stopped, ("tap kept moving", stopped)
            trace.append({"event": "autofire-and-four-held-directions", **sample()})

            key(" ")
            observed = until(lambda value: value["caption"] == 3)
            trace.append({"event": "keyboard-bomb-and-all-clear-caption", **observed})

            # The model has no counting VIA T2, so these reads exercise the
            # library's T1C-H fallback. Paddles start centred at 128.
            def paddle(index, value):
                machine.check(machine.lib.ap_input(machine.handle, b"paddle", index, value))

            def button(index, value):
                machine.check(machine.lib.ap_input(machine.handle, b"button", index, value))

            observed = step_for(4)
            assert observed.get("stick") == 1, ("centred joystick not answering", observed)
            before = observed["player"]
            paddle(0, 255)
            observed = step_for(8)
            assert observed["player"][0] > before[0] and observed["player"][1] == before[1], (
                "joystick right", before, observed)
            paddle(0, 128)
            step_for(3)
            stopped = sample()["player"]
            observed = step_for(4)
            assert observed["player"] == stopped, ("centred joystick did not stop", observed)
            paddle(1, 0)
            observed = step_for(6)
            assert observed["player"][1] < stopped[1], ("joystick up", stopped, observed)
            paddle(1, 128)
            paddle(0, 0)
            before = step_for(3)["player"]
            observed = step_for(6)
            assert observed["player"][0] < before[0], ("joystick left", before, observed)
            paddle(0, 128)
            step_for(3)
            trace.append({"event": "joystick-fallback-moves-and-centres", **sample()})
            until(lambda value: value["caption"] != 3, model_frames=600)
            button(0, 1)
            observed = until(lambda value: value["caption"] == 3)
            button(0, 0)
            trace.append({"event": "joystick-button-bomb", **observed})

            key("P")
            paused = until(lambda value: value["mode"] == 3)
            capture("pause")
            observed = advance(120)
            assert observed["mode"] == 3 and observed["tick"] == paused["tick"], observed
            assert observed["simulation_steps"] == paused["simulation_steps"], observed
            assert observed["audio_ticks"] > paused["audio_ticks"], observed
            trace.append({"event": "pause-freezes-simulation-with-live-clock", **observed})
            key(13)
            until(lambda value: value["mode"] == 1)

            # A real stick rarely rests at 128 or travels equally both ways.
            # Restart with an off-centre rest: deflections the old fixed
            # 80/175 thresholds ignored must now move the ship, and the rest
            # itself must not.
            paddle(0, 165)
            paddle(1, 95)
            key("R")
            observed = until(lambda value: value["mode"] == 1 and value["tick"] <= 6)
            rest = observed["player"]
            observed = step_for(8)
            assert observed["player"] == rest, ("off-centre rest moved the ship", rest, observed)
            paddle(0, 105)
            observed = step_for(6)
            assert observed["player"][0] < rest[0] and observed["player"][1] == rest[1], (
                "off-centre joystick left", rest, observed)
            paddle(0, 165)
            step_for(3)
            stopped = sample()["player"]
            observed = step_for(4)
            assert observed["player"] == stopped, ("off-centre rest did not stop", observed)
            paddle(1, 150)
            observed = step_for(6)
            assert observed["player"][1] > stopped[1] and observed["player"][0] == stopped[0], (
                "off-centre joystick down", stopped, observed)
            paddle(1, 95)
            step_for(3)
            trace.append({"event": "off-centre-joystick-calibrated", **sample()})

            # GREAT SHOT marks the x8 multiplier, which needs overdrive and a
            # fifteen-kill chain. Check two sf_state offsets against telemetry,
            # force overdrive and fourteen chained kills, then bomb the wave.
            observed = until(lambda value: value["enemies"] > 0)
            state_base = labels["_sf_state"]
            assert number("_sf_state", 4) == observed["tick"], ("sf_state.tick offset", observed)
            assert machine.read("main", state_base + 16, 1)[0] == observed["hull"], (
                "sf_state.hull offset", observed)
            machine.write("main", state_base + 28, bytes((14, 45)))  # chain, chain_clock
            machine.write("main", state_base + 34, bytes((240,)))    # overdrive
            key(" ")
            observed = until(lambda value: value["caption"] == 4)
            until(lambda value: phrase_observed(3), model_frames=600)
            trace.append({"event": "x8-chain-great-shot", **observed})

            key("R")
            observed = until(lambda value: value["mode"] == 1 and value["tick"] <= 6)
            assert observed["hull"] == initial_hull and observed["score"] == 0, observed
            trace.append({"event": "restart-during-play", **observed})

            # Observe a fresh unattended run. Rate calculations use each
            # model's own tick unit; TURBO fabric clocks and fixed CPU cycles
            # are never combined. A full-loop boundary avoids torn snapshots.
            first = sample()
            observations = [first]
            start_position = first["player"]
            capture("play-early")

            def idle(observed):
                # Resting paddles and no keys: any movement is a false reading.
                assert observed["player"] == start_position, (
                    "unattended ship moved", start_position, observed)
                if "joystick" in observed:
                    assert all(80 <= axis <= 175 for axis in observed["joystick"]), (
                        "centred joystick read outside its dead zone", observed)
            end_tick = first["tick"] + 240
            deadline = machine.get("ticks") + args.gameover_seconds * machine.clock_hz
            while True:
                observed = advance(6)
                observations.append(observed)
                idle(observed)
                if observed["mode"] == 1 and len(observations) % 4 == 0:
                    playfield()
                assert observed["mode"] in (1, 2), ("unexpected automatic pause", observed)
                assert not observed.get("lag", 0), ("game fell behind its clock", observed)
                if observed["tick"] >= end_tick or observed["mode"] == 2:
                    break
                assert machine.get("ticks") < deadline, ("timing window deadline", observed)
            last = observations[-1]
            elapsed = (last["model_ticks"] - first["model_ticks"]) / machine.clock_hz
            timing = {
                "model_seconds": elapsed,
                "simulation_steps": last["simulation_steps"] - first["simulation_steps"],
                "rendered_frames": last["rendered_frames"] - first["rendered_frames"],
                "simulation_hz": (last["simulation_steps"] - first["simulation_steps"]) / elapsed,
                "render_fps": (last["rendered_frames"] - first["rendered_frames"]) / elapsed,
                "target_simulation_hz": 30,
                "board_evidence": False,
            }
            (output / f"timing-{profile}.json").write_text(json.dumps({
                "profile": profile, "machine": machine.metadata(),
                "timing": timing, "observations": observations,
            }, indent=2) + "\n")
            capture("play-busy" if last["mode"] == 1 else "gameover")
            trace.append({"event": "unattended-timing-window", **last})

            while observed["mode"] != 2:
                assert machine.get("ticks") < deadline, (
                    profile, "unattended gameover deadline", observed)
                observed = advance(6)
                observations.append(observed)
                idle(observed)
                if observed["mode"] == 1 and len(observations) % 8 == 0:
                    playfield()
                assert observed["mode"] in (1, 2), observed
                assert not observed.get("lag", 0), observed
            assert observed["hull"] == 0 and observed["tick"] > 0, observed
            peak_enemies = max(value["enemies"] for value in observations)
            peak_bullets = max(value["bullets"] for value in observations)
            assert peak_enemies >= 2 and peak_bullets >= 2, ("busy scene absent", observations)
            if "enemy_types_seen" in observed:
                mask = observed["enemy_types_seen"]
                assert mask.bit_count() >= 3, ("fewer than three enemy types", observed)
            capture("gameover")
            trace.append({"event": "passive-run-reached-gameover", **observed})
            # Music tracks play on voices 0-7 of a Phasor and 0-1 of a
            # Mockingboard, each only its own track's notes; effects use the
            # voices after them.
            tracks = song_periods()
            music_voices = 8 if args.phasor else 2
            scale = 2 if args.phasor else 1
            for voice in range(music_voices):
                heard = voice_periods[voice]
                assert heard, (profile, "music voice silent", voice)
                valid = {period * scale for period in tracks[voice]}
                # A read between the two register writes of a period change
                # pairs the new low byte with the old high byte; nothing else
                # is accepted, and such reads stay rare.
                mixed = {low & 255 | high & 0xF00 for low in valid for high in valid}
                strange = {period: count for period, count in heard.items() if period not in valid}
                assert set(strange) <= mixed, (profile, "music voice played other periods", voice, strange)
                assert sum(strange.values()) * 50 <= sum(heard.values()) + 50, (
                    profile, "music voice often between period writes", voice, strange)
            effect_voices = [voice for voice in range(music_voices, 12 if args.phasor else 6)
                             if voice_periods[voice]]
            assert len(effect_voices) >= 3, (profile, "effects voices silent", effect_voices)
            trace.append({"event": "music-and-effect-voices", "music_voices": music_voices,
                          "effect_voices_heard": effect_voices,
                          "periods_heard": [len(heard) for heard in voice_periods]})
            # EXCELLENT comes from the passive run's repair pickup.
            assert {4, 5, 6} <= captions_seen, (
                "great-shot/excellent/game-over captions absent", sorted(captions_seen), observed)
            until(lambda value: phrase_observed(5), model_frames=600)
            assert all(phrase_observed(index) for index in (3, 4, 5)), (
                "actual SSI phrase writes absent",
                {index: phrase_observed(index) for index in (3, 4, 5)}, speech_events)
            trace.append({"event": "actual-ssi-great-shot-excellent-game-over",
                          "complete_phrase_register_streams": [3, 4, 5],
                          "captions_seen": sorted(captions_seen),
                          "ssi_writes": len(speech_events)})
            key(13)
            observed = until(lambda value: value["mode"] == 1 and value["tick"] <= 6)
            assert observed["hull"] == initial_hull and observed["score"] == 0, observed
            capture("retry")
            trace.append({"event": "gameover-enter-retry", **observed})

            # Observe actual MLI QUIT and Bitsy return, plus timer removal.
            machine.check(machine.lib.ap_input(machine.handle, b"key", ord("Q"), 0))
            for _ in range(30):
                returned = run(frames=6, timeout=30)
                assert returned["reason"] == "cycles", returned
            assert machine.get("newvideo") == 1, (profile, "SHR not restored", machine.state())
            post_exit_irqs = machine.get("irqs")
            for _ in range(5):
                run(frames=6, timeout=30)
            assert machine.get("irqs") == post_exit_irqs, "IRQ continues after shutdown"
            capture("return")
            with wave.open(str(output / f"audio-{profile}.wav"), "wb") as recording:
                recording.setnchannels(2)
                recording.setsampwidth(2)
                recording.setframerate(AUDIO_RATE)
                recording.writeframes(bytes(pcm_frames[:WAV_SECONDS * AUDIO_RATE * 4]))
            evidence["runs"].append({
                "profile": profile,
                "machine": machine.metadata(),
                "trace": trace,
                "timing": timing,
                "observations": observations,
                "screenshots": screens,
                "ssi_events": speech_events,
                "captions_seen": sorted(captions_seen),
                "minimum_sampled_hardware_sp": minimum_hardware_sp,
                "minimum_sampled_software_sp": minimum_software_sp,
                "peak_sampled_enemies": peak_enemies,
                "peak_sampled_bullets": peak_bullets,
                "playfield_checks": playfield_checks,
                "post_exit_irqs": post_exit_irqs,
                "returned": machine.state(),
            })
            print(f"STARFALL native {profile}: keyboard and joystick controls, autofire, pause, restart, "
                  f"passive gameover, retry and clean exit PASS; "
                  f"{timing['simulation_hz']:.2f} simulation Hz, {timing['render_fps']:.2f} rendered FPS "
                  f"(model only); peaks {peak_enemies} enemies/{peak_bullets} bullets; "
                  f"{playfield_checks} playfields matched their sprite lists", flush=True)
        except Exception as error:
            (output / f"failure-{profile}.json").write_text(json.dumps({
                "error": str(error), "trace": trace,
                "timing": timing, "observations": observations,
                "ssi_events": speech_events,
                "captions_seen": sorted(captions_seen),
                "observed": state(), "machine": machine.state(),
            }, indent=2) + "\n")
            (output / f"failure-main-{profile}.bin").write_bytes(machine.read("main", 0, 65536))
            (output / f"failure-aux0-{profile}.bin").write_bytes(machine.read("aux", 0, 65536))
            screenshot(machine, output / f"failure-{profile}.png")
            raise
        finally:
            machine.close()
    (output / "validation.json").write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
