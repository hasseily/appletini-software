#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pictures in the text flow, at the display size that the page gives."""
from copy import deepcopy
import argparse
from pathlib import Path
from mono_verify import ROOT, fixture_gif, framebuffer, save_capture
from mono_integration import warm
from mono_github import body_text

BASE = 'https://fixture.test/'
PAGE = (b'<p>Left <img src="a.gif" w=28 h=16> right text<br>'
        b'next line <img src="b.gif"> end<br>'
        + b'filler ' * 9 + b'<img src="c.gif" w=140 h=8> wrapped')


def white(memory, x, y):
    pixels = framebuffer(memory)
    return (pixels[y * 70 + x // 8] >> (7 - (x & 7))) & 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=ROOT / 'build' / 'tinibrowser')
    args = parser.parse_args()
    out = args.build.resolve()
    target = deepcopy(warm(out))
    target.memory.fixtures = {
        BASE + 'inline': ('text/html', PAGE),
        BASE + 'a.gif': ('image/gif', fixture_gif(56, 32)),     # larger than its display size
        BASE + 'b.gif': ('image/gif', fixture_gif(21, 24)),     # no display size: natural size
        BASE + 'c.gif': ('image/gif', fixture_gif(140, 8))}
    target.input = list(b'ghttps://fixture.test/inline\r')
    target.capture_at = {}
    target.keyboard_calls = 0
    target.captures = []
    try:
        target.run(target.steps + 60_000_000)
    except AssertionError as error:
        assert str(error) == 'browser requested unexpected extra input', error
    memory = target.memory
    save_capture(out / 'inline.png', memory)
    # The browser asks the card for the display size of the page, or for
    # the largest box when the page gives none.
    assert memory.picture_requests == [BASE + 'a.gif', BASE + 'b.gif', BASE + 'c.gif'], memory.picture_requests
    assert memory.picture_boxes == [(28, 16), (546, 240), (140, 8)], memory.picture_boxes

    lines = body_text(target).split('\n')
    # Row 0: "Left", the 28 x 16 picture (4 columns, 2 rows), then the text
    # goes on at its right, on its last row.
    # (The text reader shows picture cells as '?'.)
    assert lines[0].startswith(' LEFT ') and 'RIGHT' not in lines[0], lines[:6]
    assert lines[1].index('RIGHT TEXT') == 11, lines[1]
    # The picture cells hold pixels: columns 6..9 of content rows 0 and 1.
    lit = sum(white(memory, x, y) for x in range(6 * 7, 10 * 7) for y in range(8, 24))
    assert 0 < lit < 28 * 16, lit
    # Second line: a 21 x 24 picture (3 columns, 3 rows) after "next line".
    assert lines[2].startswith(' NEXT LINE ') and 'END' not in lines[2], lines[:6]
    assert lines[4].index('END') == 15, lines[:6]
    # Third paragraph: the 20-column picture does not fit after the filler
    # text, so it starts a new line; "wrapped" follows it on that line.
    assert lines[5].startswith(' FILLER') and 'WRAPPED' not in lines[5], lines[5:8]
    assert lines[6].index('WRAPPED') == 22, lines[5:8]
    print('PASS inline pictures: display size from the page, text flow to the right, wrap')


if __name__ == '__main__':
    main()
