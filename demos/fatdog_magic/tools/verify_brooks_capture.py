"""Check Brooks pixels with the actual Appletini renderer and PL capture ranges.

This host-only test is not part of the Apple II program. --reproduce-black
checks the old failing disk against the same unmodified renderer with and
without the capture filter.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess

from prodos import raw_files

DEMO = Path(__file__).resolve().parents[1]


def compile_harness(firmware, output):
    vswhere = Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
    vs = Path(subprocess.check_output([str(vswhere), "-latest", "-products", "*",
        "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
        "-property", "installationPath"], text=True).strip())
    harness = firmware / "scripts/host_render_harness"
    frontend = firmware / "ps_sources/frontend"
    executable = output / "brooks_capture_test.exe"
    command = ["cl", "/nologo", "/W3", "/O2", "/std:c11", "/D_CRT_SECURE_NO_WARNINGS",
        "/FI" + str(harness / "harness_prefix.h"), "/I" + str(harness),
        "/I" + str(harness / "xil_stub"), "/I" + str(frontend),
        "/Fe" + str(executable), str(DEMO / "tools/brooks_capture_test.c")]
    command += [str(frontend / name) for name in ("apple_cycle_renderer.c", "appletini_ntsc.c",
                                                  "appletini_csbits.c", "apple2e_video_rom_data.c")]
    batch = output / "compile.cmd"
    batch.write_text('@echo off\ncall "' + str(vs / "VC/Auxiliary/Build/vcvars32.bat") +
        '" >nul\nif errorlevel 1 exit /b 1\n' + subprocess.list2cmdline(command) + "\n")
    subprocess.run(["cmd", "/c", str(batch)], cwd=output, check=True)
    return executable


def capture_ranges(firmware):
    source = (firmware / "hdl/apple/apple_cycle_capture.sv").read_text()
    function = re.search(r"function automatic logic in_video_range\b.*?endfunction", source, re.S)[0]
    return [(int(a, 16), int(b, 16) + 1) for a, b in re.findall(
        r"a >= 24'h([0-9A-Fa-f]+)\).*?a <= 24'h([0-9A-Fa-f]+)", function)]


def reference_rgb(payload):
    """Decode original pixels/palettes, independently of relocated RAM pointers."""
    paired = payload[0x7DF8] == 1
    result = bytearray()
    for y in range(400):
        field = y & 1 if paired else 0
        base = 39168 if field else 0
        palette_base = 71936 if field and len(payload) == 78336 else 32768
        row = y // 2
        assert payload[base + 0x7D00 + row] == 0, "Reference case must be plain 320-mode SCBs"
        palette = payload[palette_base + row * 32:palette_base + row * 32 + 32]
        colors = []
        for i in range(16):
            value = int.from_bytes(palette[2 * i:2 * i + 2], "little")
            colors.append(bytes((((value >> 8) & 15) * 16, ((value >> 4) & 15) * 16, (value & 15) * 16)))
        for value in payload[base + row * 160:base + row * 160 + 160]:
            result.extend(colors[15 - (value >> 4)] * 2)
            result.extend(colors[15 - (value & 15)] * 2)
    return bytes(result)


def main():
    from PIL import Image
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware-root", type=Path, required=True)
    parser.add_argument("--image", type=Path, default=DEMO / "dist/FATDOG_MAGIC.po")
    parser.add_argument("--output", type=Path, default=DEMO / "validation/brooks-capture")
    parser.add_argument("--reproduce-black", action="store_true")
    args = parser.parse_args()
    firmware = args.firmware_root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    executable = compile_harness(firmware, output)
    ranges = capture_ranges(firmware)
    assert ranges, "No capture ranges read from HDL"
    mask = bytearray(0x20000)
    for a, b in ranges:
        mask[a:b] = bytes([1]) * (b - a)
    (output / "capture.mask").write_bytes(mask)
    (output / "full.mask").write_bytes(bytes([1]) * len(mask))
    cases = []
    files = raw_files(args.image)
    for path, payload in files.items():
        if not path.startswith("BROOKS.SHR.3200/"):
            continue
        name = path.split("/")[1]
        (output / "image.bin").write_bytes(payload)
        expected = reference_rgb(payload)
        outputs = {}
        for kind in ("capture", "full") if args.reproduce_black else ("capture",):
            result = subprocess.check_output([str(executable), str(output), "image.bin",
                kind + ".mask", str(output)], text=True)
            raw = (output / "frame.bgra").read_bytes()
            image = Image.frombytes("RGBA", (640, 400), raw, "raw", "BGRA").convert("RGB")
            actual = image.tobytes()
            outputs[kind] = {"pixel_match": actual == expected,
                             "nonblack_pixels": int(re.search(r"nonblack=(\d+)", result)[1])}
            if not cases or len(payload) == 78336:
                image.save(output / (name + "-" + kind + ".png"))
            if not args.reproduce_black or kind == "full":
                assert actual == expected, f"{name}: Appletini pixels differ from source image ({kind})"
        if args.reproduce_black:
            assert not outputs["capture"]["pixel_match"], f"{name}: old failure was not reproduced"
        cases.append({"name": name, **outputs})
        print(f"PASS {name}: " + ("black-screen failure reproduced" if args.reproduce_black else "captured pixels match source"), flush=True)
    report = {"result": "PASS", "reproduced_old_failure": args.reproduce_black,
              "disk_sha256": hashlib.sha256(args.image.read_bytes()).hexdigest(),
              "capture_ranges": [[hex(a), hex(b - 1)] for a, b in ranges],
              "renderer_sha256": hashlib.sha256((firmware / "ps_sources/frontend/apple_cycle_renderer.c").read_bytes()).hexdigest(),
              "cases": cases, "physical_hardware_tested": False}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
