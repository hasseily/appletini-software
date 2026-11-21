#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Form links written by the card's page service: typed fields, URL
encoding, GET and POST, and Escape. The model serves filtered pages."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
from mono_verify import ROOT
from mono_integration import warm

BASE = 'https://fixture.test/'
FORMS = (b'<h1>Forms</h1>'
         b'<a href="https://fixture.test/search?hl=en&q=%s">[Form: q]</a><br>'
         b'<a href="post:https://fixture.test/login user=%s&pw=%s&t=1">[Form: user, pw]</a><br>'
         b'<a href="post:https://fixture.test/vote choice=2">[Send form]</a>')


def fixtures():
    done = b'<h1>Result page</h1><a href="/forms">back</a>'
    return {BASE + 'forms': ('text/html', FORMS),
            BASE + 'search?hl=en&q=apple+ii%2B': ('text/html', done),
            BASE + 'search?hl=en&q=': ('text/html', done),
            BASE + 'login': ('text/html', done, BASE + 'welcome'),
            BASE + 'vote': ('text/html', done)}


def run(base, keys, case):
    target = deepcopy(base)
    target.memory.capabilities = 127            # with the page filter
    target.memory.fixtures = fixtures()
    target.input = list(keys)
    target.capture_at = {}
    target.keyboard_calls = 0
    target.captures = []
    target.run(target.steps + 60_000_000)
    memory = target.memory
    assert not target.opened, case
    assert not memory.ramrd and not memory.ramwrt and memory.bank == 0, case
    return memory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=ROOT / 'build' / 'tinibrowser')
    args = parser.parse_args()
    base = warm(args.build.resolve())
    go = b'ghttps://fixture.test/forms\r'
    report = []

    # GET form: one typed field, space and '+' encoded, then the result page.
    m = run(base, go + b'\rapple ii+\rq', 'get')
    assert m.requests == [BASE + 'forms', BASE + 'search?hl=en&q=apple+ii%2B'], m.requests
    # The browser learned the page capability at its start (model: none),
    # and again with the first request, so the second request uses it.
    assert m.flags == [2, 18] and not m.posts, (m.flags, m.posts)
    report.append({'case': 'get', 'requests': m.requests})

    # An empty field is legal.
    m = run(base, go + b'\r\rq', 'get-empty')
    assert m.requests[-1] == BASE + 'search?hl=en&q=', m.requests

    # Escape leaves the page and sends nothing.
    m = run(base, go + b'\rabc\x1b' + b'q', 'escape')
    assert m.requests == [BASE + 'forms'], m.requests

    # POST form: two typed fields; the body and the form content type.
    m = run(base, go + b'\t\rbob\rp&w=1\rq', 'post')
    assert m.requests == [BASE + 'forms', BASE + 'login'], m.requests
    assert m.flags == [2, 16], m.flags
    url, body, headers = m.posts[0]
    assert body == b'user=bob&pw=p%26w%3D1&t=1', body
    assert b'Content-Type: application/x-www-form-urlencoded\r\n' in headers, headers
    assert b'User-Agent: ' in headers
    report.append({'case': 'post', 'body': body.decode()})

    # POST form with no typed field goes at once.
    m = run(base, go + b'\t\t\rq', 'post-fixed')
    assert m.posts and m.posts[0][1] == b'choice=2', m.posts

    (args.build / 'forms.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS form links: GET and POST, typed fields, encoding, empty field, Escape')


if __name__ == '__main__':
    main()
