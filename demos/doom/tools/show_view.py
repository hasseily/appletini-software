#!/usr/bin/env python3
"""Render a view with the 6502 renderer and the reference, side by side.

    python3 tools/show_view.py --map E1M1 [--view X Y Z ANGLE] [--tic N]
                               [--no-things] [--no-weapon] [--extralight N]
                               [--fixed K] [--shaded] [--out view.png]

The program in BUILD (default build/rtrack, the renderer track's build; it is
not rebuilt here) is booted in the py65 test machine (tools/doomdbg.py), the
view goes into the render packet with the map's things as
tools/refrender.py's spawn_things places them (the 128 nearest to the eye,
nearest first, as the game sends them) and the pistol, render_frame runs,
and the PNG shows the 6502's view buffer on the left and
tools/refrender.py's on the right, each as the Appletini shows it (a game
pixel 4x4), with a third panel marking the pixels that differ (white).
The cycles of render_frame and the differing pixel count are printed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("RENDER_NO_MAKE", "1")

import refrender as R  # noqa: E402
import test_render_core as C  # noqa: E402
import test_render_masked as M  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--view", nargs=4, type=float, metavar=("X", "Y", "Z", "ANGLE"),
                    help="eye in map units (z absolute) and angle in degrees; "
                         "default: player 1's start")
    ap.add_argument("--tic", type=int, default=0)
    ap.add_argument("--extralight", type=int, default=0)
    ap.add_argument("--fixed", type=int, help="fixed colormap 0..15")
    ap.add_argument("--shaded", action="store_true", help="flat-shaded floors and ceilings")
    ap.add_argument("--no-things", action="store_true")
    ap.add_argument("--no-weapon", action="store_true")
    ap.add_argument("--out", default="view.png")
    ap.add_argument("--build", default=str(C.BUILD), help="the linked program's directory")
    a = ap.parse_args(argv)

    from PIL import Image, ImageDraw
    d = C.game_data(a.map)
    view = R.View.from_units(*a.view) if a.view else R.player_start(d)
    things = [] if a.no_things else M.packet_things(view, M.map_things(a.map, a.tic))
    psp = [] if a.no_weapon else [M.pistol(d)]
    sim = M.MaskedSim(Path(a.build))
    sim.set_scene(a.map, view, things, psp, a.tic, a.extralight, a.fixed, a.shaded)
    got, cycles = sim.render()
    want, st = M.reference(a.map, view, things, psp, a.tic, a.extralight, a.fixed, a.shaded)
    dd = C.diff(got, want)

    def image(buf):
        img = Image.new("RGB", (R.VIEW_W, R.VIEW_H))
        px = img.load()
        for x in range(R.VIEW_W):
            for y in range(R.VIEW_H):
                px[x, y] = d.rgb[buf[R.VIEW_H * x + y]]
        return img.resize((R.VIEW_W * 4, R.VIEW_H * 4), Image.NEAREST)

    marks = Image.new("RGB", (R.VIEW_W, R.VIEW_H))
    mp = marks.load()
    for x, y, _, _ in dd:
        mp[x, y] = (255, 255, 255)
    marks = marks.resize((R.VIEW_W * 4, R.VIEW_H * 4), Image.NEAREST)
    w, h = R.VIEW_W * 4, R.VIEW_H * 4
    out = Image.new("RGB", (3 * w + 16, h + 14), (40, 40, 40))
    for i, (img, label) in enumerate(((image(got), "6502"), (image(want), "reference"),
                                      (marks, f"{len(dd)} differ"))):
        out.paste(img, (i * (w + 8), 14))
        ImageDraw.Draw(out).text((i * (w + 8) + 2, 1), label, fill=(255, 255, 255))
    out.save(a.out)
    print(f"{a.map} {view!r}: {cycles:,} cycles, {len(dd)} pixels differ, "
          f"{st.get('vissprites', 0)} vissprites, {len(things)} things -> {a.out}")
    return 0 if not dd else 1


if __name__ == "__main__":
    sys.exit(main())
