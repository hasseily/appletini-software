#!/usr/bin/env python3
"""Boot Appletini Bosconian in GSSquared and check that it runs.

Steps (each prints the debug mailbox at $0300):
  1. boot dist/Appletini-Bosconian.hdv from the Appletini SmartPort (slot 7)
     and wait for the mailbox magic 'A13B'
  2. the frame counter advances
  3. frames per emulated second from the CPU cycle counter (33.3 MHz):
     40..70 fps
  4. state is ST_TITLE; the title screen is dumped to build/smoke_title.png;
     both joystick axes calibrated (mailbox byte 39 = 3: GSSquared reports a
     centered stick when no game controller is attached)
  5. Return -> ST_PLAY within 2 s
  6. Space held for 1 s produces display-list or score activity
  7. 'l' changes the heading
  8. 5 s of play: frame_writes and max_frame_writes stay <= 10000;
     the play screen is dumped to build/smoke_play.png
  9. quit the emulator through the debug protocol

Needs GSSquared from the codex/appletini-108-postprocessing branch:
$GSSQUARED_ROOT/build/GSSquared (default ../../../gssquared) and its
python client at $GSSQUARED_ROOT/clients/python/src. On Linux without a
DISPLAY the emulator runs under xvfb-run -a; SDL audio uses the dummy
driver. Exit status is non-zero on any failure, with the emulator log tail.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

SOFTWARE_ROOT = Path(__file__).resolve().parents[3]
GAME_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = GAME_DIR / "tools"
DEFAULT_GSSQUARED_ROOT = SOFTWARE_ROOT.parent / "gssquared"
GSSQUARED_ROOT = Path(
    os.environ.get("GSSQUARED_ROOT", str(DEFAULT_GSSQUARED_ROOT))
).expanduser().resolve()
DEFAULT_EMULATOR = GSSQUARED_ROOT / "build/GSSquared"
CLIENT_SRC = GSSQUARED_ROOT / "clients/python/src"
DEFAULT_CONFIG = GAME_DIR / "appletini-bosconian.gs2"
BUILD_DIR = GAME_DIR / "build"

sys.path.insert(0, str(TOOLS_DIR))
import shr2png  # noqa: E402
import build_disk  # noqa: E402

MAILBOX_ADDRESS = 0x0300
MAILBOX_SIZE = 41
MAILBOX_MAGIC = b"A13B"
AUX_RAW_BASE = 0x10000          # MEM_MAIN_RAW: aux bank follows main
SHR_RAW = AUX_RAW_BASE + 0x2000
SHR_SIZE = 0x8000
CPU_HZ = 33_333_333             # vTW 33 MHz preset
WRITE_BUDGET = 10_000

SCANCODE_RETURN = 40
SCANCODE_SPACE = 44
SCANCODE_J = 13
SCANCODE_L = 15

ST_NAMES = {0: "BOOT", 1: "TITLE", 2: "PLAY", 3: "DYING", 4: "GAME_OVER",
            5: "ROUND_CLEAR", 6: "PAUSED"}
ST_TITLE, ST_PLAY, ST_DYING, ST_GAME_OVER, ST_ROUND_CLEAR, ST_PAUSED = 1, 2, 3, 4, 5, 6


class SmokeError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise SmokeError(message)


# ---------------------------------------------------------------------------
# mailbox helpers
# ---------------------------------------------------------------------------
def word(m: bytes, o: int) -> int:
    return m[o] | (m[o + 1] << 8)


def frame_number(m: bytes) -> int:
    return word(m, 5)


def describe(m: bytes) -> str:
    return (f"magic={m[:4]!r} state={ST_NAMES.get(m[4], m[4])} frame={frame_number(m)} "
            f"score={int.from_bytes(m[7:11], 'little')} round={m[11]} lives={m[12]} "
            f"cond={m[13]} pos=({word(m, 14)},{word(m, 16)}) heading={m[18]} "
            f"bases={m[19]} enemies={m[20]} dl={m[21]} writes={word(m, 22)} "
            f"max_writes={word(m, 24)} rw_banks={m[26]} probe={word(m, 27)} "
            f"sfx={m[29]} music={m[30]} speech={m[31]:#04x} input={m[32]:#04x} "
            f"formation={m[33]} spy={m[34]} event={m[35]} dropped={word(m, 36)} "
            f"stars={m[38]} joy={m[39]}")


def wait_for(predicate: Callable[[], object], timeout: float, what: str) -> object:
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(0.02)
    fail(f"timed out after {timeout:.0f}s waiting for {what}; last={last!r}")
    return None


# ---------------------------------------------------------------------------
class Session:
    def __init__(self, client, gs2):
        self.c = client
        self.gs2 = gs2

    def mailbox(self) -> bytes:
        return self.c.read_mem(self.gs2.MEM_MAIN, MAILBOX_ADDRESS, MAILBOX_SIZE)

    def mailbox_when(self, predicate: Callable[[bytes], bool]) -> bytes | None:
        m = self.mailbox()
        return m if predicate(m) else None

    def cycles(self) -> int:
        return int.from_bytes(self.c.get_regs()[:8], "little")

    def dump_shr(self, png: Path) -> bytes:
        data = self.c.read_mem(self.gs2.MEM_MAIN_RAW, SHR_RAW, SHR_SIZE)
        png.parent.mkdir(parents=True, exist_ok=True)
        shr2png.convert(data, png, scale=2)
        return data

    def step(self, label: str, m: bytes | None = None) -> bytes:
        if m is None:
            m = self.mailbox()
        print(f"[{label}] {describe(m)}")
        return m


def exercise(s: Session, timeout: float, play_seconds: float) -> dict:
    gs2 = s.gs2
    c = s.c

    # 1. wait for the mailbox (boot through ProDOS on the SmartPort)
    def magic_present():
        try:
            m = s.mailbox()
        except gs2.ProtocolError as error:
            if error.code == 6:          # main thread not ready yet
                return None
            raise
        return m if m[:4] == MAILBOX_MAGIC else None

    m = wait_for(magic_present, timeout, "the A13B mailbox after boot")
    s.step("boot", m)

    # 2. frame counter advances
    first = frame_number(m)
    m = wait_for(lambda: s.mailbox_when(lambda x: frame_number(x) != first),
                 3.0, "the frame counter to advance")
    s.step("frames advance", m)

    # 3. cadence from the emulated cycle counter
    m0 = s.mailbox()
    cyc0 = s.cycles()
    t0 = time.monotonic()
    # (wall-clock limit only: a slow host emulates the 33 MHz machine at a
    # third of its speed and needs about 7 s for these 2 s of game time)
    m1 = wait_for(lambda: s.mailbox_when(
        lambda x: ((frame_number(x) - frame_number(m0)) & 0xFFFF) >= 120),
        20.0, "120 frames")
    cyc1 = s.cycles()
    elapsed = time.monotonic() - t0
    frames = (frame_number(m1) - frame_number(m0)) & 0xFFFF
    cycles_per_frame = (cyc1 - cyc0) / frames
    emulated_fps = CPU_HZ / cycles_per_frame
    wall_fps = frames / elapsed
    print(f"[cadence] {frames} frames, {cycles_per_frame:.0f} cycles/frame, "
          f"{emulated_fps:.1f} fps emulated, {wall_fps:.1f} fps wall clock")
    s.step("cadence", m1)
    if not 40.0 <= emulated_fps <= 70.0:
        fail(f"emulated frame rate {emulated_fps:.1f} fps is outside 40..70 "
             f"({cycles_per_frame:.0f} cycles per frame at 33.3 MHz)")

    # 4. title state and screenshot
    m = wait_for(lambda: s.mailbox_when(lambda x: x[4] == ST_TITLE), 5.0, "ST_TITLE")
    s.step("title", m)
    title_png = BUILD_DIR / "smoke_title.png"
    title_dump = s.dump_shr(title_png)
    title_nonzero = sum(1 for b in title_dump[:32000] if b)
    print(f"[title] wrote {title_png} ({title_nonzero} non-zero framebuffer bytes)")
    if title_nonzero < 200:
        fail("title framebuffer is blank")
    if m[39] != 3:
        fail(f"joystick calibration failed at the title: joy_status={m[39]:#04x} "
             "(expected 3: both axes usable with a centered stick)")

    # 5. Return starts a game
    c.tap_key(SCANCODE_RETURN, hold_s=0.05)
    m = wait_for(lambda: s.mailbox_when(lambda x: x[4] == ST_PLAY), 2.0,
                 "ST_PLAY after Return")
    s.step("play", m)
    score_before = int.from_bytes(m[7:11], "little")

    # 6. hold Space for one second
    dl_values: set[int] = set()
    input_masks: set[int] = set()
    c.key_down(SCANCODE_SPACE)
    try:
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            x = s.mailbox()
            dl_values.add(x[21])
            input_masks.add(x[32])
            time.sleep(0.02)
    finally:
        c.key_up(SCANCODE_SPACE)
    m = s.step("after fire", s.mailbox())
    score_after = int.from_bytes(m[7:11], "little")
    fire_seen = any(mask & 0x10 for mask in input_masks)
    print(f"[fire] dl_count values={sorted(dl_values)} score {score_before}->{score_after} "
          f"input masks={sorted(hex(v) for v in input_masks)}")
    if not (fire_seen or len(dl_values) >= 2 or score_after > score_before):
        fail("holding Space produced no fire input, no display-list change and no score")

    # 7. heading key
    heading_before = m[18]
    key, wanted = (SCANCODE_L, 2) if heading_before != 2 else (SCANCODE_J, 6)
    c.tap_key(key, hold_s=0.05)
    m = wait_for(lambda: s.mailbox_when(lambda x: x[18] == wanted), 2.0,
                 f"heading {wanted} after the direction key")
    s.step("heading", m)
    print(f"[heading] {heading_before} -> {m[18]}")

    # 8. play for a while and watch the write budget
    writes_seen = 0
    max_seen = 0
    states: set[int] = set()
    start_frame = frame_number(m)
    end = time.monotonic() + play_seconds
    while time.monotonic() < end:
        x = s.mailbox()
        states.add(x[4])
        writes_seen = max(writes_seen, word(x, 22))
        max_seen = max(max_seen, word(x, 24))
        if word(x, 22) > WRITE_BUDGET or word(x, 24) > WRITE_BUDGET:
            s.step("budget", x)
            fail(f"AUX write budget exceeded: frame_writes={word(x, 22)} "
                 f"max_frame_writes={word(x, 24)} (limit {WRITE_BUDGET})")
        time.sleep(0.05)
    m = s.step("after play", s.mailbox())
    play_png = BUILD_DIR / "smoke_play.png"
    play_dump = s.dump_shr(play_png)
    play_nonzero = sum(1 for b in play_dump[:32000] if b)
    played_frames = (frame_number(m) - start_frame) & 0xFFFF
    print(f"[play] {played_frames} frames in {play_seconds:.0f}s wall clock, "
          f"largest frame_writes={writes_seen} max_frame_writes={max_seen} "
          f"states={sorted(ST_NAMES.get(v, v) for v in states)} "
          f"dropped={word(m, 36)}")
    print(f"[play] wrote {play_png} ({play_nonzero} non-zero framebuffer bytes)")
    # The wall clock depends on the host (a slow host or xvfb runs the
    # emulator below real time); the emulated rate was checked above.
    if played_frames < play_seconds * 10:
        fail(f"only {played_frames} frames in {play_seconds:.0f}s of play")
    if not states & {ST_PLAY, ST_DYING, ST_ROUND_CLEAR, ST_GAME_OVER}:
        fail(f"unexpected states during play: {states}")
    if play_nonzero < 200:
        fail("play framebuffer is blank")

    return {
        "cycles_per_frame": cycles_per_frame,
        "emulated_fps": emulated_fps,
        "wall_fps": wall_fps,
        "max_frame_writes": max_seen,
        "largest_frame_writes": writes_seen,
        "final": describe(m),
    }


# ---------------------------------------------------------------------------
def check_disk(disk: Path) -> None:
    image = build_disk.Image(disk.read_bytes(), dos_order=False)
    _, entries, _ = build_disk.list_volume(image)
    names = {e["name"]: e for e in entries}
    if "PRODOS" not in names or names["PRODOS"]["file_type"] != 0xFF:
        fail(f"disk has no PRODOS SYS file: {sorted(names)}")
    system = names.get("BOSCO.SYSTEM")
    if system is None or system["file_type"] != 0xFF or system["aux"] != 0x2000:
        fail(f"BOSCO.SYSTEM is not a $2000 SYS file: {system}")
    if disk.stat().st_size != 800 * 1024:
        fail(f"disk image is {disk.stat().st_size} bytes, not 800 KB")


def connect(client, gs2, socket_path: Path, process: subprocess.Popen, timeout: float):
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            fail(f"GSSquared exited before opening its debug socket (status {process.returncode})")
        if socket_path.exists():
            try:
                client.connect(str(socket_path))
                client.hello()
                return
            except (OSError, ConnectionError, gs2.ProtocolError) as error:
                last_error = error
                client.close()
        time.sleep(0.1)
    fail(f"could not connect to {socket_path}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--disk", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--emulator", type=Path, default=DEFAULT_EMULATOR)
    parser.add_argument("--timeout", type=float, default=60.0,
                        help="seconds to wait for the mailbox after launch")
    parser.add_argument("--play-seconds", type=float, default=5.0)
    parser.add_argument("--keep-log", action="store_true")
    args = parser.parse_args()

    disk = args.disk.resolve()
    config = args.config.resolve()
    emulator = args.emulator.resolve()
    for path, what in ((disk, "SmartPort disk image"), (config, "GSSquared config"),
                       (emulator, "GSSquared executable")):
        if not path.is_file():
            fail(f"missing {what}: {path}")
    if not CLIENT_SRC.is_dir():
        fail(f"gs2debug python client not found at {CLIENT_SRC} (set GSSQUARED_ROOT)")
    sys.path.insert(0, str(CLIENT_SRC))
    import gs2debug as gs2  # noqa: E402

    check_disk(disk)
    config_text = config.read_text()
    if 'card = "appletini"' not in config_text or 'card = "mockingboard"' not in config_text:
        fail("config must have the Appletini card in slot 7 and a Mockingboard in slot 4")

    command = [str(emulator), str(config), f"-ds7d1={disk}",
               "--debug", None, "--no-quit-confirm"]
    if not os.environ.get("DISPLAY") and sys.platform.startswith("linux"):
        if shutil.which("xvfb-run") is None:
            fail("no DISPLAY and xvfb-run is not installed")
        command = ["xvfb-run", "-a"] + command
    env = os.environ.copy()
    env.setdefault("SDL_AUDIODRIVER", "dummy")

    socket_path = Path(tempfile.gettempdir()) / f"gs2-bosco-{os.getpid()}.sock"
    command[command.index(None)] = str(socket_path)
    log_file = tempfile.NamedTemporaryFile(prefix="gs2-bosco-", suffix=".log", delete=False)
    log_path = Path(log_file.name)
    process: subprocess.Popen | None = None
    client = gs2.Client()
    passed = False
    try:
        print("launch:", " ".join(command))
        process = subprocess.Popen(command, cwd=GSSQUARED_ROOT, env=env,
                                   stdout=log_file, stderr=subprocess.STDOUT)
        connect(client, gs2, socket_path, process, args.timeout)
        result = exercise(Session(client, gs2), args.timeout, args.play_seconds)
        print("PASS Appletini Bosconian")
        print(f"  {result['cycles_per_frame']:.0f} cycles/frame, "
              f"{result['emulated_fps']:.1f} fps emulated, {result['wall_fps']:.1f} fps wall")
        print(f"  largest frame_writes={result['largest_frame_writes']} "
              f"max_frame_writes={result['max_frame_writes']} (budget {WRITE_BUDGET})")
        print(f"  final: {result['final']}")
        passed = True
    finally:
        try:
            client.quit()
        except Exception:      # noqa: BLE001 - best effort shutdown
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
        log_file.close()
        if socket_path.exists():
            socket_path.unlink()
        if not passed:
            print("---- GSSquared log tail ----", file=sys.stderr)
            print(log_path.read_text(errors="replace")[-6000:], file=sys.stderr)
        if passed and not args.keep_log:
            log_path.unlink(missing_ok=True)
        else:
            print(f"GSSquared log: {log_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SmokeError, OSError, RuntimeError, subprocess.SubprocessError,
            build_disk.DiskError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
