#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Execute real 6502 HTTP/FIFO code against transient redirect descriptors."""
from pathlib import Path
import functools
import json
import shutil
import subprocess

import mono_verify

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "mono-http-redirect-tests"
FINAL = "https://final.test/new/dir/page.html?ok=1"
BODY = b"FINAL\x00BINARY\x00BODY"

CONFIG = """
SYMBOLS { __STACKSIZE__: type=weak,value=$0800; }
MEMORY {
 ZP: start=$0080,size=$001A,type=rw,define=yes;
 MAIN: start=$6000,size=$5700,type=rw,file=%O,define=yes;
 WORK: start=$0880,size=$1780,type=rw,file="";
}
SEGMENTS {
 ZEROPAGE: load=ZP,type=zp;
 STARTUP: load=MAIN,type=ro;
 CODE: load=MAIN,type=ro;
 RODATA: load=MAIN,type=ro;
 LC: load=MAIN,type=ro;
 NET: load=MAIN,type=ro;
 DATA: load=MAIN,type=rw;
 BSS: load=WORK,type=bss,define=yes;
 NETBSS: load=WORK,type=bss;
}
"""
STARTUP = """
.setcpu "6502"
.include "zeropage.inc"
.export __STARTUP__ : absolute = 1
.export _test_done
.import _main, zerobss
.segment "STARTUP"
 ldx #$FF
 txs
 cld
 lda #$00
 ldx #$B7
 sta c_sp
 stx c_sp+1
 jsr zerobss
 jsr _main
_test_done:
 jmp _test_done
"""


class RedirectMemory(mono_verify.Memory):
    def __init__(self, stages, fragment):
        super().__init__({"https://start.test/old/page":
                          ("application/octet-stream", BODY, FINAL)}, fragment)
        self.stages = stages
        self.phase = 0
        self.started = False
        self.current = (3, 200, 0)
        self.body_reads = []

    def submit(self, packet):
        if packet[0] == 4:
            if packet[13] == 1:
                payload = packet[12:]
                method_length = payload[3]
                url_length = int.from_bytes(payload[4:6], "little")
                header_length = int.from_bytes(payload[6:8], "little")
                at = 12 + method_length + url_length
                headers = payload[at:at + header_length]
                fields = [line.split(b":", 1) for line in headers.split(b"\r\n") if line]
                agents = [value.strip() for name, value in fields if name.lower() == b"user-agent"]
                assert agents == [b"Mozilla/5.0 (Mobile; APPLE2LYNX/1)"], agents
                assert [value.strip() for name, value in fields if name.lower() == b"sec-ch-ua-mobile"] == [b"?1"]
                assert [value.strip() for name, value in fields if name.lower() == b"save-data"] == [b"on"]
            super().submit(packet)
            # The START request is accepted once. Redirects belong to ARM.
            if packet[13] == 1:
                self.started, self.phase = True, 0
            return
        selector = packet[5]
        if selector == 0x82 and self.started:
            self.current = self.stages[min(self.phase, len(self.stages) - 1)]
            self.phase += 1
            state, code, result, *verify = self.current
            reply = bytearray(64)
            reply[:10] = b"ATNH" + bytes((1, 64, 15, self.generation, state, 0))
            reply[10:12] = result.to_bytes(2, "little", signed=True)
            reply[12:14] = code.to_bytes(2, "little")
            reply[16:20] = len(self.body).to_bytes(4, "little")
            reply[20:24] = len(self.body).to_bytes(4, "little")
            reply[28:30] = len(self.url).to_bytes(2, "little")
            reply[30:32] = len(self.content_type).to_bytes(2, "little")
            reply[40:44] = (verify[0] if verify else 0).to_bytes(4, "little")
            self.answer(reply)
        elif selector == 0x83:
            state, code, *_ = self.current
            assert not 300 <= code < 400, "client read an intermediate redirect body"
            self.body_reads.append((state, code))
            if code == 0 or state == 1:
                offset = int.from_bytes(packet[6:8], "little")
                self.answer(bytes((self.generation, 1)) +
                            offset.to_bytes(4, "little") + b"\0\0")
            else:
                super().submit(packet)
        else:
            super().submit(packet)


def read_z(memory, address):
    data = memory.main[address:address + 256]
    return bytes(data[:data.index(0)]).decode()


def run_case(binary, symbols, name, stages, success, fragment=3, error=None):
    from py65.devices.mpu6502 import MPU
    memory = RedirectMemory(stages, fragment)
    memory.main[0x6000:0x6000 + len(binary)] = binary
    cpu = MPU(memory=memory, pc=0x6000)
    memory.cpu = cpu
    cpu.p, cpu.sp = 0x20, 255
    steps = 0
    while cpu.pc != symbols["_test_done"]:
        assert memory[cpu.pc] != 0, (name, "BRK", hex(cpu.pc))
        cpu.step()
        steps += 1
        if steps >= 2_000_000:
            raise AssertionError((name, "request did not terminate", hex(cpu.pc)))
    result = memory.main[symbols["_test_result"]]
    length = memory.main[symbols["_test_length"]]
    actual = bytes(memory.main[symbols["_test_body"]:symbols["_test_body"] + length])
    assert result == int(success), (name, result)
    assert memory.requests == ["https://start.test/old/page"], (name, memory.requests)
    assert memory.controls == [1, 2], (name, memory.controls)
    if success:
        assert actual == BODY, (name, actual)
        assert read_z(memory, symbols["_test_url"]) == FINAL
        assert read_z(memory, symbols["_mono_http_type"]) == "application/octet-stream"
        assert all(code == 0 or 200 <= code < 300 for _, code in memory.body_reads)
    else:
        assert not actual, (name, "non-final body escaped", actual)
    message_pointer = int.from_bytes(memory.main[symbols["_test_error"]:symbols["_test_error"]+2], "little")
    message = read_z(memory, message_pointer)
    if error is not None:
        assert message == error, (name, message, error)
    assert memory.intcxrom and not memory.selected
    assert not memory.ramrd and not memory.ramwrt and memory.bank == 0
    return {"case": name, "success": success, "instructions": steps,
            "descriptor_polls": memory.phase, "body": actual.hex(), "error": message}


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    cl65 = shutil.which("cl65")
    if not cl65:
        raise RuntimeError("cl65 is required")
    (BUILD / "test.cfg").write_text(CONFIG)
    (BUILD / "start.s").write_text(STARTUP)
    subprocess.run([cl65, "-t", "apple2", "--cpu", "6502", "-Os",
                    "--warnings-as-errors", "-C", str(BUILD / "test.cfg"),
                    "-Ln", str(BUILD / "test.lbl"), "-o", str(BUILD / "test.bin"),
                    str(BUILD / "start.s"), str(ROOT / "tests" / "mono_http_redirect.c"),
                    str(ROOT / "mono_http.c"), str(ROOT / "mono_mobile.c"), str(ROOT / "http_client" / "net.c"),
                    str(ROOT / "http_client" / "net.s"), str(ROOT / "mono_net_buffer.s")], check=True)
    symbols = mono_verify.labels(BUILD / "test.lbl")
    binary = (BUILD / "test.bin").read_bytes()
    # Reuse one valid ROM fixture across cases; its CRC is still checked by CPU.
    mono_verify.identity_rom = functools.lru_cache()(mono_verify.identity_rom)
    cases = []
    for code in (301, 302, 303, 307, 308):
        cases.append((str(code), [(2, code, 0), (2, 0, 0), (3, 200, 0)], True))
    cases.extend([
        ("three-hops", [(2, 301, 0), (2, 302, 0), (2, 308, 0), (3, 200, 0)], True),
        ("no-location", [(2, 302, 0), (3, 302, 0)], False),
        ("unsupported-final", [(2, 305, 0), (3, 305, 0)], False),
        ("redirect-loop", [(2, 301, 0), (2, 302, 0), (2, 301, 0), (4, 302, -109)], False),
        ("redirect-timeout", [(2, 308, 0)] * 12 + [(4, 308, -107)], False),
        ("final-404", [(2, 301, 0), (3, 404, 0)], False),
        ("tls-failure", [(2, 307, 0), (4, 0, -9984)], False),
    ])
    report = [run_case(binary, symbols, name, stages, success)
              for name, stages, success in cases]
    # One-byte fragmentation stresses final URL/type metadata and binary NULs.
    report.append(run_case(binary, symbols, "one-byte-fragments",
                           [(2, 308, 0), (3, 200, 0)], True, 1))
    for name, result, flags, message in (
        ("issuer-untrusted", -9984, 8, "TLS issuer untrusted; update CA bundle"),
        ("wrong-hostname", -9984, 4, "TLS certificate verification failed"),
        ("http-header-limit", -2, 0, "HTTP response limit; update Appletini firmware"),
    ):
        report.append(run_case(binary, symbols, name, [(4, 0, result, flags)], False, error=message))
    (BUILD / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS {len(report)} actual-6502 redirect/FIFO cases; mobile headers, final URL and binary body preserved")


if __name__ == "__main__":
    main()
