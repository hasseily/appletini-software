"""Exercise the loopback play endpoint against a real native machine."""

from __future__ import annotations

from contextlib import contextmanager
import http.client
import json
from pathlib import Path
import select
import subprocess
import sys
import wave
import tempfile
import unittest
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def session(code="4c0020", *, extra=()):
    with tempfile.TemporaryFile(mode="w+") as stderr:
        process = subprocess.Popen(
            [str(ROOT / "emulator" / "appletini"), "play", "--hex", code, "--no-open", *extra],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=stderr, text=True,
        )
        try:
            ready, _, _ = select.select([process.stdout], [], [], 30)
            if not ready:
                raise AssertionError("play did not publish a URL within 30 seconds")
            line = process.stdout.readline()
            if not line:
                stderr.seek(0)
                raise AssertionError("play exited before publishing a URL: " + stderr.read())
            announcement = json.loads(line)
            if not announcement.get("ok") or "url" not in announcement:
                raise AssertionError(f"play failed: {announcement}")
            yield process, urlsplit(announcement["url"]), announcement
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            process.stdout.close()


def request(url, method="GET", path="/", body=None, *, query=None, headers=None):
    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=10)
    query = url.query if query is None else query
    target = path + ("?" + query if query else "")
    data = json.dumps(body).encode() if body is not None else None
    headers = dict(headers or {})
    if data is not None:
        headers.setdefault("Content-Type", "application/json")
    try:
        connection.request(method, target, body=data, headers=headers)
        response = connection.getresponse()
        return response.status, response.read(), dict(response.getheaders())
    finally:
        connection.close()


class AppletiniPlayTests(unittest.TestCase):
    def test_local_page_requires_token_and_rejects_foreign_origin(self):
        with session() as (_, url, announcement):
            self.assertEqual(url.hostname, "127.0.0.1")
            self.assertEqual(announcement["mode"], "play")
            status, html, headers = request(url)
            self.assertEqual(status, 200)
            self.assertIn(b"Laptop joystick", html)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(request(url, query="token=wrong")[0], 403)
            self.assertEqual(request(url, query="token=%C3%A9")[0], 403)
            self.assertEqual(request(url, query="")[0], 403)
            self.assertEqual(request(url, headers={"Origin": "https://example.com"})[0], 403)
            self.assertEqual(request(url, path="/state")[0], 404)

    def test_frame_runs_guest_and_applies_then_releases_controller_keys(self):
        # Repeatedly read Apple joystick button 0 into A.
        with session("ad61c04c0020") as (_, url, _):
            status, data, _ = request(url, "POST", "/frame", {"frames": 0, "keys": []})
            self.assertEqual(status, 200, data)
            paused = json.loads(data)
            self.assertEqual(paused["reason"], "paused")
            self.assertEqual(paused["state"]["ticks"], 0)
            self.assertIn("image", paused)
            self.assertEqual(paused["video"]["height"], 192)
            self.assertEqual(paused["audio"]["frames"], 0)

            status, data, _ = request(url, "POST", "/frame", {"frames": 1, "keys": ["Space"]})
            self.assertEqual(status, 200, data)
            held = json.loads(data)
            self.assertTrue(held["ok"])
            self.assertGreater(held["state"]["ticks"], paused["state"]["ticks"])
            self.assertEqual(held["state"]["registers"]["a"] & 0x80, 0x80)
            self.assertGreater(held["audio"]["frames"], 700)

            status, data, _ = request(url, "POST", "/frame", {"frames": 1, "keys": []})
            self.assertEqual(status, 200, data)
            released = json.loads(data)
            self.assertGreater(released["state"]["ticks"], held["state"]["ticks"])
            self.assertEqual(released["state"]["registers"]["a"] & 0x80, 0)

    def test_rejected_input_batch_does_not_change_keyboard_state(self):
        # Repeatedly sample the keyboard data and strobe into A.
        with session("ad00c04c0020") as (_, url, _):
            status, data, _ = request(url, "POST", "/frame", {"frames": 1})
            self.assertEqual(status, 200, data)
            original = json.loads(data)["state"]["registers"]["a"]
            self.assertEqual(original & 0x80, 0)

            status, data, _ = request(url, "POST", "/frame", {
                "frames": 1,
                "inputs": [{"kind": "hold", "x": 65}, {"kind": "buttons", "x": 2}],
            })
            self.assertEqual(status, 400, data)
            self.assertFalse(json.loads(data)["ok"])
            status, data, _ = request(url, "POST", "/frame", {"frames": 1})
            self.assertEqual(status, 200, data)
            self.assertEqual(json.loads(data)["state"]["registers"]["a"], original)

            # The same valid first event still works when sent alone.
            status, data, _ = request(url, "POST", "/frame", {
                "frames": 1, "inputs": [{"kind": "hold", "x": 65}],
            })
            self.assertEqual(status, 200, data)
            self.assertEqual(json.loads(data)["state"]["registers"]["a"], 65 | 0x80)

    def test_invalid_frame_recovers_and_stop_exits_cleanly(self):
        with session() as (process, url, _):
            for body in ({"frames": 7}, {"keys": ["KeyF"]},
                         {"inputs": [{"kind": "write", "x": 0, "y": 1}]},
                         {"cmd": "read"}, []):
                with self.subTest(body=body):
                    status, data, _ = request(url, "POST", "/frame", body)
                    self.assertEqual(status, 400, data)
                    self.assertFalse(json.loads(data)["ok"])
            status, data, _ = request(url, "POST", "/frame", {"frames": 1})
            self.assertEqual(status, 200, data)
            self.assertTrue(json.loads(data)["ok"])
            status, data, _ = request(url, "POST", "/stop", {"keys": [], "frames": 0})
            self.assertEqual(status, 200, data)
            self.assertTrue(json.loads(data)["ok"])
            self.assertEqual(process.wait(timeout=10), 0)


    def test_stopped_terminal_persists_and_explicit_restart_clears_inputs(self):
        with session("ad61c0db") as (_, url, _):
            status, data, _ = request(url, "POST", "/frame", {"frames": 1, "keys": ["Space"]})
            self.assertEqual(status, 200, data)
            ended = json.loads(data)
            self.assertEqual(ended["terminal"]["reason"], "stp")
            self.assertEqual(ended["state"]["registers"]["a"], 128)
            self.assertNotIn("image", ended)
            self.assertEqual(ended["audio"]["frames"], 0)
            self.assertEqual(request(url)[0], 200)  # Page reload retains the session.
            for frames in (0, 6):
                status, data, _ = request(url, "POST", "/frame", {"frames": frames})
                state = json.loads(data)
                self.assertEqual(status, 200, data)
                self.assertEqual(state["terminal"], ended["terminal"])
                self.assertEqual(state["state"]["ticks"], ended["state"]["ticks"])
                self.assertNotIn("image", state)
            # Restart accepts no replacement program/configuration surface.
            self.assertEqual(request(url, "POST", "/restart", {"disk": "/tmp/other.po"})[0], 400)
            self.assertEqual(request(url, "POST", "/restart", {}, query="token=wrong")[0], 403)
            status, data, _ = request(url, "POST", "/restart", {
                "frames": 0, "keys": ["Space"], "inputs": [{"kind": "hold", "x": 65}]})
            self.assertEqual(status, 200, data)
            restarted = json.loads(data)
            self.assertEqual(restarted["reason"], "restarted")
            self.assertEqual(restarted["session"], ended["session"] + 1)
            self.assertIsNone(restarted["terminal"])
            self.assertEqual(restarted["state"]["ticks"], 0)
            self.assertEqual(restarted["state"]["audio"]["frames"], 0)
            self.assertIn("image", restarted)
            status, data, _ = request(url, "POST", "/frame", {"frames": 1})
            self.assertEqual(status, 200, data)
            self.assertEqual(json.loads(data)["state"]["registers"]["a"], 0)

    def test_restart_preserves_wav_and_uses_a_new_recording(self):
        with tempfile.TemporaryDirectory(prefix="appletini-restart-") as work:
            wav = Path(work) / "game.wav"
            with session(extra=("--wav", str(wav), "--no-speech")) as (_, url, _):
                status, data, _ = request(url, "POST", "/frame", {"frames": 1})
                self.assertEqual(status, 200, data)
                first_frames = json.loads(data)["state"]["audio"]["frames"]
                status, data, _ = request(url, "POST", "/restart", {})
                self.assertEqual(status, 200, data)
                restart_wav = Path(json.loads(data)["state"]["audio"]["wav"])
                self.assertNotEqual(restart_wav, wav)
                with wave.open(str(wav), "rb") as recording:
                    self.assertEqual(recording.getnframes(), first_frames)
                complete = wav.read_bytes()
                request(url, "POST", "/frame", {"frames": 2})
                self.assertEqual(wav.read_bytes(), complete)

    def test_live_acceleration_keeps_machine_and_restart_uses_new_speed(self):
        with session(extra=("--no-speech",)) as (_, url, _):
            _, data, _ = request(url, "POST", "/frame", {"frames": 1})
            original = json.loads(data)
            for profile in ("vtw26", "vtw33", "mhz1"):
                status, data, _ = request(url, "POST", "/acceleration", {"profile": profile})
                changed = json.loads(data)
                self.assertEqual(status, 200, data)
                self.assertEqual(changed["session"], original["session"])
                self.assertEqual(changed["state"], original["state"])
                self.assertEqual(changed["machine"]["profile"], profile)
                self.assertFalse(changed["acceleration_restarted"])
            _, data, _ = request(url, "POST", "/restart", {})
            restarted = json.loads(data)
            self.assertEqual(restarted["session"], original["session"] + 1)
            self.assertEqual(restarted["machine"]["profile"], "mhz1")
            self.assertEqual(restarted["state"]["ticks"], 0)

    def test_turbo_acceleration_needs_explicit_restart_and_invalid_requests_recover(self):
        with session(extra=("--no-audio",)) as (_, url, _):
            _, data, _ = request(url, "POST", "/frame", {"frames": 1})
            original = json.loads(data)
            for body in ({"profile": "turbo-f122"}, {"profile": "unknown"},
                         {"profile": "vtw26", "restart": 1}, {"profile": []},
                         {"profile": "vtw26", "frames": 2}, {}):
                status, data, _ = request(url, "POST", "/acceleration", body)
                self.assertEqual(status, 400, data)
                self.assertFalse(json.loads(data)["ok"])
            self.assertEqual(request(url, "POST", "/acceleration", {"profile": "vtw26"},
                                     query="token=wrong")[0], 403)
            _, data, _ = request(url, "POST", "/frame", {})
            unchanged = json.loads(data)
            self.assertEqual(unchanged["state"], original["state"])
            self.assertEqual(unchanged["machine"]["profile"], "ultrawarp")
            for generation, profile in enumerate(("turbo-f122", "vtw33"), 1):
                status, data, _ = request(url, "POST", "/acceleration", {
                    "profile": profile, "restart": True})
                restarted = json.loads(data)
                self.assertEqual(status, 200, data)
                self.assertTrue(restarted["acceleration_restarted"])
                self.assertEqual(restarted["reason"], "restarted")
                self.assertEqual(restarted["session"], generation)
                self.assertEqual(restarted["state"]["ticks"], 0)
                self.assertEqual(restarted["machine"]["profile"], profile)


class PlayLifecycleTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / 'tools/appletini'))
        from cli import Machine, parser
        from play import PlaySession
        self.Machine, self.parser, self.PlaySession = Machine, parser, PlaySession

    def test_direct_quit_presents_terminal_and_stays_frozen(self):
        args = self.parser().parse_args(['play', '--hex', '2000bf650020', '--no-audio'])
        machine = self.Machine(args)
        self.addCleanup(machine.close)
        machine.check(machine.lib.ap_prodos(machine.handle, b'TEST', b'GAME.SYSTEM'))
        machine.write('main', 0x2006, b'\x04\0\0\0\0\0\0')
        # Correct inline parameter pointer to $2006.
        machine.write('main', 0x2004, b'\x06\x20')
        play = self.PlaySession(machine, args)
        ended = play.frame(1)
        self.assertEqual(ended['reason'], 'quit')
        self.assertEqual(ended['terminal']['title'], 'Program exited')
        self.assertIn('Restart', ended['terminal']['message'])
        self.assertNotIn('image', ended)
        for frames in (0, 1):
            again = play.frame(frames)
            self.assertEqual(again['terminal'], ended['terminal'])
            self.assertEqual(again['state']['ticks'], ended['state']['ticks'])
        play.restart()
        self.addCleanup(play.close)
        self.assertIsNone(play.frame()['terminal'])
        self.assertEqual(play.generation, 1)

    def test_bosconian_escape_direct_quit_and_real_boot_return(self):
        target = ROOT.parent / 'appletini-one'
        disk = ROOT / 'demos/appletini_bosconian/Appletini-Bosconian.hdv'
        rom = target / 'Assets/ROMs/Apple2e_Enhanced.rom'
        if not disk.is_file():
            self.skipTest('requires built Bosconian disk')
        for boot in (False, True):
            if boot and not all(path.is_file() for path in [rom,
                    target / 'hdl/apple/smartport_a2retronet_style_c700.mem',
                    target / 'hdl/apple/smartport_a2retronet_style_c800.mem']):
                continue  # Direct-launch regression still runs without supplied ROMs.
            argv = ['play', '--disk', str(disk), '--no-audio']
            argv += ['--boot', '--rom', str(rom)] if boot else ['--system', 'BOSCO.SYSTEM']
            args = self.parser().parse_args(argv)
            machine = self.Machine(args)
            self.addCleanup(machine.close)
            machine.run(steps=5_000_000)
            self.assertTrue(machine.get('newvideo') & 0x80)
            machine.check(machine.lib.ap_input(machine.handle, b'key', 27, 0))
            play = self.PlaySession(machine, args)
            reply = play.frame(6)
            if boot:
                # Run actual ProDOS's return path; it must remain an active
                # emulated OS with a real display, never the direct-launch card.
                machine.run(steps=1_000_000)
                reply = play.frame(0)
                self.assertIsNone(reply['terminal'])
                self.assertIn('image', reply)
                self.assertNotEqual(machine.read('main', 0x400, 16), bytes(16))
            else:
                self.assertEqual(reply['reason'], 'quit')
                self.assertEqual(reply['terminal']['reason'], 'quit')
                self.assertNotIn('image', reply)
                self.assertEqual(machine.read('main', 0x400, 16), bytes(16))


if __name__ == "__main__":
    unittest.main()
