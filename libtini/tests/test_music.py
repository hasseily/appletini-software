import importlib.util
import json
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


music = load("music_tool", "tools/music.py")
midi = load("midi_tool", "tools/midi.py")


def song_document(**changes):
    song = {"bpm": 150, "rows_per_beat": 4, "loop": 0,
            "tracks": [{"name": "lead", "volume": 12, "decay": 2, "floor": 6, "order": ["a", "b"]},
                       {"name": "bass", "volume": 10, "order": ["c", "c"]}],
            "patterns": {"a": "C4:2 -:2 E4:4", "b": "v9 G4:8", "c": "C2:8"}}
    song.update(changes)
    return {"song": song}


def song_bytes(document):
    text, report = music.compile_song(document, "demo")
    body = text[text.index("{") + 1:text.index("};")]
    return bytes(int(item, 16) for item in body.replace("\n", " ").split(",") if item.strip()), report


def midi_file(division, events_by_track):
    """A format 1 file; events are (tick, bytes) in order per track."""
    chunks = [b"MThd" + struct.pack(">IHHH", 6, 1, len(events_by_track), division)]
    for events in events_by_track:
        body, last = bytearray(), 0
        for tick, data in events + [(events[-1][0], b"\xFF\x2F\x00")]:
            delta, last = tick - last, tick
            encoded = [delta & 127]
            while delta > 127:
                delta >>= 7
                encoded.insert(0, (delta & 127) | 128)
            body += bytes(encoded) + data
        chunks.append(b"MTrk" + struct.pack(">I", len(body)) + bytes(body))
    return b"".join(chunks)


class MusicTests(unittest.TestCase):
    def test_event_order_and_determinism(self):
        score = {"events": [{"duration": 0, "period": 100, "voice": 0, "volume": 7},
                            {"duration": 25, "period": 200, "voice": 1, "volume": 8}]}
        text, report = music.compile_score(score, "demo")
        self.assertIn("{0, 100, 0, 7}", text)
        self.assertEqual(report["ticks"], 25)
        self.assertEqual(music.compile_score(score, "demo"), (text, report))

    def test_invalid_device_ranges(self):
        base = {"duration": 1, "period": 10, "voice": 0, "volume": 1}
        for key, value in (("duration", -1), ("duration", 65536), ("period", 2048),
                           ("voice", 6), ("volume", 16), ("volume", True)):
            event = dict(base); event[key] = value
            with self.assertRaises(ValueError): music.compile_score({"events": [event]})
        with self.assertRaises(ValueError): music.compile_score({"events": [base]}, "bad-name")
        with self.assertRaises(ValueError): music.compile_score({"voices": 7, "events": [base]})
        with self.assertRaises(ValueError): music.compile_score({"events": [base] * 513})

    def test_native_voices_and_bounded_simultaneous_events(self):
        event = {"duration": 0, "period": 1, "voice": 11, "volume": 1}
        with self.assertRaises(ValueError): music.compile_score({"voices": 12, "events": [event]})
        final = dict(event); final["duration"] = 1
        music.compile_score({"voices": 12, "events": [event] * 31 + [final]})
        with self.assertRaises(ValueError): music.compile_score({"voices": 12, "events": [event] * 32 + [final]})


class SongTests(unittest.TestCase):
    def test_layout_matches_the_player(self):
        data, report = song_bytes(song_document())
        # 150 bpm in sixteenths: 10 ticks a row, 2560 in 8.8.
        self.assertEqual(struct.unpack_from("<H", data)[0], 2560)
        tracks, positions, loop, notes, patterns = data[2:7]
        self.assertEqual((tracks, positions, loop, notes, patterns), (2, 2, 0, 4, 3))
        self.assertEqual(list(data[7:13]), [12, 2, 6, 10, 0, 0])
        # Notes in pitch order: C2, C4, E4, G4.
        periods = struct.unpack_from("<4H", data, 13)
        self.assertEqual(periods, (956, 239, 190, 159))
        offsets = struct.unpack_from("<3H", data, 21)
        self.assertEqual(list(data[27:31]), [0, 1, 2, 2])
        self.assertEqual(offsets[0], 31)
        # Each pattern sets its length, then rows; volume is a command.
        self.assertEqual(data[offsets[0]:offsets[1]], bytes((0x81, 1, 0x60, 0x83, 2, 0xFF)))
        self.assertEqual(data[offsets[1]:offsets[2]], bytes((0xC9, 0x87, 3, 0xFF)))
        self.assertEqual(data[offsets[2]:], bytes((0x87, 0, 0xFF)))
        self.assertEqual(report["bytes"], len(data))
        self.assertEqual(report["rows"], 16)
        self.assertEqual(song_bytes(song_document()), (data, report))

    def test_long_rows_hold(self):
        document = song_document(tracks=[{"name": "pad", "order": ["p"]}], patterns={"p": "A3:100 -:70"})
        data, _ = song_bytes(document)
        body = data[struct.unpack_from("<H", data, 7 + 3 + 2)[0]:]
        # 100 rows: 64 of the note and 36 held; 70 rows of rest: 64 and 6.
        self.assertEqual(body, bytes((0xBF, 0, 0xA3, 0x61, 0xBF, 0x60, 0x85, 0x60, 0xFF)))

    def test_rejected_songs(self):
        bad = [song_document(bpm=10), song_document(rows_per_beat=0), song_document(loop=2),
               song_document(tracks=[]), song_document(patterns={"a": "C4:8"}),
               song_document(tracks=[{"name": "x", "order": ["a"]}] * 13),
               song_document(tracks=[{"name": "x", "order": ["a", "b"]}, {"name": "y", "order": ["c"]}]),
               song_document(tracks=[{"name": "x", "order": ["a"]}, {"name": "y", "order": ["c"]}],
                             patterns={"a": "C4:4", "b": "C4:8", "c": "C2:8"}),
               song_document(patterns={"a": "C4:2 H4:2", "b": "C4:8", "c": "C4:8"}),
               song_document(patterns={"a": "C0:8", "b": "C4:8", "c": "C4:8"}),
               song_document(patterns={"a": "v16 C4:8", "b": "C4:8", "c": "C4:8"}),
               song_document(patterns={"a": "v3", "b": "C4:8", "c": "C4:8"}),
               song_document(patterns={"a": "C4:0", "b": "C4:8", "c": "C4:8"})]
        for document in bad:
            with self.assertRaises(ValueError, msg=json.dumps(document)):
                music.compile_song(document)
        with self.assertRaises(ValueError): music.compile_song(song_document(), "bad name")

    def test_starfall_song_compiles(self):
        document = json.loads((ROOT / "assets/starfall/music/song.json").read_text(encoding="utf-8"))
        text, report = music.compile_song(document, "sf_song")
        self.assertEqual(report["tracks"], 8)
        self.assertLessEqual(report["bytes"], 1100)
        self.assertIn("doranarasi", text)


class MidiTests(unittest.TestCase):
    def test_slots_rests_holds_and_bars(self):
        q = 480
        tempo = (0, b"\xFF\x51\x03" + (500000).to_bytes(3, "big"))
        meter = (0, b"\xFF\x58\x04\x04\x02\x18\x08")
        # Channel 1: C4+E4 for a beat, then G4 two beats later, a little
        # early, for half a beat. Channel 2: C3 held across the bar line.
        # Channel 10 drums are ignored.
        chords = [(0, b"\x90\x3C\x64"), (0, b"\x90\x40\x64"), (q, b"\x80\x3C\x00"), (q, b"\x80\x40\x00"),
                  (3 * q - 10, b"\x90\x43\x64"), (3 * q + q // 2, b"\x80\x43\x00")]
        bass = [(0, b"\x91\x30\x64"), (6 * q, b"\x81\x30\x00"), (0 + 6 * q, b"\x99\x24\x64"),
                (6 * q + 10, b"\x89\x24\x00")]
        data = midi_file(q, [[tempo, meter], chords, bass])
        plan = {"bars": [0, 1], "loop_bar": 1, "rows_per_beat": 2,
                "tracks": [{"name": "hi", "channel": 1, "slot": 0, "volume": 11, "decay": 3, "floor": 5},
                           {"name": "lo", "channel": 1, "slot": 1},
                           {"name": "bass", "channel": 2, "transpose": 12}]}
        song, report = midi.arrange(data, plan)
        self.assertEqual(song["bpm"], 120)
        self.assertEqual(song["loop"], 1)
        patterns = song["patterns"]
        orders = {track["name"]: [patterns[name] for name in track["order"]] for track in song["tracks"]}
        self.assertEqual(orders["hi"], ["E4:2 -:4 G4:1 -:1", "-:8"])
        self.assertEqual(orders["lo"], ["C4:2 -:6", "-:8"])
        self.assertEqual(orders["bass"], ["C4:8", "^:4 -:4"])
        self.assertEqual(song["tracks"][0]["volume"], 11)
        self.assertEqual(report["unassigned"], {"1": 0, "2": 0})
        # The arrangement compiles for the player.
        _, compiled = music.compile_song({"song": song})
        self.assertEqual(compiled["rows"], 16)

    def test_rejected_files(self):
        plan = {"bars": [0, 0], "rows_per_beat": 4, "tracks": [{"channel": 1}]}
        for data in (b"", b"RIFF" + bytes(10), b"MThd" + struct.pack(">IHHH", 6, 1, 1, 0x8000 | 25)):
            with self.assertRaises(ValueError): midi.arrange(data, plan)
        truncated = midi_file(480, [[(0, b"\x90\x3C\x64")]])[:-3]
        with self.assertRaises(ValueError): midi.arrange(truncated, plan)
        tempo_change = midi_file(480, [[(0, b"\xFF\x51\x03\x07\xA1\x20"), (960, b"\xFF\x51\x03\x06\x1A\x80")]])
        with self.assertRaises(ValueError): midi.arrange(tempo_change, plan)
        with self.assertRaises(ValueError): midi.arrange(midi_file(480, [[(0, b"\x90\x3C\x64")]]),
                                                         {**plan, "tracks": [{"channel": 1, "voice": 2}]})


if __name__ == "__main__": unittest.main()
