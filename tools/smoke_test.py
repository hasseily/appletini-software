#!/usr/bin/env python3
"""Boot and exercise Appletini Invasion in a fresh GSSquared instance."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[3]
GAME_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = GAME_DIR / "appletini-invasion.gs2"
DEFAULT_EMULATOR = ROOT / "build/GSSquared.app/Contents/MacOS/GSSquared"
CLIENT_SRC = ROOT / "clients/python/src"
SDL_SCANCODE_F9 = 66
SDL_SCANCODE_SPACE = 44
MAILBOX_ADDRESS = 0x0300
MAILBOX_SIZE = 34
PARALLAX_HEIGHT = 316
MB_FAR_PHASE = 20
MB_MID_PHASE = 22
MB_NEAR_PHASE = 24
MB_MUSIC_STEP = 26
MB_MUSIC_LOOPS = 27
MB_MUSIC_TICK = 28
MB_AY_MIXER = 29
MB_EFFECT_KIND = 30
MB_LEAD_NOTE = 31
MB_BASS_NOTE = 32
MB_MUSIC_EVENTS = 33
PARALLAX_ANCHORS = ((4, 0), (5, 0), (30, 1), (43, 2))

sys.path.insert(0, str(CLIENT_SRC))

from gs2debug import (  # noqa: E402
    Client,
    MEM_MAIN_RAW,
    PLATFORM_APPLE_IIE_ENHANCED,
    ProtocolError,
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def frame_number(mailbox: bytes) -> int:
    return mailbox[6] | (mailbox[7] << 8)


def mailbox_word(mailbox: bytes, offset: int) -> int:
    return mailbox[offset] | (mailbox[offset + 1] << 8)


def parallax_phases(mailbox: bytes) -> tuple[int, int, int]:
    return (
        mailbox_word(mailbox, MB_FAR_PHASE),
        mailbox_word(mailbox, MB_MID_PHASE),
        mailbox_word(mailbox, MB_NEAR_PHASE),
    )


def hgr_address(y: int, page: int = 0x2000) -> int:
    return page + ((y & 7) << 10) + ((y & 0x38) << 4) + ((y >> 6) * 0x28)


def wait_for(predicate: Callable[[], object], timeout: float, description: str) -> object:
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(0.02)
    fail(f"timed out waiting for {description}; last value was {last!r}")


def connect_debug(client: Client, socket_path: Path, process: subprocess.Popen[bytes],
                  timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            fail(f"GSSquared exited before opening its debug socket (status {process.returncode})")
        try:
            client.connect(str(socket_path))
            client.hello()
            return
        except OSError as exc:
            last_error = exc
            client.close()
            time.sleep(0.05)
    fail(f"could not connect to {socket_path}: {last_error}")


def read_mailbox(client: Client) -> bytes:
    return client.read_mem(MEM_MAIN_RAW, MAILBOX_ADDRESS, MAILBOX_SIZE)


def matching_mailbox(client: Client, predicate: Callable[[bytes], bool]) -> bytes | None:
    mailbox = read_mailbox(client)
    return mailbox if predicate(mailbox) else None


def matching_memory(client: Client, address: int, wanted: bytes) -> bytes | None:
    value = client.read_mem(MEM_MAIN_RAW, address, len(wanted))
    return value if value == wanted else None


def capture_committed_dhgri(client: Client) -> tuple[bytes, dict[str, bytes]]:
    wanted_marker = bytes((0xC1, 0xB2, 0xCC, 0xE9, 0x01))
    for _ in range(30):
        captured: tuple[bytes, dict[str, bytes]] | None = None
        client.pause()
        try:
            if client.read_mem(MEM_MAIN_RAW, 0x4078, 5) == wanted_marker:
                mailbox = read_mailbox(client)
                planes = {
                    "main page 1": client.read_mem(MEM_MAIN_RAW, 0x02000, 0x2000),
                    "aux page 1": client.read_mem(MEM_MAIN_RAW, 0x12000, 0x2000),
                    "main page 2": client.read_mem(MEM_MAIN_RAW, 0x04000, 0x2000),
                    "aux page 2": client.read_mem(MEM_MAIN_RAW, 0x14000, 0x2000),
                }
                if client.read_mem(MEM_MAIN_RAW, 0x4078, 5) == wanted_marker:
                    captured = mailbox, planes
        finally:
            client.continue_()
        if captured is not None:
            return captured
        time.sleep(0.02)
    fail("could not pause on a committed A2Li DHGRi frame")


def star_geometry(index: int) -> tuple[int, int, int]:
    half_x = (index * 37 + 13) % 80
    if index < 24:
        mask = 1 << ((index * 5 + 1) % 7)
        span = 1
    elif index < 40:
        mask = 3 << ((index * 5 + 2) % 6)
        span = 1
    else:
        mask = 7 << ((index * 3 + 1) % 5)
        span = 1
    return half_x, mask, span


def star_head(index: int, phase: int) -> int:
    seed = 2 * ((index * 83 + 29) % (PARALLAX_HEIGHT // 2))
    seed += (index ^ (index >> 1)) & 1
    return (seed + phase) % PARALLAX_HEIGHT


def assert_anchor(planes: dict[str, bytes], index: int, phase: int) -> None:
    half_x, mask, span = star_geometry(index)
    woven_y = star_head(index, phase)
    for _ in range(span):
        page_number = 1 if (woven_y & 1) == 0 else 2
        page = 0x2000 if page_number == 1 else 0x4000
        plane = "aux" if (half_x & 1) == 0 else "main"
        offset = hgr_address(20 + (woven_y >> 1), page) - page + (half_x >> 1)
        value = planes[f"{plane} page {page_number}"][offset]
        if value & mask != mask:
            fail(
                f"parallax anchor {index} missing at woven row {woven_y}: "
                f"{plane} page {page_number} byte=${value:02X} mask=${mask:02X}"
            )
        woven_y = (woven_y - 1) % PARALLAX_HEIGHT


def assert_old_anchor_erased(planes: dict[str, bytes], index: int, old_phase: int) -> None:
    half_x, mask, _ = star_geometry(index)
    woven_y = star_head(index, old_phase)
    page_number = 1 if (woven_y & 1) == 0 else 2
    page = 0x2000 if page_number == 1 else 0x4000
    plane = "aux" if (half_x & 1) == 0 else "main"
    offset = hgr_address(20 + (woven_y >> 1), page) - page + (half_x >> 1)
    value = planes[f"{plane} page {page_number}"][offset]
    if value & mask:
        fail(f"parallax anchor {index} left pixels behind at woven row {woven_y}")


def exercise(client: Client, timeout: float) -> dict[str, object]:
    status = client.get_status()
    if status.platform_id != PLATFORM_APPLE_IIE_ENHANCED:
        fail(f"wrong platform {status.platform_id}; expected enhanced Apple //e")

    # Every fresh enhanced //e starts at 1.024 MHz. Three F9 releases select
    # 2.8, 7.159, then 14.3 MHz while boot and game I/O remain synchronized.
    for _ in range(3):
        client.tap_key(SDL_SCANCODE_F9, hold_s=0.02)

    mailbox = wait_for(
        lambda: matching_mailbox(client, lambda m: m[:4] == b"A13I"),
        timeout,
        "the A13I mailbox after SmartPort boot",
    )
    assert isinstance(mailbox, bytes)

    expected = {
        "video mode": (mailbox[4], 1),
        "RamWorks banks": (mailbox[5], 128),
        "reported speed": (mailbox[12], 14),
        "audio feature flags": (mailbox[13], 7),
        "game state": (mailbox[15], 1),
    }
    for label, (actual, wanted) in expected.items():
        if actual != wanted:
            fail(f"{label} is {actual}, expected {wanted}; mailbox={mailbox.hex()}")

    first_visual_box, first_planes = capture_committed_dhgri(client)
    first_phases = parallax_phases(first_visual_box)
    for index, layer in PARALLAX_ANCHORS:
        assert_anchor(first_planes, index, first_phases[layer])

    speech_values: set[int] = set()
    speech_completions = 0
    music_steps: set[int] = {mailbox[MB_MUSIC_STEP]}
    lead_notes: set[int] = {mailbox[MB_LEAD_NOTE]}
    bass_notes: set[int] = {mailbox[MB_BASS_NOTE]}
    mixer_values: set[int] = {mailbox[MB_AY_MIXER]}
    first_music_loop = mailbox[MB_MUSIC_LOOPS]
    speech_deadline = time.monotonic() + 0.8
    while time.monotonic() < speech_deadline:
        speech_box = read_mailbox(client)
        speech_values.add(speech_box[14])
        speech_completions = max(speech_completions, speech_box[18])
        music_steps.add(speech_box[MB_MUSIC_STEP])
        lead_notes.add(speech_box[MB_LEAD_NOTE])
        bass_notes.add(speech_box[MB_BASS_NOTE])
        mixer_values.add(speech_box[MB_AY_MIXER])
        time.sleep(0.02)
    if not any(value not in (0x00, 0xFF) for value in speech_values):
        fail(f"SSI-263 speech scheduler did not publish a phoneme: {speech_values}")
    if speech_completions == 0:
        fail("SSI-263 did not deliver a VIA CA1 phoneme-completion event")
    if len(music_steps) < 2 or len(lead_notes) < 2:
        fail(
            "continuous AY score did not advance while speech played: "
            f"steps={music_steps} lead={lead_notes} bass={bass_notes}"
        )
    if any(value == 0x3F or value & 0x03 for value in mixer_values):
        fail(f"music channels A/B were disabled during speech: mixers={mixer_values}")

    wait_for(
        lambda: matching_mailbox(
            client,
            lambda m: ((mailbox_word(m, MB_FAR_PHASE) - first_phases[0])
                       % PARALLAX_HEIGHT) >= 8,
        ),
        2.0,
        "eight committed far-layer parallax steps",
    )
    second_visual_box, second_planes = capture_committed_dhgri(client)
    second_phases = parallax_phases(second_visual_box)
    phase_deltas = tuple(
        (new - old) % PARALLAX_HEIGHT
        for old, new in zip(first_phases, second_phases)
    )
    if not phase_deltas[0] or phase_deltas[1] != (phase_deltas[0] * 2) % PARALLAX_HEIGHT \
            or phase_deltas[2] != (phase_deltas[0] * 4) % PARALLAX_HEIGHT:
        fail(f"parallax layers did not retain 1:2:4 motion: {phase_deltas}")
    for index, layer in PARALLAX_ANCHORS:
        assert_old_anchor_erased(second_planes, index, first_phases[layer])
        assert_anchor(second_planes, index, second_phases[layer])

    music_loop_box: bytes | None = None
    music_deadline = time.monotonic() + 8.0
    while time.monotonic() < music_deadline:
        music_box = read_mailbox(client)
        music_steps.add(music_box[MB_MUSIC_STEP])
        lead_notes.add(music_box[MB_LEAD_NOTE])
        bass_notes.add(music_box[MB_BASS_NOTE])
        mixer_values.add(music_box[MB_AY_MIXER])
        if music_box[MB_MUSIC_LOOPS] != first_music_loop \
                and len(music_steps) >= 8 and len(bass_notes) >= 4:
            music_loop_box = music_box
            break
        time.sleep(0.02)
    if music_loop_box is None:
        fail(
            "continuous score did not complete a varied loop: "
            f"steps={music_steps} lead={lead_notes} bass={bass_notes}"
        )
    if any(value == 0x3F or value & 0x03 for value in mixer_values):
        fail(f"music channels A/B were disabled during the loop: mixers={mixer_values}")

    # Make reset observable: perturb player state first, then require R to put
    # it back. The other public values already match a fresh game at boot.
    client.type_text("d", delay_s=0, hold_s=0.04)
    wait_for(
        lambda: matching_mailbox(client, lambda m: m[11] > 20),
        2.0,
        "pre-reset player movement",
    )
    client.type_text("r", delay_s=0, hold_s=0.04)
    reset_box = wait_for(
        lambda: matching_mailbox(
            client,
            lambda m: m[8] == 0 and m[9] == 3 and m[10] == 24 and m[11] == 20,
        ),
        2.0,
        "game reset",
    )
    assert isinstance(reset_box, bytes)

    start_frame = frame_number(reset_box)
    client.type_text("d", delay_s=0, hold_s=0.04)
    moved_box = wait_for(
        lambda: matching_mailbox(client, lambda m: m[11] > 20),
        2.0,
        "lowercase movement input",
    )
    assert isinstance(moved_box, bytes)
    client.type_text("s", delay_s=0, hold_s=0.04)

    # A zero-hold tap may be released before the guest's next 30 Hz game tick;
    # it still must queue one shot from the keyboard strobe.
    client.tap_key(SDL_SCANCODE_SPACE, hold_s=0)
    tap_box = wait_for(
        lambda: matching_mailbox(client, lambda m: m[16] >= 1 and m[19] >= 1),
        1.0,
        "one queued bullet from a quick Space tap",
    )
    assert isinstance(tap_box, bytes)

    # One KEYEVENT down with no host repeat events must sustain autofire via
    # the Apple //e AKD level until the corresponding key-up.
    music_events_before_hold = tap_box[MB_MUSIC_EVENTS]
    client.key_down(SDL_SCANCODE_SPACE)
    try:
        held_music_box = wait_for(
            lambda: matching_mailbox(
                client,
                lambda m: m[MB_EFFECT_KIND] == 1
                          and ((m[MB_MUSIC_EVENTS] - music_events_before_hold) & 0xFF) >= 1
                          and (m[MB_AY_MIXER] & 0x03) == 0,
            ),
            1.5,
            "music advancement during held-fire effects",
        )
        assert isinstance(held_music_box, bytes)
        bullet_box = wait_for(
            lambda: matching_mailbox(client, lambda m: m[16] >= 3 and m[19] >= 3),
            2.0,
            "three simultaneous bullets from held-space autofire",
        )
    finally:
        client.key_up(SDL_SCANCODE_SPACE)
    assert isinstance(bullet_box, bytes)
    time.sleep(0.35)
    released_box = read_mailbox(client)
    if released_box[19] != bullet_box[19]:
        fail(f"held-space autofire continued after key-up: "
             f"{bullet_box[19]} -> {released_box[19]} shots")
    if released_box[MB_AY_MIXER] == 0x3F or released_box[MB_AY_MIXER] & 0x03:
        fail(f"music did not survive effect release: mixer=${released_box[MB_AY_MIXER]:02X}")

    replay_at_start = bullet_box[17]
    replay_box = wait_for(
        lambda: matching_mailbox(client, lambda m: m[17] != replay_at_start),
        2.0,
        "RamWorks replay-bank rotation",
    )
    assert isinstance(replay_box, bytes)
    if frame_number(replay_box) == start_frame:
        fail("game frame counter did not advance")

    wanted_marker = bytes((0xC1, 0xB2, 0xCC, 0xE9, 0x01))
    marker = wait_for(
        lambda: matching_memory(client, 0x4078, wanted_marker),
        1.0,
        "a committed A2Li DHGRi frame",
    )
    assert isinstance(marker, bytes)

    final_visual_box, planes = capture_committed_dhgri(client)
    # Video-7 MIX selector bits are metadata, not pixels. Count only the low
    # seven DHGR data bits so a selector-only background cannot satisfy the
    # plane-density check.
    nonzero = {
        name: sum((value & 0x7F) != 0 for value in data)
        for name, data in planes.items()
    }
    sparse = {name: count for name, count in nonzero.items() if count < 100}
    if sparse:
        fail(f"DHGRi plane data is unexpectedly sparse: {sparse}")
    if planes["main page 1"] == planes["main page 2"]:
        fail("DHGRi main fields are identical")
    if planes["aux page 1"] == planes["aux page 2"]:
        fail("DHGRi auxiliary fields are identical")
    field_differences = {
        "main": sum(a != b for a, b in zip(planes["main page 1"], planes["main page 2"])),
        "aux": sum(a != b for a, b in zip(planes["aux page 1"], planes["aux page 2"])),
    }
    if min(field_differences.values()) < 20:
        fail(f"DHGRi fields do not carry enough distinct detail: {field_differences}")

    # Video-7 state 10 interprets bit 7 of the interleaved AUX/MAIN stream as
    # an 8+8+8+4-dot monochrome/color selector. Every byte in the gameplay
    # rows is color-selected, on both pages and in both planes, so moving art
    # cannot expose a monochrome seam at an odd-byte boundary.
    for name, data in planes.items():
        for y in range(20, 180):
            offset = hgr_address(y, 0x2000 if "page 1" in name else 0x4000)
            offset -= 0x2000 if "page 1" in name else 0x4000
            row = data[offset:offset + 40]
            if len(row) != 40 or any((value & 0x80) == 0 for value in row):
                fail(f"{name} row {y} does not fully select Video-7 color")

    # The static border deliberately overwrites every byte, so its exact
    # values also prove that non-text writes preserve the selector bit.
    for page, suffix in ((0x2000, "page 1"), (0x4000, "page 2")):
        offset = hgr_address(178, page) - page
        if planes[f"aux {suffix}"][offset:offset + 40] != bytes((0xD5,)) * 40:
            fail(f"aux {suffix} color border is damaged")
        if planes[f"main {suffix}"][offset:offset + 40] != bytes((0xAA,)) * 40:
            fail(f"main {suffix} color border is damaged")

    # HUD, title, and footer occupy dedicated rows. Keeping all four planes'
    # selector bits clear makes their glyphs monochrome white without turning
    # the colored playfield monochrome.
    text_rows = (*range(2, 9), *range(10, 17), *range(181, 188))
    for name, data in planes.items():
        page = 0x2000 if "page 1" in name else 0x4000
        for y in text_rows:
            offset = hgr_address(y, page) - page
            row = data[offset:offset + 40]
            if any(value & 0x80 for value in row):
                fail(f"{name} text row {y} incorrectly selects Video-7 color")

    # The font table is stored conventionally with bit 4 at the left, but an
    # Apple II graphics byte displays bit 0 at the left. SCORE's asymmetric S
    # is a compact regression check that the game reverses those five bits.
    expected_s = bytes((0x1E, 0x01, 0x01, 0x0E, 0x10, 0x10, 0x0F))
    for page in (0x2000, 0x4000):
        actual_s = bytes(
            client.read_mem(MEM_MAIN_RAW, hgr_address(2 + row, page), 1)[0]
            for row in range(7)
        )
        if actual_s != expected_s:
            fail(f"page ${page:04X} SCORE glyph is mirrored or damaged: {actual_s.hex()}")

    final_box = read_mailbox(client)
    return {
        "platform": status.platform_id,
        "mailbox": final_box.hex(),
        "frames": (start_frame, frame_number(final_box)),
        "player_x": moved_box[11],
        "player_bullets": bullet_box[16],
        "shots_fired": bullet_box[19],
        "speech": sorted(speech_values),
        "speech_completions": speech_completions,
        "parallax_phases": parallax_phases(final_visual_box),
        "parallax_deltas": phase_deltas,
        "music_steps": sorted(music_steps),
        "music_loop": music_loop_box[MB_MUSIC_LOOPS],
        "mixer_values": sorted(mixer_values),
        "replay_banks": (replay_at_start, replay_box[17]),
        "nonzero": nonzero,
        "field_differences": field_differences,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--disk", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--emulator", type=Path, default=DEFAULT_EMULATOR)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--keep-log", action="store_true")
    args = parser.parse_args()

    disk = args.disk.resolve()
    config = args.config.resolve()
    emulator = args.emulator.resolve()
    for path, description in ((disk, "SmartPort disk"), (config, "system config"),
                              (emulator, "GSSquared executable")):
        if not path.is_file():
            fail(f"missing {description}: {path}")
    if disk.stat().st_size < 800 * 1024 or disk.stat().st_size % 512:
        fail(f"SmartPort image has invalid size: {disk.stat().st_size}")

    config_text = config.read_text()
    if 'card = "diskII"' in config_text or 'card = "diskii"' in config_text:
        fail("showcase config must not contain a Disk II controller")
    if 'slot = 7\ncard = "appletini"' not in config_text:
        fail("showcase config must put Appletini in slot 7")
    if 'slot = 4\ncard = "mockingboard"' not in config_text:
        fail("showcase config must put Mockingboard in slot 4")

    socket_path = Path(tempfile.gettempdir()) / f"gs2-appletini-invasion-{os.getpid()}.sock"
    log_file = tempfile.NamedTemporaryFile(
        prefix="gs2-appletini-invasion-", suffix=".log", delete=False,
    )
    log_path = Path(log_file.name)
    process: subprocess.Popen[bytes] | None = None
    client = Client()
    passed = False
    exit_error: str | None = None
    try:
        process = subprocess.Popen(
            (
                str(emulator), str(config), f"-ds7d1={disk}",
                "--debug", str(socket_path), "--no-quit-confirm",
            ),
            cwd=ROOT,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        connect_debug(client, socket_path, process, args.timeout)
        result = exercise(client, args.timeout)
        print("PASS Appletini Invasion")
        print(f"  platform={result['platform']} mailbox={result['mailbox']}")
        print(f"  frames={result['frames']} player_x={result['player_x']} "
              f"simultaneous_bullets={result['player_bullets']} "
              f"shots_fired={result['shots_fired']}")
        print(f"  speech={result['speech']} completions={result['speech_completions']} "
              f"replay_banks={result['replay_banks']}")
        print(f"  parallax phases={result['parallax_phases']} "
              f"sample deltas={result['parallax_deltas']}")
        print(f"  music steps={result['music_steps']} loop={result['music_loop']} "
              f"mixers={result['mixer_values']}")
        print(f"  DHGRi nonzero bytes={result['nonzero']}")
        print(f"  DHGRi field differences={result['field_differences']}")
        passed = True
    finally:
        try:
            client.quit()
        except (OSError, RuntimeError, ProtocolError):
            pass
        client.close()
        if process is not None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            if passed and process.returncode != 0:
                passed = False
                exit_error = f"GSSquared exited with status {process.returncode}"
        log_file.close()
        if socket_path.exists():
            socket_path.unlink()
        if passed and not args.keep_log:
            log_path.unlink(missing_ok=True)
        else:
            print(f"GSSquared log: {log_path}", file=sys.stderr)
    if exit_error is not None:
        fail(exit_error)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
