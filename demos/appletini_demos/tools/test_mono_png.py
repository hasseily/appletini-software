#!/usr/bin/env python3
"""Execute the native PNG decoder as real 6502 code and compare with Pillow."""
from pathlib import Path
import io
import random
import shutil
import struct
import subprocess
import zlib

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "appletini_webserver"
BUILD = ROOT / "build" / "mono-png-tests"
HOST_HEADER = r"""
#include <stdint.h>
uint8_t mono_bank_get(uint8_t bank,uint16_t address);
void mono_bank_set(uint8_t bank,uint16_t address,uint8_t value);
void mono_gfx_pixel(uint16_t x,uint16_t y,uint8_t black);
"""
HOST = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mono_png.h"
static uint8_t aux[40960U], pixels[4096];
static FILE *source;
static uint16_t position;
extern uint8_t _PNGBSS_RUN__, _PNGBSS_SIZE__;
uint8_t mono_bank_get(uint8_t bank,uint16_t a) {
    if (bank != 1 || a < 0x2000U || a >= 0xC000U) abort();
    return aux[a - 0x2000U];
}
void mono_bank_set(uint8_t bank,uint16_t a,uint8_t v) {
    if (bank != 1 || a < 0x2000U || a >= 0xC000U) abort();
    aux[a - 0x2000U] = v;
}
void mono_gfx_pixel(uint16_t x,uint16_t y,uint8_t black) {
    if (x >= 560U || y >= 384U || black > 1U) abort();
    if (x < 64U && y < 64U) pixels[y * 64U + x] = black;
}
uint8_t mono_source_get(uint16_t at) {
    if (at != position) abort();
    ++position;
    return fgetc(source);
}
int main(int argc,char **argv) {
    FILE *f;
    uint8_t result;
    if (argc != 8) return 10;
    memset(&_PNGBSS_RUN__,0xA5,(uint16_t)&_PNGBSS_SIZE__);
    memset(aux,0x97,sizeof(aux));
    memset(pixels,2,sizeof(pixels));
    source = fopen(argv[1],"rb");
    if (!source) return 11;
    result = mono_png_decode(atoi(argv[3]),atoi(argv[4]),atoi(argv[5]),
                             atoi(argv[6]),atoi(argv[7]));
    printf("%u %u %u %s\n",result,mono_png_width(),mono_png_height(),
           mono_png_error() ? mono_png_error() : "OK");
    fclose(source);
    f = fopen(argv[2],"wb");
    if (!f) return 13;
    fwrite(pixels,1,sizeof(pixels),f);
    fclose(f);
    return 0;
}
"""
BAYER = (0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5)


def chunk(name, data):
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))


def paeth(a, b, c):
    p = a + b - c
    aa, bb, cc = abs(p - a), abs(p - b), abs(p - c)
    return a if aa <= bb and aa <= cc else b if bb <= cc else c


def png(width, height, color, depth, rows, *, palette=None, transparency=None,
        filtering="all", level=6, strategy=zlib.Z_DEFAULT_STRATEGY,
        split=257, adler_bad=False, interlace=0):
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    raw = bytearray()
    previous = bytes(len(rows[0]))
    for y, row in enumerate(rows):
        mode = y % 5 if filtering == "all" else filtering
        filtered = bytearray()
        for x, value in enumerate(row):
            a, b, c = row[x - bpp] if x >= bpp else 0, previous[x], previous[x - bpp] if x >= bpp else 0
            predictor = (0, a, b, (a + b) // 2, paeth(a, b, c))[mode]
            filtered.append((value - predictor) & 255)
        raw.append(mode)
        raw.extend(filtered)
        previous = row
    compressor = zlib.compressobj(level, zlib.DEFLATED, 15, strategy=strategy)
    encoded = compressor.compress(bytes(raw)) + compressor.flush()
    if adler_bad:
        encoded = encoded[:-1] + bytes([encoded[-1] ^ 1])
    output = b"\x89PNG\r\n\x1a\n"
    output += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, interlace))
    if palette is not None:
        output += chunk(b"PLTE", bytes(palette))
    if transparency is not None:
        output += chunk(b"tRNS", bytes(transparency))
    output += b"".join(chunk(b"IDAT", encoded[i:i + split]) for i in range(0, len(encoded), split))
    return output + chunk(b"IEND", b"")


def expected(data, dx, dy, max_w, max_h):
    image = Image.open(io.BytesIO(data)).convert("RGBA")
    w, h = image.size
    out_w, out_h = w, h
    if w > max_w or h > max_h:
        out_w, out_h = max_w, h * max_w // w
        if out_h > max_h:
            out_w, out_h = w * max_h // h, max_h
        out_w, out_h = max(1, out_w), max(1, out_h)
    result = bytearray([2] * 4096)
    for y in range(out_h):
        for x in range(out_w):
            xx, yy = x + dx, y + dy
            if not (0 <= xx < 64 and 0 <= yy < 64):
                continue
            r, g, b, a = image.getpixel((x * w // out_w, y * h // out_h))
            if a:
                lum = (r * 77 + g * 150 + b * 29 + 128) >> 8
                if a != 255:
                    lum = 255 - (((255 - lum) * a + 127) // 255)
                threshold = BAYER[(yy & 3) * 4 + (xx & 3)] * 16 + 8
                result[yy * 64 + xx] = int(lum < threshold)
    return out_w, out_h, bytes(result)


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    cl65 = shutil.which("cl65")
    if not cl65:
        raise RuntimeError("Install cc65 and put cl65/sim65 in PATH")
    sim65 = shutil.which("sim65") or str(Path(cl65).with_name("sim65.exe"))
    (BUILD / "mono_png_host.h").write_text(HOST_HEADER)
    (BUILD / "host.c").write_text(HOST)
    config = (Path(cl65).resolve().parent.parent / "cfg" / "sim6502.cfg").read_text()
    config = config.replace("    BSS:", "    PNGBSS: load = MAIN, type = bss, define = yes;\n    BSS:")
    (BUILD / "test.cfg").write_text(config)
    binary = BUILD / "decoder.sim"
    subprocess.run([cl65, "-t", "sim6502", "-Oirs", "--warnings-as-errors",
                    "-C", str(BUILD / "test.cfg"), "-D", "MONO_PNG_HOST", "-I", str(BUILD), "-I", str(SOURCE),
                    "-o", str(binary), str(BUILD / "host.c"),
                    str(SOURCE / "mono_png.c")], check=True)
    rng = random.Random(6502)
    w, h = 31, 23
    rgb = [bytes((x * 23 + y * 71 + c * 59) & 255 for x in range(w) for c in range(3)) for y in range(h)]
    rgba = [bytes(v for x in range(w) for v in ((x * 23) & 255, (y * 31) & 255, (x * 11 + y * 7) & 255, (x % 5) * 63)) for y in range(h)]
    gray = [bytes((x * 7 + y * 13) & 255 for x in range(w)) for y in range(h)]
    ga = [bytes(v for x in range(w) for v in ((x * 7 + y * 13) & 255, (x % 5) * 63)) for y in range(h)]
    cases = [
        ("rgb-dynamic", png(w, h, 2, 8, rgb), 0, 0, 560, 384),
        ("rgb-fixed", png(w, h, 2, 8, rgb, strategy=zlib.Z_FIXED), 0, 0, 560, 384),
        ("rgb-stored", png(w, h, 2, 8, rgb, level=0), 0, 0, 560, 384),
        ("rgb-split-idat", png(w, h, 2, 8, rgb, split=1), 0, 0, 560, 384),
        ("rgba", png(w, h, 6, 8, rgba), 0, 0, 560, 384),
        ("gray", png(w, h, 0, 8, gray), 0, 0, 560, 384),
        ("gray-alpha", png(w, h, 4, 8, ga), 0, 0, 560, 384),
        ("scaled", png(w, h, 2, 8, rgb), 3, 5, 13, 11),
        ("clip", png(w, h, 2, 8, rgb), -8, -5, 560, 384),
    ]
    for depth in (1, 2, 4, 8):
        count = 1 << depth
        packed = []
        for y in range(h):
            row = bytearray((w * depth + 7) // 8)
            for x in range(w):
                row[(x * depth) // 8] |= ((x + y) % count) << (8 - depth - ((x * depth) & 7))
            packed.append(bytes(row))
        palette = [v for i in range(count) for v in ((i * 37) & 255, (i * 71) & 255, (i * 13) & 255)]
        cases.append((f"indexed{depth}", png(w, h, 3, depth, packed, palette=palette,
                                              transparency=[0] + [i * 255 // (count - 1) for i in range(1, count)]), 0, 0, 560, 384))
        cases.append((f"gray{depth}", png(w, h, 0, depth, packed), 0, 0, 560, 384))
    # More than 32 KiB of inflated data exercises the circular history window.
    repeated = [bytes(rng.randrange(256) for _ in range(2048)) for _ in range(8)]
    cases.append(("window-wrap", png(2048, 32, 0, 8, repeated * 4, filtering=0), 0, 0, 560, 384))
    passed = 0
    for name, data, dx, dy, mw, mh in cases:
        source = BUILD / f"{name}.png"
        output = BUILD / "pixels.bin"
        source.write_bytes(data)
        result = subprocess.run([sim65, str(binary), str(source), str(output),
                                 str(dx), str(dy), str(mw), str(mh), str(len(data))],
                                check=True, capture_output=True, text=True)
        ew, eh, pixels = expected(data, dx, dy, mw, mh)
        if not result.stdout.startswith(f"1 {ew} {eh} "):
            raise AssertionError((name, result.stdout, result.stderr))
        actual = output.read_bytes()
        if actual != pixels:
            mismatch = next(i for i, (a, b) in enumerate(zip(actual, pixels)) if a != b)
            raise AssertionError((name, "pixel mismatch", mismatch % 64, mismatch // 64,
                                  actual[mismatch], pixels[mismatch]))
        passed += 1
    good = cases[0][1]
    malformed = [
        ("signature", b"NOTPNG!!" + good[8:]),
        ("header-crc", good[:29] + bytes([good[29] ^ 1]) + good[30:]),
        ("truncated", good[:-3]),
        ("bad-adler", png(w, h, 2, 8, rgb, adler_bad=True)),
        ("interlace-reject", png(w, h, 2, 8, rgb, interlace=1)),
        ("bad-row", png(4096, 1, 6, 8, [bytes(16384)])),
    ]
    for name, data in malformed:
        source = BUILD / f"{name}.png"
        source.write_bytes(data)
        result = subprocess.run([sim65, str(binary), str(source), str(BUILD / "pixels.bin"),
                                 "0", "0", "560", "384", str(len(data))],
                                check=True, capture_output=True, text=True)
        if not result.stdout.startswith("0 "):
            raise AssertionError((name, result.stdout))
        passed += 1
    print(f"PASS {passed} real-6502 PNG cases: stored/fixed/dynamic DEFLATE, "
          "32KB window, all filters, indexed/gray1/2/4/8, RGB/GA/RGBA, alpha, "
          "scaling, clipping, split IDAT, CRC/Adler and malformed input")


if __name__ == "__main__":
    main()
