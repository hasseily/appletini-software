#!/usr/bin/env python3
"""Rebuild the native ProDOS edition from the unmodified 1982 DOS disk."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from disk_formats import (DEFAULT_MASTER, TYPE_BAS, TYPE_BIN, basic_source,
                          build_prodos_image, detokenize_body, pack_basic,
                          parse_basic, read_dos_disk, runtime_files)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Sound_and_Speech_I_Demo_Disk__1982.dsk"
SOURCE_SHA256 = "5745a87e1c6dfb9948ce9fa759d27504a22883c2ff0349e195c9370bbd6e238c"
NAMES = {"PRIMARY ROUTINES": "PRIMARY", "TITLE PAGE": "TITLE.PAGE",
         "THE WORM": "THE.WORM", "THE LASER": "THE.LASER",
         "MULTIPLE TONES": "MULTIPLE.TONES", "MULTIPLE NOISE1": "MULTIPLE.NOISE1",
         "MULTIPLE NOISE2": "MULTIPLE.NOISE2"}


def patched_basic(name: str, data: bytes) -> bytes:
    lines = {n: detokenize_body(body) for n, body in parse_basic(data)}
    for n, body in list(lines.items()):
        for old, new in NAMES.items():
            body = body.replace('"RUN ' + old + '"', '"RUN ' + new + '"')
            body = body.replace('"BLOAD ' + old + '"', '"BLOAD ' + new + '"')
        # Put the shape tables above both HGR pages and below the resident code.
        body = re.sub(r"POKE\s+233,16", "POKE233,96", body)
        body = re.sub(r"POKE\s+233,17", "POKE233,97", body)
        # The IIe keyboard can return lowercase. Applesoft comparisons yield 0/1.
        body = re.sub(r"GET\s+A\$", lambda _: "GETA$:A$=CHR$(ASC(A$)-32*(ASC(A$)>96ANDASC(A$)<123))", body)
        lines[n] = body
    # RUN resets Applesoft variables: apply this on every program entry.
    lines[0] = "HIMEM:8192"
    if name == "DEMO1":
        lines[165] = 'VTAB20:HTAB3:IFPEEK(37104)=0THENPRINT"SPEECH HARDWARE NOT DETECTED"'
        lines[166] = 'VTAB20:HTAB3:IFPEEK(37104)=1THENPRINT"SPEECH: SC-01 / ESC STOPS SPEECH"'
        lines[167] = 'VTAB20:HTAB3:IFPEEK(37104)=2THENPRINT"SPEECH: SSI-263 / ESC STOPS SPEECH"'
        lines[175] = "POKE37106,0"
        lines[220] = 'IFA$=CHR$(27)THENCALL-28604:HOME:END'
    if name == "DEMO2":
        lines[1145] = "CALL-28604:POKE37106,0"
        lines[1170] = 'IFA$="C"THENGOSUB1600:Y=Y-3:GOTO1140'
        lines[1600] = "POKE8,16:POKE9,137:CALL-32748"
        # Keep the original empty-FOR pauses. The keyboard check follows a
        # completed FOR, so cancellation never abandons an Applesoft loop.
        lines[1610] = "FORT=1TO500:NEXTT:GOSUB1700:IFPEEK(37106)THEN1690"
        lines[1630] = "Q=2"
        lines[1640] = "POKE6,0:POKE7,129:CALL-32768:CALL-32768"
        lines[1650] = "IFPEEK(37106)THEN1690"
        lines[1660] = "FORT=1TO500:NEXTT:GOSUB1700:IFPEEK(37106)THEN1690"
        lines[1680] = "Q=Q-1:IFQ>0THEN1640"
        lines[1690] = "CALL-28604:RETURN"
        lines[1700] = "IFPEEK(49152)=155THENPOKE49168,0:POKE37106,1"
        lines[1710] = "RETURN"
    if name == "DEMO3":
        lines[2020] = 'VTAB24:HTAB5:PRINT"PRESS ESC TO RETURN TO MENU":POKE35,22'
    if name == "DEMO4":
        lines[5] = "POKE37106,0"
        lines[45] = 'PRINT:HTAB4:PRINT"PRESS ESC TO STOP SPEECH"'
        lines[46] = "IFPEEK(37104)=0THEN80"
        lines[55] = "IFPEEK(37105)=2THEN90"
        lines[80] = 'PRINT:HTAB4:PRINT"NO SC-01 OR SSI-263 SPEECH RESPONSE."'
        lines[81] = 'HTAB4:PRINT"SOUND EFFECTS STILL WORK."'
        lines[82] = 'HTAB4:PRINT"PRESS ANY KEY TO RETURN":GETA$'
        lines[83] = 'PRINTCHR$(4);"RUN DEMO1"'
        lines[90] = 'PRINT:HTAB4:PRINT"SPEECH TIMED OUT. PRESS ANY KEY.":GETA$'
        lines[91] = 'PRINTCHR$(4);"RUN DEMO1"'
    return pack_basic(sorted(lines.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--output", type=Path, default=ROOT / "Mockingboard_IIplus_IIe.po")
    parser.add_argument("--acme", default=shutil.which("acme") or "acme")
    args = parser.parse_args()
    if hashlib.sha256(args.source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("Source disk differs from the audited 1982 image")
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    driver_path = build / "speech.bin"
    subprocess.run([args.acme, "-f", "plain", "-o", str(driver_path), "--symbollist",
                    str(build / "speech.sym"), str(ROOT / "src/speech.a")], check=True)
    driver = driver_path.read_bytes()
    if len(driver) > 0x500:
        raise ValueError("Speech driver overlaps BASIC.SYSTEM's $9600 workspace")
    originals = read_dos_disk(args.source)
    files = runtime_files(args.master)
    manifest = []
    for original in originals:
        name = NAMES.get(original.name, original.name)
        data, aux = original.data, original.load_address
        if original.type == 2:
            data, aux, kind = patched_basic(original.name, data), 0x0801, TYPE_BAS
            (build / (name + ".bas")).write_text(basic_source(data), encoding="ascii")
        elif original.type == 4:
            kind = TYPE_BIN
            if original.name == "PRIMARY ROUTINES":
                assert aux == 0x9000 and len(data) == 80
                patched = bytearray(data)
                patched[0:3] = bytes.fromhex("4C 00 91")
                # The obsolete standalone SC-01 polling entry is unreachable;
                # remove it as well so no unbounded hardware wait remains.
                patched[0x13:0x23] = b"\x60" + b"\xEA" * 15
                data = bytes(patched).ljust(0x100, b"\0") + driver
            elif original.name == "DEMO1.OBJ":
                assert aux == 0x8000 and data[:3] == bytes.fromhex("A0 00 B1")
                data = bytes.fromhex("4C 03 91") + data[3:]
            elif original.name.startswith("SHPTABLE"):
                aux += 0x5000
        else:
            raise ValueError(f"Unsupported original type: {original.name}")
        files.append((name, kind, aux, data))
        if original.name == "DEMO":
            files.append(("STARTUP", TYPE_BAS, 0x0801, data))
        manifest.append({"original": original.name, "prodos": name,
                         "source_sha256": hashlib.sha256(original.data).hexdigest(),
                         "sha256": hashlib.sha256(data).hexdigest(),
                         "type": kind, "aux": aux, "length": len(data)})
    used = build_prodos_image(args.output, files, master_path=args.master)
    report = {"source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
              "master_sha256": hashlib.sha256(args.master.read_bytes()).hexdigest(),
              "output": args.output.name,
              "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
              "blocks_used": used, "files": manifest}
    (ROOT / "build-manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Built {args.output}: {len(files)} files, {used}/280 blocks used")
    print("SHA256 " + report["output_sha256"])


if __name__ == "__main__":
    main()
