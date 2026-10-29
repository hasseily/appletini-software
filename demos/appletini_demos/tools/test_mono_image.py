#!/usr/bin/env python3
"""Run the real cc65 GIF decoder in sim65 against Pillow reference pixels."""
from pathlib import Path
import io
import random
import shutil
import subprocess
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "appletini_webserver"
BUILD = ROOT / "build" / "mono-image-tests"

HOST_HEADER = r"""
#include <stdint.h>
uint8_t mono_aux_get(uint16_t address);
void mono_aux_set(uint16_t address, uint8_t value);
void mono_gfx_pixel(uint16_t x, uint16_t y, uint8_t black);
"""
HOST = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mono_image.h"
static uint8_t aux[16384];
static uint8_t pixels[4096];
static uint8_t bytes[257];
extern uint8_t _GIFBSS_RUN__, _GIFBSS_SIZE__;
uint8_t mono_aux_get(uint16_t a) {
    if (a < 0x6000U || a >= 0xA000U) abort();
    return aux[a - 0x6000U];
}
void mono_aux_set(uint16_t a,uint8_t v) {
    if (a < 0x6000U || a >= 0xA000U) abort();
    aux[a - 0x6000U] = v;
}
void mono_gfx_pixel(uint16_t x,uint16_t y,uint8_t black) {
    if (x >= 560U || y >= 384U || black > 1U) abort();
    if (x < 64U && y < 64U) pixels[y * 64U + x] = black;
}
int main(int argc,char **argv) {
    FILE *f;
    uint16_t n, fragment;
    if (argc != 8) return 10;
    memset(&_GIFBSS_RUN__,0xA5,(uint16_t)&_GIFBSS_SIZE__);
    memset(aux,0x97,sizeof(aux));
    memset(pixels,2,sizeof(pixels));
    mono_image_begin(atoi(argv[3]),atoi(argv[4]),atoi(argv[5]),atoi(argv[6]));
    f = fopen(argv[1],"rb");
    if (!f) return 11;
    fragment = atoi(argv[7]);
    if (!fragment || fragment > sizeof(bytes)) return 12;
    while ((n = fread(bytes,1,fragment,f)) != 0U) {
        if (mono_image_feed(bytes,n) != MONO_IMAGE_MORE) break;
    }
    fclose(f);
    printf("%u %u %u %s\n",mono_image_finish(),mono_image_width(),
           mono_image_height(),mono_image_error() ? mono_image_error() : "OK");
    f = fopen(argv[2],"wb");
    if (!f) return 13;
    fwrite(pixels,1,sizeof(pixels),f);
    fclose(f);
    return 0;
}
"""
BAYER = (0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5)


def gif(image, **options):
    out = io.BytesIO()
    image.save(out, format="GIF", optimize=False, **options)
    return out.getvalue()


def local_palette(data):
    count = 2 << (data[10] & 7)
    palette_end = 13 + count * 3
    assert data[palette_end] == 0x2C
    header = data[:10] + bytes([data[10] & 0x7F]) + data[11:13]
    descriptor = data[palette_end:palette_end + 9]
    descriptor += bytes([data[palette_end + 9] | 0x80 | (data[10] & 7)])
    return header + descriptor + data[13:palette_end] + data[palette_end + 10:]


def small_gif(width, codes):
    # Explicit clear codes keep these small fixtures at three bits per code.
    bits = sum(value << (i * 3) for i, value in enumerate(codes))
    packed = bits.to_bytes((len(codes) * 3 + 7) // 8, "little")
    return (b"GIF89a" + bytes([width, 0, 1, 0, 0x80, 0, 0]) +
            bytes([0, 0, 0, 255, 255, 255]) +
            b"," + bytes([0, 0, 0, 0, width, 0, 1, 0, 0, 2, len(packed)]) +
            packed + b"\x00;")


def expected(data, dx=0, dy=0, max_w=560, max_h=384):
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
                threshold = BAYER[(yy & 3) * 4 + (xx & 3)] * 16 + 8
                result[yy * 64 + xx] = int(lum < threshold)
    return bytes(result)


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    cl65 = shutil.which("cl65")
    if not cl65:
        raise RuntimeError("Install cc65 and put cl65/sim65 in PATH")
    sim65 = shutil.which("sim65") or str(Path(cl65).with_name("sim65.exe"))
    (BUILD / "mono_image_host.h").write_text(HOST_HEADER)
    (BUILD / "host.c").write_text(HOST)
    config = (Path(cl65).resolve().parent.parent / "cfg" / "sim6502.cfg").read_text()
    config = config.replace("    BSS:", "    GIFBSS: load = MAIN, type = bss, define = yes;\n    BSS:")
    (BUILD / "test.cfg").write_text(config)
    binary = BUILD / "decoder.sim"
    subprocess.run([cl65, "-t", "sim6502", "-Oirs", "--warnings-as-errors",
                    "-C", str(BUILD / "test.cfg"), "-D", "MONO_IMAGE_HOST", "-I", str(BUILD), "-I", str(SOURCE),
                    "-o", str(binary), str(BUILD / "host.c"),
                    str(SOURCE / "mono_image.c")], check=True)
    rng = random.Random(1965)
    palette = [c for i in range(256) for c in ((i * 37) & 255, i, (i * 93) & 255)]
    random_image = Image.new("P", (64, 64))
    random_image.putpalette(palette)
    random_image.putdata([rng.randrange(256) for _ in range(4096)])
    flat = Image.new("P", (63, 31), 1)
    flat.putpalette([0, 0, 0, 255, 255, 255] + [0] * 762)
    stripes = Image.new("P", (19, 23))
    stripes.putpalette(palette)
    stripes.putdata([(x + y * 7) & 255 for y in range(23) for x in range(19)])
    alpha = stripes.copy()
    alpha.info["transparency"] = 7
    wide = Image.new("P", (701, 5))
    wide.putpalette(palette)
    wide.putdata([(x * 7 + y * 13) & 255 for y in range(5) for x in range(701)])
    cases = [
        ("random-12bit", gif(random_image, interlace=False), 0, 0),
        ("interlaced", gif(stripes, interlace=True), 0, 0),
        ("flat-kwkwk", gif(flat, interlace=False), 0, 0),
        ("transparent", gif(alpha, interlace=False, transparency=7), 2, 3),
        ("negative-clip", gif(stripes, interlace=False), -8, -5),
        ("right-bottom-clip", gif(stripes, interlace=False), 550, 375),
        ("local-palette", local_palette(gif(random_image, interlace=False)), 0, 0),
        ("repeated-clear", small_gif(2, [4, 0, 4, 1, 5]), 0, 0),
        ("wide-original", gif(wide, interlace=False), 0, 0),
    ]
    passed = 0
    cases = [case + (560, 384) for case in cases]
    cases += [("scaled", gif(random_image), 3, 5, 23, 19),
              ("scaled-interlace", gif(stripes, interlace=True), 2, 3, 11, 17)]
    for name, data, dx, dy, mw, mh in cases:
        for fragment in (1, 7, 257):
            source = BUILD / f"{name}.gif"
            output = BUILD / "pixels.bin"
            source.write_bytes(data)
            result = subprocess.run([sim65, str(binary), str(source), str(output),
                                     str(dx), str(dy), str(mw), str(mh), str(fragment)],
                                    check=True, capture_output=True, text=True)
            if not result.stdout.startswith("1 "):
                raise AssertionError((name, fragment, result.stdout, result.stderr))
            if output.read_bytes() != expected(data, dx, dy, mw, mh):
                raise AssertionError((name, fragment, "pixel mismatch"))
            passed += 1
    good = cases[0][1]
    malformed = [
        ("signature", b"NOTGIF" + good[6:], 560, 384),
        ("truncated-header", good[:11], 560, 384),
        ("truncated-data", good[:-9], 560, 384),
        ("oversized", good[:6] + bytes([1, 16]) + good[8:], 560, 384),
        ("bad-box", good, 561, 384),
        ("bad-lzw", small_gif(1, [4, 6, 5]), 560, 384),
        ("too-many-pixels", small_gif(1, [4, 0, 4, 1, 5]), 560, 384),
        ("too-few-pixels", small_gif(2, [4, 0, 5]), 560, 384),
        ("bad-palette-index", small_gif(1, [4, 3, 5]), 560, 384),
    ]
    for name, data, width, height in malformed:
        source = BUILD / f"{name}.gif"
        output = BUILD / "pixels.bin"
        source.write_bytes(data)
        result = subprocess.run([sim65, str(binary), str(source), str(output),
                                 "0", "0", str(width), str(height), "1"],
                                check=True, capture_output=True, text=True)
        if not result.stdout.startswith("2 "):
            raise AssertionError((name, result.stdout))
        passed += 1
    print(f"PASS {passed} real-6502 GIF cases: LZW12, fragmentation, interlace, "
          "transparency, clipping, malformed and truncated input")


if __name__ == "__main__":
    main()
