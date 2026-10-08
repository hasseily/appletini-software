# SPDX-License-Identifier: GPL-2.0-only
"""Loopback-only browser display and inputs for the same headless machine."""
import base64
import copy
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, urlsplit
import webbrowser

from cli import Machine, PROFILES, integer, output
from controls import events
from video import frame_png


class PlaySession:
    """Own the current machine and persistent end/restart lifecycle."""
    def __init__(self, machine, args):
        self.machine = machine
        self.args = copy.deepcopy(args)
        self.generation = 0
        self.terminal = None

    def release(self):
        for item in events([]) + [dict(kind='release', x=0, y=0),
                                   dict(kind='buttons', x=0, y=0),
                                   dict(kind='oa', x=0, y=0), dict(kind='ca', x=0, y=0)]:
            self.machine.check(self.machine.lib.ap_input(self.machine.handle,
                               item['kind'].encode(), item['x'], item['y']))

    def restart(self, profile=None):
        args = copy.deepcopy(self.args)
        if profile is not None:
            if not isinstance(profile, str) or profile not in PROFILES:
                raise ValueError('unknown acceleration profile')
            args.profile = profile
        if getattr(args, 'wav', None):
            # Preserve the completed recording, including earlier restarts.
            source = Path(args.wav).expanduser().resolve()
            number = self.generation + 1
            while True:
                candidate = source.with_name(source.stem + '-restart-' + str(number) +
                                             (source.suffix or '.wav'))
                if not candidate.exists():
                    args.wav = str(candidate)
                    break
                number += 1
        # Construct before replacing the current session: a missing asset or
        # build error leaves the old machine and its terminal card intact.
        replacement = Machine(args)
        previous = self.machine
        self.machine = replacement
        self.args.profile = args.profile
        self.generation += 1
        self.terminal = None
        previous.close()

    def acceleration(self, profile, restart=False):
        if not isinstance(profile, str) or profile not in PROFILES:
            raise ValueError('unknown acceleration profile')
        if not isinstance(restart, bool):
            raise ValueError('restart must be true or false')
        if restart:
            self.restart(profile)
            return True
        self.machine.acceleration(profile)
        self.args.profile = profile
        return False

    def frame(self, frames=0, *, restarted=False):
        machine = self.machine
        if self.terminal:
            result = {'reason': self.terminal['reason'], 'state': machine.state()}
        else:
            result = machine.run(frames=frames) if frames else {
                'reason': 'restarted' if restarted else 'paused', 'state': machine.state()}
            reason = result['reason']
            if reason in ('stp', 'halt') or (reason == 'quit' and not self.args.boot):
                self.release()
                if reason == 'quit':
                    title = 'Program exited'
                    message = 'The program has exited. Restart to run it again, or stop this session.'
                elif reason == 'stp':
                    title, message = 'Program stopped', 'The processor stopped. Restart to run the program again.'
                else:
                    title, message = 'Emulator stopped', result['state']['halt'] or 'The machine stopped with an error.'
                self.terminal = {'reason': reason, 'title': title, 'message': message, 'restart': True}
        reply = {'ok': True, 'machine': machine.metadata(), **result,
                 'session': self.generation, 'terminal': self.terminal}
        if machine.audio:
            pcm = machine.audio.take()
            if self.terminal:
                pcm = b''
            reply['audio'] = {'sample_rate': 48000, 'channels': 2,
                              'format': 's16le', 'frames': len(pcm) // 4,
                              'pcm': base64.b64encode(pcm).decode('ascii')}
        if not self.terminal:
            try:
                png, info = frame_png(machine)
                reply['image'] = base64.b64encode(png).decode('ascii')
                reply['video'] = info
            except ValueError as exc:
                reply['video_error'] = str(exc)
        return reply

    def close(self):
        self.machine.close()


def serve(machine, args):
    token = secrets.token_urlsafe(32)
    session = PlaySession(machine, args)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def send(self, status, data, content_type):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy',
                             "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                             "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                             "connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def valid(self):
            expected = '127.0.0.1:%d' % self.server.server_port
            supplied = parse_qs(urlsplit(self.path).query).get('token', [''])[0]
            return (self.headers.get('Host') == expected and
                    self.headers.get('Origin', 'http://' + expected) == 'http://' + expected and
                    secrets.compare_digest(supplied.encode(), token.encode()))

        def do_GET(self):
            if not self.valid():
                self.send(403, b'Forbidden', 'text/plain')
            elif urlsplit(self.path).path == '/':
                self.send(200, (Path(__file__).with_name('play.html')).read_bytes(), 'text/html; charset=utf-8')
            else:
                self.send(404, b'Not found', 'text/plain')

        def do_POST(self):
            if not self.valid() or urlsplit(self.path).path not in ('/frame', '/stop', '/restart', '/acceleration'):
                self.send(403, b'Forbidden', 'text/plain')
                return
            try:
                size = integer(self.headers.get('Content-Length', '0'), 1, 65536)
                req = json.loads(self.rfile.read(size))
                if urlsplit(self.path).path == '/acceleration':
                    if not isinstance(req, dict) or set(req) - {'profile', 'restart'} or 'profile' not in req:
                        raise ValueError('invalid acceleration request')
                    restarted = session.acceleration(req['profile'], req.get('restart', False))
                    reply = session.frame(restarted=restarted)
                    reply['acceleration_restarted'] = restarted
                    self.send(200, json.dumps(reply).encode(), 'application/json')
                    return
                if not isinstance(req, dict) or set(req) - {'frames', 'keys', 'inputs'}:
                    raise ValueError('invalid frame request')
                frames = integer(req.get('frames', 0), 0, 6)
                inputs = req.get('inputs', [])
                if not isinstance(inputs, list) or len(inputs) > 128:
                    raise ValueError('at most 128 input events per request')
                validated = []
                for item in inputs:
                    if not isinstance(item, dict) or set(item) - {'kind', 'x', 'y'}:
                        raise ValueError('invalid input event')
                    if item.get('kind') not in ('hold', 'release', 'key', 'mouse', 'mouse-to', 'buttons', 'oa', 'ca'):
                        raise ValueError('invalid input kind')
                    kind = item['kind']
                    x = integer(item.get('x', 0), -32768, 32767)
                    y = integer(item.get('y', 0), -32768, 32767)
                    if kind in ('hold', 'key'):
                        integer(x, 0, 255)
                    if kind in ('buttons', 'oa', 'ca'):
                        integer(x, 0, 1)
                    if kind == 'buttons':
                        integer(y, 0, 1)
                    validated.append({'kind': kind, 'x': x, 'y': y})
                if 'keys' in req:
                    mapped = events(req['keys'])
                else:
                    mapped = []
                path = urlsplit(self.path).path
                if path == '/restart':
                    if frames:
                        raise ValueError('restart does not accept a frame budget')
                    session.restart()
                    reply = session.frame(restarted=True)
                elif path == '/stop':
                    session.release()
                    self.send(200, b'{"ok":true}', 'application/json')
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                else:
                    machine = session.machine
                    # A completed session remains frozen until explicit Restart.
                    if not session.terminal:
                        for item in mapped + validated:
                            machine.check(machine.lib.ap_input(machine.handle, item['kind'].encode(),
                                          integer(item.get('x', 0), -32768, 32767),
                                          integer(item.get('y', 0), -32768, 32767)))
                    reply = session.frame(frames)
                self.send(200, json.dumps(reply).encode(), 'application/json')
            except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
                self.send(400, json.dumps({'ok': False, 'error': str(exc)}).encode(), 'application/json')

    server = HTTPServer(('127.0.0.1', args.port), Handler)
    server.timeout = 1
    url = 'http://127.0.0.1:%d/?token=%s' % (server.server_port, token)
    output({'url': url, 'machine': machine.metadata(), 'mode': 'play',
            'controls': 'QWE/ASD/ZXC; Space/J/K; Enter/Tab; U/I/O'})
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        session.close()
    return 0
