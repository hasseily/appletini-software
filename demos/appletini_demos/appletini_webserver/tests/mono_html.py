#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compare actual 6502 page renders for HTML hidden/raw-text elements."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path

from mono_verify import ROOT
from mono_integration import warm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path,
                        default=ROOT / 'build' / 'mono-network')
    args = parser.parse_args()
    out = args.build.resolve()
    base = warm(out)
    url = 'https://fixture.test/hidden'
    visible = (b'<h1>Visible body</h1><p>Only this page text belongs here.</p>'
               b'<a href="next.html">Visible link</a>')
    fixtures = {
        'body-reference': b'<html><body>' + visible + b'</body></html>',
        'nested-head': (
            b'<html><head><title>HIDDEN TITLE</title>'
            b'<style>HIDDEN STYLE</style>HIDDEN AFTER STYLE'
            b'<script>HIDDEN SCRIPT</script>HIDDEN AFTER SCRIPT'
            b'</head><body>' + visible + b'</body></html>'),
        'raw-script-operators': (
            b'<html><head><script>var less = 1 < 2; var quote = " > ";'
            b'var markup = "<a href=\'hidden.html\'>HIDDEN LINK</a>";'
            b'</script>HIDDEN AFTER SCRIPT</head><body>' + visible +
            b'</body></html>'),
        'raw-style-operators': (
            b'<html><body><style>.x::before { content: "<hidden> >"; }'
            b'</style><script>var less = 1 < 2;</script>' + visible +
            b'</body></html>'),
        'uppercase-head': (
            b'<HTML><HEAD><STYLE>HIDDEN STYLE</STYLE>HIDDEN HEAD'
            b'<SCRIPT>var less = 1 < 2;</SCRIPT></HEAD><BODY>' + visible +
            b'</BODY></HTML>'),
    }
    cases = []
    expected = None
    for name, body in fixtures.items():
        target = deepcopy(base)
        target.input = list(('g' + url + '\rq').encode())
        target.capture_at = {len(target.input) - 1: 'html-' + name}
        target.keyboard_calls = 0
        target.captures = []
        target.memory.fixtures = {url: ('text/html; charset=utf-8', body)}
        first = target.steps
        target.run(first + 30_000_000)
        assert target.memory.requests == [url], target.memory.requests
        assert not target.opened
        capture = target.captures[-1]
        if expected is None:
            expected = capture['sha256']
        assert capture['sha256'] == expected, (name, capture)
        cases.append({'case': name, 'fixture_bytes': len(body),
                      'instructions': target.steps - first, 'capture': capture})
    report = {'model': 'actual NMOS6502 HTTP client and browser renderer',
              'board_evidence': False,
              'program_sha256': hashlib.sha256((out / 'A2MONO.bin').read_bytes()).hexdigest(),
              'cases': cases}
    (out / 'html-hidden.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
