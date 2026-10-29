#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise local anchor navigation in the compiled NMOS6502 browser."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from mono_verify import ROOT, framebuffer, fixture_gif
from mono_integration import warm
from mono_github import body_text

URL = 'https://fixture.test/docs/page?q=1'


def filler(count=32):
    return b''.join(b'<p>FILLER %02d</p>' % n for n in range(count))


def page(href, destination=b"<h2 id='destination'>DESTINATION VISIBLE</h2>"):
    return (b"<a href='" + href.encode() + b"'>JUMP</a><p>PAGE TOP</p>" +
            filler() + destination + b'<p>AFTER DESTINATION</p>')


def drive(base, keys, budget=30_000_000):
    """Run real keyboard input and stop at the next idle input call."""
    target = deepcopy(base)
    target.input = list(keys)
    target.keyboard_calls = 0
    target.capture_at = {}
    target.captures = []
    target.ui_hook = None
    before = target.steps
    try:
        target.run(before + budget)
    except AssertionError as error:
        if str(error) != 'browser requested unexpected extra input':
            raise
        assert target.cpu.pc == target.symbols['_cgetc']
    else:
        raise AssertionError('browser exited instead of waiting for input')
    assert not target.opened, 'overlay file left open'
    assert target.memory.bank == 0 and not target.memory.ramrd and not target.memory.ramwrt
    assert target.memory.intcxrom and not target.memory.selected
    return target


def load(base, body, url=URL, extra=None):
    target = deepcopy(base)
    parts = urlsplit(url)
    requested = urlunsplit((parts.scheme, parts.netloc, parts.path or '/', parts.query, ''))
    # The final response URL may omit the authority's empty path, including
    # after an HTTP redirect. Navigation must compare its canonical form.
    target.memory.fixtures = {requested: ('text/html; charset=utf-8', body, url)}
    if extra:
        target.memory.fixtures.update(extra)
    target = drive(target, ('g' + url + '\r').encode())
    assert target.memory.requests == [requested], target.memory.requests
    return target


def record(name, before, after):
    text = body_text(after)
    return {'case': name, 'requests': list(after.memory.requests),
            'navigation_instructions': after.steps - before.steps,
            'framebuffer_sha256': hashlib.sha256(framebuffer(after.memory)).hexdigest(),
            'visible_text': text}


def keyboard_case(base, name, href, destination=None, unchanged=False, url=URL):
    body = page(href) if destination is None else page(href, destination)
    target = load(base, body, url)
    if unchanged:
        target = drive(target, b' ')
    before = body_text(target)
    before_pixels = framebuffer(target.memory) if unchanged else None
    requests = list(target.memory.requests)
    assert 'DESTINATION VISIBLE' not in before
    result = drive(target, b'\r')
    assert result.memory.requests == requests, (name, result.memory.requests)
    text = body_text(result)
    if unchanged:
        assert text == before, (name, 'local fragment changed the viewport', text)
        assert framebuffer(result.memory) == before_pixels, (name, 'local fragment changed screen pixels')
    else:
        assert 'DESTINATION VISIBLE' in text, (name, text)
        assert 'PAGE TOP' not in text, (name, 'did not leave the first viewport')
    return record(name, target, result)


def top_case(base, href):
    url = 'https://fixture.test/top'
    body = b'<p>PAGE TOP</p>' + filler() + b"<a href='" + href.encode() + b"'>TOP LINK</a>"
    target = drive(load(base, body, url), b' ')
    assert 'PAGE TOP' not in body_text(target)
    result = drive(target, b'\r')
    assert result.memory.requests == [url]
    assert 'PAGE TOP' in body_text(result), body_text(result)
    return record('top-' + ('empty' if href == '#' else 'fallback'), target, result)


def precedence_case(base, duplicate=False):
    name = 'duplicate-id-first' if duplicate else 'id-before-legacy-name'
    first = b"<h2 id='same'>FIRST ID</h2>" if duplicate else b"<a name='same'></a><p>LEGACY NAME FIRST</p>"
    second = b"<h2 id='same'>SECOND ID</h2>" if duplicate else b"<h2 id='same'>ID PRIORITY</h2>"
    body = b"<a href='#same'>JUMP</a>" + filler() + first + filler() + second
    target = load(base, body)
    result = drive(target, b'\r')
    text = body_text(result)
    expected = 'FIRST ID' if duplicate else 'ID PRIORITY'
    excluded = 'SECOND ID' if duplicate else 'LEGACY NAME FIRST'
    assert expected in text and excluded not in text, (name, text)
    assert result.memory.requests == [URL]
    return record(name, target, result)


def different_query_case(base):
    other = 'https://fixture.test/docs/page?q=2'
    target = load(base, page('?q=2#destination'), extra={
        other: ('text/html', b'<h1>OTHER QUERY PAGE</h1>')})
    result = drive(target, b'\r')
    assert result.memory.requests == [URL, other], result.memory.requests
    assert 'OTHER QUERY PAGE' in body_text(result), body_text(result)
    return record('different-query-fetches', target, result)


def image_case(base):
    url = 'https://fixture.test/images'
    near, far = 'https://fixture.test/near.gif', 'https://fixture.test/far.gif'
    body = (b"<a href='#picture'>JUMP</a><img src='near.gif'>" + filler() +
            b"<img id='picture' src='far.gif'><p>IMAGE DESTINATION</p>")
    image = ('image/gif', fixture_gif(16, 8))
    target = load(base, body, url, {near: image, far: image})
    target = drive(target, b'i')
    assert target.memory.requests == [url, near], target.memory.requests
    result = drive(target, b'\r')
    assert result.memory.requests == [url, near, far], result.memory.requests
    assert 'IMAGE DESTINATION' in body_text(result), body_text(result)
    assert result.memory.requests.count(url) == 1, 'anchor reloaded the HTML'
    return record('enabled-images-survive-anchor-and-overlays', target, result)


def mouse_case(base):
    target = load(base, page('#destination'))
    before = target.steps
    target.memory.main[target.symbols['_mono_mouse_available']] = 1
    target.input = [0, ord('q')]
    target.keyboard_calls = 0
    target.capture_at = {}
    target.mouse_clicked = False

    def hook(run):
        pc = run.cpu.pc
        if pc == run.symbols['_mono_mouse_poll']:
            assert not run.mouse_clicked, 'unexpected repeated mouse click'
            for field, value in (('_mono_mouse_x', 2), ('_mono_mouse_y', 1),
                                 ('_mono_mouse_down', 1), ('_mono_mouse_pressed', 1)):
                run.memory.main[run.symbols[field]] = value
            run.mouse_clicked = True
            run.cpu.a, run.cpu.x = 3, 0
            run.rts()
            return True
        if pc == run.symbols['_kbhit']:
            sp, memory = run.cpu.sp, run.memory.main
            ret = memory[0x100 + ((sp + 1) & 255)] | memory[0x100 + ((sp + 2) & 255)] << 8
            run.cpu.a, run.cpu.x = int(run.mouse_clicked and 0x8B00 <= ret < 0xB700), 0
            run.rts()
            return True
        if pc == run.symbols['_mono_mouse_disable']:
            run.memory.main[run.symbols['_mono_mouse_available']] = 0
            run.cpu.a, run.cpu.x = 0, 0
            run.rts()
            return True
        return False

    target.ui_hook = hook
    target.run(before + 30_000_000)
    assert target.mouse_clicked and target.memory.requests == [URL]
    assert not target.opened
    assert 'DESTINATION VISIBLE' in body_text(target), body_text(target)
    return {'case': 'mouse-local-anchor', 'requests': target.memory.requests,
            'navigation_instructions': target.steps - before, 'visible_text': body_text(target)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=ROOT / 'build' / 'mono')
    parser.add_argument('--case', action='append', help='run only the named case, repeatable')
    args = parser.parse_args()
    out = args.build.resolve()
    program_sha256 = hashlib.sha256((out / 'A2MONO.bin').read_bytes()).hexdigest()
    base = warm(out)
    tests = [
        ('keyboard-id', lambda: keyboard_case(base, 'keyboard-id', '#destination')),
        ('legacy-name', lambda: keyboard_case(base, 'legacy-name', '#destination', b"<a name='destination'></a><p>DESTINATION VISIBLE</p>")),
        ('percent-space-plus', lambda: keyboard_case(base, 'percent-space-plus', '#Case%20%2B+', b"<h2 id='Case ++'>DESTINATION VISIBLE</h2>")),
        ('case-sensitive-id', lambda: keyboard_case(base, 'case-sensitive-id', '#case%20%2B+', b"<h2 id='Case ++'>DESTINATION VISIBLE</h2>", True)),
        ('html-attribute-amp', lambda: keyboard_case(base, 'html-attribute-amp', '#amp%26key', b"<h2 id='amp&amp;key'>DESTINATION VISIBLE</h2>")),
        ('utf8-percent-bytes', lambda: keyboard_case(base, 'utf8-percent-bytes', '#%E2%98%83', b"<h2 id='\xe2\x98\x83'>DESTINATION VISIBLE</h2>")),
        ('unknown-fragment', lambda: keyboard_case(base, 'unknown-fragment', '#unknown', unchanged=True)),
        ('trailing-percent', lambda: keyboard_case(base, 'trailing-percent', '#bad%', unchanged=True)),
        ('short-percent', lambda: keyboard_case(base, 'short-percent', '#bad%2', unchanged=True)),
        ('invalid-percent', lambda: keyboard_case(base, 'invalid-percent', '#bad%GG', unchanged=True)),
        ('nul-percent', lambda: keyboard_case(base, 'nul-percent', '#%00destination', unchanged=True)),
        ('absolute-same-query', lambda: keyboard_case(base, 'absolute-same-query', URL + '#destination')),
        ('relative-same-query', lambda: keyboard_case(base, 'relative-same-query', 'page?q=1#destination')),
        ('query-only-same', lambda: keyboard_case(base, 'query-only-same', '?q=1#destination')),
        ('root-without-slash', lambda: keyboard_case(base, 'root-without-slash', '/#destination', url='https://fixture.test')),
        ('root-query-without-slash', lambda: keyboard_case(base, 'root-query-without-slash', '/?q=1#destination', url='https://fixture.test?q=1')),
        ('top-empty', lambda: top_case(base, '#')),
        ('top-fallback', lambda: top_case(base, '#top')),
        ('id-before-legacy-name', lambda: precedence_case(base)),
        ('duplicate-id-first', lambda: precedence_case(base, True)),
        ('different-query-fetches', lambda: different_query_case(base)),
        ('enabled-images-survive-anchor-and-overlays', lambda: image_case(base)),
        ('mouse-local-anchor', lambda: mouse_case(base)),
    ]
    reports, failures = [], []
    for name, test in tests:
        if args.case and name not in args.case:
            continue
        try:
            result = test()
        except AssertionError as error:
            result = {'case': name, 'error': str(error)}
            failures.append(name)
            print('FAIL', name, str(error), flush=True)
        else:
            print('PASS', name, 'requests', len(result['requests']), flush=True)
        reports.append(result)
    assert reports, 'no selected test cases'
    report = {'model': 'actual NMOS6502 browser; modeled HTTP FIFO/ProDOS; synthesized mouse event',
              'board_evidence': False,
              'program_sha256': program_sha256,
              'cases': reports, 'failed': failures}
    (out / 'anchor-navigation.json').write_text(json.dumps(report, indent=2) + '\n')
    assert not failures, failures
    print('PASS', len(reports), 'real-6502 anchor cases; local navigation does not reload HTML')


if __name__ == '__main__':
    main()
