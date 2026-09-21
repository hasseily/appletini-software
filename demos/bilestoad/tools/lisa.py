#!/usr/bin/env python3
"""Read DOS 3.3 disk images and decode LISA 2.5 tokenized source files.

LISA 2.5 file layout (learned from the upstream SOURCE disk, whose files
decode to the exact upstream text):

    +0  load address, little endian ($1800)
    +2  source length, little endian
    +4  lines: <count> <count bytes>, the last byte of each line is $0D

A line is plain ASCII up to the mnemonic token (a byte >= $80). One mode byte
follows the token: $20 for a pseudo-op, a small addressing-mode number for a
6502 instruction. The operand is plain ASCII.
"""

import argparse
import sys
from pathlib import Path

TOKENS = {
    0x80: "BGE", 0x81: "BLT", 0x82: "BMI", 0x83: "BCC", 0x84: "BCS",
    0x85: "BPL", 0x86: "BNE", 0x87: "BEQ", 0x99: "CLC", 0x9A: "CLD",
    0x9C: "DEX", 0x9D: "DEY", 0x9E: "INX", 0x9F: "INY", 0xA0: "NOP",
    0xA1: "PHA", 0xA2: "PLA", 0xA3: "PHP", 0xA4: "PLP", 0xA5: "RTS",
    0xA9: "SEC", 0xAB: "SED", 0xAC: "TAX", 0xAD: "TAY", 0xAF: "TXA",
    0xB1: "TYA", 0xC0: "ADC", 0xC1: "AND", 0xC2: "ORA", 0xC4: "CMP",
    0xC5: "CPX", 0xC6: "CPY", 0xC7: "DEC", 0xC8: "EOR", 0xC9: "INC",
    0xCA: "JMP", 0xCB: "JSR", 0xCD: "LDA", 0xCE: "LDX", 0xCF: "LDY",
    0xD0: "STA", 0xD1: "STX", 0xD2: "STY", 0xD4: "LSR", 0xD5: "ROR",
    0xD6: "ROL", 0xD7: "ASL", 0xD8: "ADR", 0xD9: "EQU", 0xDA: "ORG",
    0xDB: "OBJ", 0xDC: "EPZ", 0xDD: "STR", 0xDE: "DCM", 0xE0: "ICL",
    0xE1: "END", 0xE2: "LST", 0xE3: "NLS", 0xE4: "HEX", 0xF0: "SBC",
    0xF9: ".DA",
}

SECTOR = 256


def read_dsk(path):
    """Return {name: (type, bytes)} for a DOS 3.3 order .dsk image."""
    image = Path(path).read_bytes()

    def sector(track, sec):
        start = (track * 16 + sec) * SECTOR
        return image[start:start + SECTOR]

    files = {}
    vtoc = sector(17, 0)
    track, sec = vtoc[1], vtoc[2]
    seen = set()
    while track and (track, sec) not in seen:
        seen.add((track, sec))
        catalog = sector(track, sec)
        for index in range(7):
            entry = catalog[11 + index * 35:11 + (index + 1) * 35]
            if entry[0] in (0x00, 0xFF):
                continue
            name = "".join(chr(b & 0x7F) for b in entry[3:33]).rstrip()
            data = b""
            list_track, list_sec = entry[0], entry[1]
            while list_track:
                ts_list = sector(list_track, list_sec)
                for k in range(12, 256, 2):
                    if ts_list[k] or ts_list[k + 1]:
                        data += sector(ts_list[k], ts_list[k + 1])
                list_track, list_sec = ts_list[1], ts_list[2]
            files[name] = (entry[2] & 0x7F, data)
        track, sec = catalog[1], catalog[2]
    return files


def detokenize(data):
    """Return the source text lines of one LISA 2.5 file."""
    lines = []
    pos = 4
    while pos < len(data):
        count = data[pos]
        if count in (0x00, 0xFF):
            break
        raw = data[pos + 1:pos + 1 + count]
        pos += 1 + count
        if raw[-1:] == b"\r":
            raw = raw[:-1]
        token_at = next((i for i, b in enumerate(raw) if b >= 0x80), None)
        if token_at is None:
            text = raw.decode("ascii")
            # A label-only line is the padded label followed by ':'.
            if text[:1] not in (";", "*") and text.rstrip().endswith(":"):
                text = text.rstrip()[:-1].rstrip() + ":"
            lines.append(text)
            continue
        label = raw[:token_at].decode("ascii").rstrip()
        token = raw[token_at]
        if token not in TOKENS:
            raise ValueError("unknown LISA token $%02X" % token)
        operand = raw[token_at + 2:].decode("ascii")
        text = "%-9s%s" % (label, TOKENS[token])
        if operand:
            text += " " + operand
        elif raw[token_at + 1] == 0x20 or TOKENS[token] in ("LST", "NLS"):
            text += " "
        lines.append(text)
    return lines


def self_test(upstream):
    """Decode every SOURCE file and compare it with the upstream text."""
    upstream = Path(upstream)
    disk = next(upstream.glob("*SOURCE*.dsk"))
    files = read_dsk(disk)
    failures = 0
    for name in ("INTRO", "FRONT", "MAPS", "BACK", "APPENDIX", "EPILOGUE",
                 "TWO", "OB"):
        mine = [line.rstrip() for line in detokenize(files[name][1])]
        theirs = (upstream / "SOURCE" / (name + ".txt")).read_text().split("\n")
        theirs = [line.rstrip() for line in theirs]
        while theirs and not theirs[-1]:
            theirs.pop()
        diff = sum(1 for a, b in zip(mine, theirs) if a != b)
        diff += abs(len(mine) - len(theirs))
        print("%-9s %5d lines, %d differences" % (name, len(mine), diff))
        failures += diff
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("upstream", help="upstream repository directory")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--disk", choices=("SOURCE", "DATA"))
    parser.add_argument("--file", help="file name on the disk")
    args = parser.parse_args()
    if args.self_test:
        sys.exit(1 if self_test(args.upstream) else 0)
    disk = next(Path(args.upstream).glob("*%s*.dsk" % args.disk))
    print("\n".join(detokenize(read_dsk(disk)[args.file][1])))


if __name__ == "__main__":
    main()
