#!/usr/bin/env python3
"""Run ONEWWW.SYSTEM in py65 against a small model of the card.

The model has the SmartPort entry, the ONEWWW selector and a mouse card
in slot 4. It checks the calls that the program makes for two keys, a
mouse move and the Q key. Build first with build_onewww.py.
"""
from pathlib import Path

from py65.devices.mpu6502 import MPU

HERE = Path(__file__).resolve().parent


def main():
    program = (HERE / "build/ONEWWW.SYSTEM").read_bytes()
    cpu = MPU()
    mem = cpu.memory
    mem[0x2000:0x2000 + len(program)] = program
    for address, value in ((0xC701, 0x20), (0xC703, 0x00), (0xC705, 0x03),
                           (0xC707, 0x00), (0xC7FF, 0x0A),
                           (0xC40C, 0x20), (0xC4FB, 0xD6)):
        mem[address] = value
    for index in range(8):              # mouse entry offsets -> $C440+index
        mem[0xC412 + index] = 0x40 + index
    keys = [ord("G") | 0x80, ord("a") | 0x80, ord("Q") | 0x80]
    controls, mouse_calls = [], []
    state = {"mode": 1, "key_wait": 0, "mouse": (320, 200, 0), "done": False}

    def rts():
        low = mem[0x100 + ((cpu.sp + 1) & 0xFF)]
        high = mem[0x100 + ((cpu.sp + 2) & 0xFF)]
        cpu.sp = (cpu.sp + 2) & 0xFF
        cpu.pc = ((high << 8) | low) + 1 & 0xFFFF

    cpu.pc = 0x2000
    for _ in range(400000):
        pc = cpu.pc
        if pc == 0xC70D:                # SmartPort dispatcher
            low = mem[0x100 + ((cpu.sp + 1) & 0xFF)]
            high = mem[0x100 + ((cpu.sp + 2) & 0xFF)]
            ret = ((high << 8) | low) + 1
            command = mem[ret]
            plist = mem[ret + 1] | (mem[ret + 2] << 8)
            assert mem[plist] == 3 and mem[plist + 1] == 0
            assert mem[plist + 4] == 0x88
            buffer = mem[plist + 2] | (mem[plist + 3] << 8)
            if command == 0:
                reply = b"ATNW" + bytes([1, state["mode"]]) + bytes(10)
                mem[buffer:buffer + 16] = reply
            else:
                assert command == 4
                length = mem[buffer] | (mem[buffer + 1] << 8)
                payload = bytes(mem[buffer + 2:buffer + 2 + length])
                controls.append(payload)
                if payload[1] == 3 and (payload[2] & 0x7F) == ord("Q"):
                    state["mode"] = 0
            ret += 2                    # return after the three inline bytes
            mem[0x100 + ((cpu.sp + 1) & 0xFF)] = ret & 0xFF
            mem[0x100 + ((cpu.sp + 2) & 0xFF)] = ret >> 8
            cpu.a = 0
            cpu.p &= ~1                 # carry clear: no error
            rts()
            continue
        if 0xC440 <= pc <= 0xC447:      # mouse firmware
            assert cpu.x == 0xC4 and cpu.y == 0x40, (hex(cpu.x), hex(cpu.y))
            mouse_calls.append((pc - 0xC440, cpu.a))
            if pc - 0xC440 == 2:        # READMOUSE
                x, y, button = state["mouse"]
                mem[0x0478 + 4], mem[0x0578 + 4] = x & 255, x >> 8
                mem[0x04F8 + 4], mem[0x05F8 + 4] = y & 255, y >> 8
                mem[0x0778 + 4] = 0x80 if button else 0
                if len(mouse_calls) > 12:
                    state["mouse"] = (500, 300, 1)
            rts()
            continue
        if pc == 0xBF00:                # ProDOS QUIT
            state["done"] = True
            break
        if pc in (0xFC58, 0xFDED):      # HOME, COUT
            rts()
            continue
        # Give the next key when the program polls the keyboard.
        state["key_wait"] += 1
        if state["key_wait"] > 3000 and keys and mem[0xC000] < 0x80:
            mem[0xC000] = keys.pop(0)
            state["key_wait"] = 0
        if mem[pc] == 0x2C and mem[pc + 1] == 0x10 and mem[pc + 2] == 0xC0:
            mem[0xC000] &= 0x7F         # BIT $C010 clears the strobe
        cpu.step()

    assert state["done"], "the program did not quit"
    ops = [p[1] for p in controls]
    assert controls[0] == bytes([1, 1, 0]) or controls[0][:2] == bytes([1, 1])
    key_codes = [p[2] for p in controls if p[1] == 3]
    assert key_codes == [ord("G"), ord("a"), ord("Q")], key_codes
    moves = [p for p in controls if p[1] == 4]
    assert moves and all(len(p) == 7 for p in moves)
    assert moves[0][2:] == bytes([320 & 255, 320 >> 8, 200, 0, 0]), moves[0]
    assert moves[-1][2:] == bytes([500 & 255, 500 >> 8, 300 & 255, 300 >> 8, 1])
    assert ops[-1] == 2, ops
    kinds = [call[0] for call in mouse_calls]
    assert kinds[:5] == [7, 0, 5, 5, 4] and mouse_calls[1][1] == 1, kinds[:6]
    assert mem[0xC029] == 0x00       # the program does not change the video mode
    print(f"PASS: {len(controls)} CONTROL calls, {len(mouse_calls)} mouse calls")


if __name__ == "__main__":
    main()
