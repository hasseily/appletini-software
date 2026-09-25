"""GAME on the actual Apple memory map with permanent auxiliary LC code banks.

Uses a2sim.Machine and an ordinary py65 65C02. Opcode and data fetches use
exactly the same bank mapping: there are no instruction-only windows. The
standalone kernel's far-memory services are trapped in Python. Reported CPU
cycles exclude PSRAM latency and do not estimate TURBO wall-clock performance.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import gamesim

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "tools"))
import a2sim  # noqa: E402
import wad2a2  # noqa: E402

OUT = PROJECT / "build/host/banked-validation"


class MeasuredMachine(a2sim.Machine):
    """Track actual stack writes without assigning hardware timing costs."""
    def __init__(self, *args, **kwargs):
        self.stack_tracking = False
        super().__init__(*args, **kwargs)
        self.hardware_stack_min = {}
        self.software_stack_floor = 0xB800
        self.software_stack_min_write = 0xC000
        self.software_stack_min_pointer = 0xC000
        self.software_sp_address = None

    def __setitem__(self, address, value):
        super().__setitem__(address, value)
        if not self.stack_tracking:
            return
        if 0x0100 <= address < 0x0200:
            context = self.bank if self.sw["altzp"] else 0x80
            self.hardware_stack_min[context] = min(
                self.hardware_stack_min.get(context, 0x100), address & 0xFF)
        if self.software_stack_floor <= address < 0xC000 and not self.sw["ramwrt"]:
            self.software_stack_min_write = min(self.software_stack_min_write, address)
        if self.software_sp_address is not None and address in (
                self.software_sp_address, self.software_sp_address + 1):
            # Bytewise updates can expose a transient pointer. This is a
            # conservative observed bound, reported separately from writes.
            pointer = self[self.software_sp_address] | self[self.software_sp_address + 1] << 8
            if self.software_stack_floor <= pointer <= 0xC000:
                self.software_stack_min_pointer = min(self.software_stack_min_pointer, pointer)


class MappedMemory:
    """Fixed-size slice access for existing state readers and kernel traps."""
    def __init__(self, machine):
        self.machine = machine

    def __len__(self):
        return 65536

    def __getitem__(self, address):
        if isinstance(address, slice):
            return bytearray(self.machine[a] for a in range(*address.indices(65536)))
        return self.machine[address]

    def __setitem__(self, address, value):
        if isinstance(address, slice):
            positions = range(*address.indices(65536))
            if len(positions) != len(value):
                raise ValueError("mapped-memory writes cannot resize memory")
            for a, v in zip(positions, value):
                self.machine[a] = v
        else:
            self.machine[address] = value


def build(out=OUT):
    out = Path(out)
    dependencies = list((PROJECT / "src/game").glob("*"))
    dependencies += list((PROJECT / "src/kernel").glob("*.inc"))
    dependencies += [PROJECT / "src/kernel/gamebanks.s"]
    dependencies += [PROJECT / "tools/bank_game.py", PROJECT / "tests/host/flatkern.s",
                     PROJECT / "build/data/doomdata.inc", Path(__file__)]
    image = out / "GAME.BIN"
    if not image.exists() or image.stat().st_mtime < max(p.stat().st_mtime for p in dependencies):
        subprocess.run([sys.executable, str(PROJECT / "tools/bank_game.py"),
                        "--out", str(out), "--standalone"], check=True,
                       stdout=subprocess.DEVNULL)
    return out


class BankedGame(gamesim.FlatGame):
    def __init__(self, out=OUT):
        out = build(out)
        self.L = gamesim.labels(out / "game.lbl")
        rom = out / "test-rom.bin"
        rom.write_bytes(bytes([0xEA]) * 0x4000)
        self.machine = MeasuredMachine(rom, mouse=False, io_cycles=0)
        self.mem = MappedMemory(self.machine)
        self.mpu = self.machine.mpu
        self.banks = self.machine.aux_banks
        for bank, data in wad2a2.load_banks(gamesim.DATA).items():
            self.machine.bank_memory(bank)[:] = data
        image = (out / "GAME.BIN").read_bytes()
        self.machine.main[0x0200:0x0200 + len(image)] = image
        inventory = json.loads((out / "banks.json").read_text())
        self.bank_groups = dict(inventory["banks"])
        self.code_banks = set(self.bank_groups.values())
        self.optional_entries = {entry["public"]: (inventory["banks"][entry["group"]],
                                                    self.L[entry["private"]])
                                 for entry in inventory["entries"]
                                 if entry["private"] in self.L}
        for bank in self.code_banks:
            self.machine.bank_memory(bank)[0xD000:] = (out / f"GBANK{bank}.BIN").read_bytes()
        info = (out / "GAME.INFO").read_bytes()
        self.machine.bank_memory(1)[0x6000:0x6000 + len(info)] = info
        tables = (out / "GAME.TABLES").read_bytes()
        self.machine.bank_memory(127)[0x0200:0x0200 + len(tables)] = tables
        self.machine[0xC083]
        self.machine[0xC083]
        self.mem[self.L["kbanks"]] = 128
        # Reuse the tested byte-copy implementations, with no historical
        # synthetic GAME-space timing surcharge attached to these traps.
        def trap(fn):
            def run():
                _, count = fn()
                return 0, count
            return run
        self.traps = {self.L[name]: trap(fn) for name, fn in (
            ("trap_far_read", self._far_read), ("trap_far_write", self._far_write),
            ("trap_far_copy", self._far_copy), ("trap_far_elem", self._far_elem),
            ("trap_crash", self._crash))}
        self.far_calls = self.far_bytes = 0
        self.machine.software_sp_address = self.L["sp"]
        self.machine.software_stack_floor = self.L["__STACKSTART__"] - self.L["__STACKSIZE__"]
        floor = self.machine.software_stack_floor
        self.machine.main[floor:floor + 32] = bytes([0xA5]) * 32
        self.machine.stack_tracking = True
        self.call("gb_init")

    def call(self, label, a=0, x=0, limit=200_000_000):
        if self.machine.sw["altzp"]:
            raise AssertionError("host entry while a game bank is still active")
        entry = label
        if isinstance(label, str) and label not in self.L and label in self.optional_entries:
            # Unused C API wrappers have no permanent game gate. The host
            # debugger may still call one through a temporary main-LC gate
            # while main is mapped. This is real 65C02 code and real mapping.
            bank, target = self.optional_entries[label]
            gate = bytes([0x20]) + self.L["gb_call"].to_bytes(2, "little")
            gate += bytes([bank]) + target.to_bytes(2, "little")
            self.machine.lc[False][0x3F00:0x3F06] = gate
            entry = 0xFF00
        cycles = super().call(entry, a, x, limit)
        if self.machine.sw["altzp"] or self.machine.sw["ramrd"] or self.machine.sw["ramwrt"]:
            raise AssertionError(f"{label} did not restore main memory")
        if self.mem[self.L["gb_current"]] != 0x80 or self.mpu.sp != 0xFF:
            raise AssertionError(f"{label} did not unwind its bank contexts")
        return cycles

    def boot(self):
        # Production crt0 initializes BSS/cc65's stack and calls game_init.
        return self.call("game_boot")

    def stack_usage(self):
        m = self.machine
        return dict(software_written_bytes=0xC000 - m.software_stack_min_write,
                    software_observed_pointer_bytes=0xC000 - m.software_stack_min_pointer,
                    hardware_written_bytes={context: 0x100 - offset
                                            for context, offset in m.hardware_stack_min.items()})

    def stack_guard_intact(self):
        floor = self.machine.software_stack_floor
        return self.machine.main[floor:floor + 32] == bytes([0xA5]) * 32
