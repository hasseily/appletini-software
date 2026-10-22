"""Run linked libtini ProDOS SYS programs on the installed py65 65C02."""
from __future__ import annotations

from pathlib import Path

from py65.devices.mpu65c02 import MPU

from apple2_model import Apple2Memory, read_labels


class TargetRun:
    def __init__(self, program: Path, labels: Path, banks: int = 4):
        self.memory = Apple2Memory(banks)
        self.labels = read_labels(labels)
        image = program.read_bytes()
        if len(image) > 0x8800:
            raise AssertionError("SYS image exceeds linker code/data memory")
        self.memory.main[0x2000:0x2000 + len(image)] = image
        self.cpu = MPU(memory=self.memory, pc=0x2000)
        self.memory.cpu = self.cpu
        self.cpu.sp = 0xF7
        self.cpu.p = 0x20  # IRQ initially enabled; decimal clear.
        self.steps = 0
        self.quit = False
        self.mli_calls = []
        # Recognisable OS-owned memory. Raw loader writes only above $2000.
        for i in range(0x100):
            self.memory.main[i] = (i * 17 + 3) & 0xFF
        self.memory.main[0x180:0x1F8] = bytes([0x6B]) * 0x78
        self.initial_zero_page = bytes(self.memory.main[:0x100])
        self.mode = 0
        self.entered_main = False
        self.in_main = False
        self.main_return = None
        self.min_hardware_sp = 0xFF
        self.min_software_sp = 0xA800

    def byte(self, name):
        return self.memory.main[self.labels[name]]

    def word(self, name):
        address = self.labels[name]
        return self.memory.main[address] | self.memory.main[address + 1] << 8

    def _rts(self):
        self.cpu.pc = (self.cpu.stPopWord() + 1) & 0xFFFF

    def run(self, max_steps=30_000_000):
        while self.steps < max_steps:
            pc = self.cpu.pc
            if pc == self.labels.get("_main") and not self.entered_main:
                self.entered_main = True
                self.in_main = True
                stack = self.cpu.sp
                self.main_return = (self.memory.main[0x100 + ((stack + 1) & 255)] |
                                    self.memory.main[0x100 + ((stack + 2) & 255)] << 8) + 1
                if "_test_mode" in self.labels:
                    self.memory.main[self.labels["_test_mode"]] = self.mode
            if self.in_main and pc == self.main_return:
                self.in_main = False
            self.min_hardware_sp = min(self.min_hardware_sp, self.cpu.sp)
            if self.cpu.sp < 0x80:
                raise AssertionError(f"hardware stack left reservation: SP=${self.cpu.sp:02X}")
            if self.memory.ramrd and not 0x140 <= pc < 0x180:
                raise AssertionError(f"AUX instruction fetch outside trampoline: ${pc:04X}")
            if (self.memory.ramrd or self.memory.ramwrt or self.memory.bank) and not self.cpu.p & 4:
                raise AssertionError("IRQ enabled while AUX transfer mapping is active")
            if pc == 0xBF00:
                sp = self.cpu.sp
                ret = self.memory.main[0x100 + ((sp + 1) & 0xFF)]
                ret |= self.memory.main[0x100 + ((sp + 2) & 0xFF)] << 8
                command = self.memory[ret + 1]
                params = self.memory[ret + 2] | self.memory[ret + 3] << 8
                self.mli_calls.append((command, params))
                if command == 0x65:
                    self.quit = True
                    return
                raise AssertionError(f"unexpected ProDOS MLI ${command:02X}")
            if pc == 0xFDED:
                self.memory.output.append(self.cpu.a & 0x7F)
                self._rts()
            elif pc in (0xFC58, 0xFB39, 0xFE89, 0xFE93):
                # HOME / SETTXT / SETKBD / SETVID, if used by the diagnostic.
                self._rts()
            else:
                opcode = self.memory[pc]
                # cc65 updates its 16-bit software stack pointer bytewise;
                # between writes it can momentarily appear above its limit.
                # Check stable values at every JSR and RTS during main.
                if self.in_main and opcode in (0x20, 0x60):
                    address = self.labels["c_sp"]
                    software_sp = self.memory.main[address] | self.memory.main[address + 1] << 8
                    self.min_software_sp = min(self.min_software_sp, software_sp)
                    if not 0xA000 <= software_sp <= 0xA800:
                        raise AssertionError(f"software stack left reservation: ${software_sp:04X}")
                if opcode == 0:
                    raise AssertionError(f"unexpected BRK at ${pc:04X}")
                self.cpu.step()
            self.steps += 1
        raise AssertionError(f"target exceeded {max_steps:,} steps at ${self.cpu.pc:04X}")

