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
MAILBOX_ADDRESS = 0x0300
MAILBOX_SIZE = 19

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
        "audio feature flags": (mailbox[13], 3),
        "game state": (mailbox[15], 1),
    }
    for label, (actual, wanted) in expected.items():
        if actual != wanted:
            fail(f"{label} is {actual}, expected {wanted}; mailbox={mailbox.hex()}")

    speech_values: set[int] = set()
    speech_completions = 0
    speech_deadline = time.monotonic() + 0.8
    while time.monotonic() < speech_deadline:
        speech_box = read_mailbox(client)
        speech_values.add(speech_box[14])
        speech_completions = max(speech_completions, speech_box[18])
        time.sleep(0.02)
    if not any(value not in (0x00, 0xFF) for value in speech_values):
        fail(f"SSI-263 speech scheduler did not publish a phoneme: {speech_values}")
    if speech_completions == 0:
        fail("SSI-263 did not deliver a VIA CA1 phoneme-completion event")

    # Reset to a deterministic formation before exercising lowercase controls.
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

    client.type_text(" ", delay_s=0, hold_s=0.04)
    bullet_box = wait_for(
        lambda: matching_mailbox(client, lambda m: bool(m[16])),
        2.0,
        "player fire input",
    )
    assert isinstance(bullet_box, bytes)

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

    planes = {
        "main page 1": client.read_mem(MEM_MAIN_RAW, 0x02000, 0x2000),
        "aux page 1": client.read_mem(MEM_MAIN_RAW, 0x12000, 0x2000),
        "main page 2": client.read_mem(MEM_MAIN_RAW, 0x04000, 0x2000),
        "aux page 2": client.read_mem(MEM_MAIN_RAW, 0x14000, 0x2000),
    }
    nonzero = {name: sum(value != 0 for value in data) for name, data in planes.items()}
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
        "speech": sorted(speech_values),
        "speech_completions": speech_completions,
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
        print(f"  frames={result['frames']} player_x={result['player_x']}")
        print(f"  speech={result['speech']} completions={result['speech_completions']} "
              f"replay_banks={result['replay_banks']}")
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
