#!/usr/bin/env python3
"""Exercise the ProDOS demo through a fresh GSSquared debug-protocol session.

Examples::

    python tools/test_emulator.py --platform 2
    python tools/test_emulator.py --platform all --disk Mockingboard_IIplus_IIe.po

The runner copies the input image, launches only its own emulator process,
types keys through the debug protocol, and checks Applesoft's executing line
as well as menu text. Merely seeing an old menu label is never a return check.
This verifies execution and keyboard recovery; it does not judge audible
speech quality or constitute a physical Mockingboard test.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GS2 = Path("C:/Users/hasse/source/repos/gssquared")
DEFAULT_EMULATOR = DEFAULT_GS2 / "build-phasor-pr/GSSquared.exe"
DEFAULT_CLIENT = DEFAULT_GS2 / "clients/python/src"
PLATFORMS = {1: "Apple II Plus", 2: "Apple IIe", 3: "Apple IIe Enhanced"}


def connect_client(client, address: Path) -> None:
    """Support Windows CPython builds that omit AF_UNIX's address parser.

    Windows itself supports AF_UNIX. Such Python builds can create family-1
    sockets and perform send/recv, but need Winsock to supply sockaddr_un.
    """
    if hasattr(socket, "AF_UNIX"):
        client.connect(str(address))
    elif os.name == "nt":
        encoded = os.fsencode(str(address))
        if len(encoded) >= 108:
            raise ValueError("Windows AF_UNIX socket path must be under 108 bytes")

        class UnixAddress(ctypes.Structure):
            _fields_ = [("family", ctypes.c_ushort), ("path", ctypes.c_char * 108)]

        winsock = ctypes.WinDLL("Ws2_32.dll")
        winsock.connect.argtypes = [ctypes.c_size_t, ctypes.c_void_p, ctypes.c_int]
        winsock.connect.restype = ctypes.c_int
        winsock.WSAGetLastError.restype = ctypes.c_int
        sock = socket.socket(1, socket.SOCK_STREAM)
        value = UnixAddress(1, encoded)
        if winsock.connect(sock.fileno(), ctypes.byref(value), ctypes.sizeof(value)):
            error = winsock.WSAGetLastError()
            sock.close()
            raise OSError(error, "Winsock AF_UNIX connect failed")
        client._sock = sock
        client._handshaked = False
        client._next_seq = 1
    else:
        raise RuntimeError("Python has no AF_UNIX support")
    client._sock.settimeout(10)
    client.hello()


class Session:
    def __init__(self, client, gs2, directory: Path, timeout: float):
        self.client, self.gs2 = client, gs2
        self.directory, self.timeout = directory, min(timeout, 60)
        self.records: list[dict] = []

    def snapshot(self) -> dict:
        registers = self.client.get_regs()
        # Explicit TEXT40 avoids protocol errors while the graphics demos are
        # active. Text memory still identifies their last visible menu.
        screen = self.client.video_text(page=1, mode=self.gs2.VIDEO_MODE_TEXT40)
        return {
            "cycle": int.from_bytes(registers[:8], "little"),
            "pc": int.from_bytes(registers[16:18], "little"),
            "line": int.from_bytes(self.client.read_mem(self.gs2.MEM_MAIN_RAW, 0x75, 2), "little"),
            "speech": list(self.client.read_mem(self.gs2.MEM_MAIN_RAW, 0x90F0, 3)),
            "text": "\n".join(screen.as_lines()),
            "video_flags": screen.flags,
        }

    def wait(self, label: str, predicate: Callable[[dict], bool],
             timeout: float | None = None) -> dict:
        deadline = time.monotonic() + (self.timeout if timeout is None else min(timeout, 60))
        last = {}
        while time.monotonic() < deadline:
            last = self.snapshot()
            for message in ("SYNTAX ERROR", "UNDEF'D STATEMENT", "OUT OF MEMORY",
                            "ILLEGAL QUANTITY", "FILE NOT FOUND", "I/O ERROR"):
                if message in last["text"]:
                    raise AssertionError(f"{label}: {message}\n{last['text']}")
            if predicate(last):
                return last
            time.sleep(0.035)
        self.record("FAIL " + label, last)
        raise AssertionError(f"{label}: timeout; line={last.get('line')} "
                             f"PC=${last.get('pc', 0):04X}; speech={last.get('speech')}\n"
                             f"{last.get('text', '')}")

    def ready(self, label: str, text: str, line: int, *, after: int = 0,
              timeout: float | None = None) -> dict:
        stable_since = None

        def predicate(state: dict) -> bool:
            nonlocal stable_since
            matches = text in state["text"] and state["line"] == line and state["cycle"] >= after
            if not matches:
                stable_since = None
                return False
            if stable_since is None:
                stable_since = time.monotonic()
            return time.monotonic() - stable_since >= 0.12

        state = self.wait(label, predicate, timeout)
        self.record(label, state)
        return state

    def record(self, label: str, state: dict | None = None) -> None:
        state = self.snapshot() if state is None else state
        record = {"test": label, **state}
        self.records.append(record)
        (self.directory / "checks.json").write_text(json.dumps(self.records, indent=2) + "\n")
        print(f"PASS {label}: line={state.get('line')} PC=${state.get('pc', 0):04X} "
              f"speech={state.get('speech')}", flush=True)

    def key(self, value: str) -> int:
        before = self.snapshot()["cycle"]
        self.client.paste_text(value)
        return before + 10000

    def main_menu(self, label: str, *, after: int = 0) -> dict:
        return self.ready(label, "MAIN MENU", 170, after=after)

    def effects_menu(self, label: str, *, after: int = 0) -> dict:
        return self.ready(label, "SOUND EFFECTS MENU", 1140, after=after)

    def exit_to_basic(self) -> None:
        after = self.key("\x1b")
        self.wait("Escape shows BASIC prompt",
                  lambda s: s["cycle"] >= after and "MAIN MENU" not in s["text"] and
                  any(line.lstrip().startswith("]") for line in s["text"].splitlines()))
        after = self.key('PRINT"EXIT.OK"\r')
        self.wait("immediate BASIC command executes",
                  lambda s: s["cycle"] >= after and
                  any(line.strip() == "EXIT.OK" for line in s["text"].splitlines()))
        self.record("Escape exits to functioning BASIC")

    def exercise(self, *, boot_only: bool = False, exit_only: bool = False) -> None:
        state = self.main_menu("boot to main menu")
        if boot_only:
            return
        if exit_only:
            self.exit_to_basic()
            return
        after = self.key("Z")
        self.main_menu("invalid main-menu key returns", after=after)
        after = self.key("a")
        self.effects_menu("lowercase a opens sound effects", after=after)
        for key in "ABCDEFGHIJKL":
            after = self.key(key)
            self.effects_menu("sound effect " + key + " completes", after=after)
        after = self.key("C")
        self.wait("train is executing", lambda s: 1600 <= s["line"] <= 1710 and s["cycle"] >= after)
        after = self.key("\x1b")
        stopped = self.effects_menu("Escape stops train", after=after)
        if stopped["speech"][2] != 1:
            raise AssertionError("train returned without latching Escape")
        after = self.key("z")
        self.effects_menu("invalid sound-effect key returns", after=after)
        after = self.key("\x1b")
        self.main_menu("Escape exits sound effects", after=after)

        after = self.key("b")
        self.ready("lowercase b opens music", "MUSIC DEMO", 2021, after=after)
        for key in "ASDFGHJK":
            after = self.key(key)
            self.ready("music key " + key, "MUSIC DEMO", 2021, after=after)
        after = self.key("z")
        self.ready("invalid music key returns", "MUSIC DEMO", 2021, after=after)
        after = self.key("a")
        self.ready("lowercase music key returns", "MUSIC DEMO", 2021, after=after)
        after = self.key("\x1b")
        self.main_menu("Escape exits music", after=after)

        after = self.key("c")
        self.wait("speech demo starts", lambda s: "THIS DEMONSTRATION UTILIZES" in s["text"] and s["cycle"] >= after)
        if state["speech"][0] == 0:
            self.wait("missing speech hardware prompt", lambda s: "NO SC-01 OR SSI-263" in s["text"])
            after = self.key(" ")
            self.main_menu("missing speech hardware returns", after=after)
        else:
            completed = self.main_menu("speech demonstration completes", after=after)
            if completed["speech"][1] != 0:
                raise AssertionError(f"speech did not complete successfully: {completed['speech']}")
            after = self.key("C")
            self.wait("speech playback active", lambda s: s["line"] == 50 and s["cycle"] >= after)
            after = self.key("\x1b")
            stopped = self.main_menu("Escape stops speech", after=after)
            if stopped["speech"][1] != 1:
                raise AssertionError(f"speech abort status missing: {stopped['speech']}")

        for key, name in zip("DEFGH", ("worm", "laser", "multiple tones", "multiple noise 1", "multiple noise 2")):
            before = self.snapshot()["cycle"]
            after = self.key(key.lower())
            # The noise programs intentionally leave the main-menu text in
            # place. Observe actual execution leave its GET line first.
            self.wait(name + " starts", lambda s: s["line"] != 170 and s["cycle"] > before)
            self.main_menu(name + " completes", after=after)
        self.exit_to_basic()


def run_platform(args, gs2, platform: int) -> dict:
    directory = args.artifacts.resolve() / f"p{platform}"
    directory.mkdir(parents=True, exist_ok=True)
    disk_copy = directory / "demo.po"
    shutil.copyfile(args.disk, disk_copy)
    config = directory / "test.gs2"
    platform_name = {1: "apple2plus", 2: "apple2e", 3: "apple2e_enhanced"}[platform]
    config_text = (f'gs2_version = 1\nid = "mockingboard-smoke-p{platform}"\n'
                   f'name = "Mockingboard compatibility p{platform}"\n'
                   f'platform = "{platform_name}"\nclock = "ntsc"\n'
                   f'scanner = "{"apple2" if platform == 1 else "apple2e"}"\n')
    if platform == 1:
        config_text += '\n[[cards]]\nslot = 0\ncard = "language_card"\n'
    config_text += ('\n[[cards]]\nslot = 4\ncard = "mockingboard"\n'
                    '\n[[cards]]\nslot = 6\ncard = "disk_ii"\n')
    config.write_text(config_text, encoding="ascii")
    address = Path(tempfile.gettempdir()) / f"mb{os.getpid()}p{platform}.sock"
    command = [str(args.emulator.resolve()), str(config), f"-p{platform}", f"-ds6d1={disk_copy}",
               "--debug", str(address), "--no-quit-confirm"]
    env = os.environ.copy()
    env.setdefault("SDL_AUDIODRIVER", "dummy")
    options = {}
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        options["startupinfo"] = startup
    log = (directory / "emulator.log").open("w", encoding="utf-8")
    process = subprocess.Popen(command, cwd=args.client_path.resolve().parents[2],
                               env=env, stdout=log, stderr=subprocess.STDOUT, **options)
    client = gs2.Client()
    result = {"platform": platform, "name": PLATFORMS[platform], "command": command,
              "disk_sha256": hashlib.sha256(args.disk.read_bytes()).hexdigest(), "passed": False}
    try:
        deadline = time.monotonic() + 20
        last_error = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"emulator exited early: status {process.returncode}")
            try:
                connect_client(client, address)
                break
            except (OSError, RuntimeError) as error:
                last_error = error
                client.close()
                time.sleep(0.1)
        else:
            raise RuntimeError(f"debug socket never became ready: {last_error}")
        status = client.get_status()
        if status.platform_id != platform:
            raise AssertionError(f"wrong platform: {status.platform_id}; expected {platform}")
        session = Session(client, gs2, directory, args.timeout)
        session.exercise(boot_only=args.boot_only, exit_only=args.exit_only)
        result["passed"] = True
        result["checks"] = len(session.records)
    except Exception as error:
        result["error"] = str(error)
        raise
    finally:
        (directory / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        client.close()
        # GSSquared's graceful QUIT unconditionally overwrites a shared trace
        # in the user's Documents folder. Kill only this owned subprocess so
        # validation artifacts stay isolated; it mounted only our disk copy.
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        log.close()
        address.unlink(missing_ok=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emulator", type=Path, default=DEFAULT_EMULATOR)
    parser.add_argument("--client-path", type=Path, default=DEFAULT_CLIENT)
    parser.add_argument("--disk", type=Path, default=ROOT / "Mockingboard_IIplus_IIe.po")
    parser.add_argument("--platform", choices=("1", "2", "3", "all"), default="all")
    parser.add_argument("--artifacts", type=Path, default=ROOT / "scratch-validation/build/emulator")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--boot-only", action="store_true")
    parser.add_argument("--exit-only", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.client_path.resolve()))
    import gs2debug as gs2
    platforms = (1, 2, 3) if args.platform == "all" else (int(args.platform),)
    for platform in platforms:
        print(f"Testing {PLATFORMS[platform]}", flush=True)
        run_platform(args, gs2, platform)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
