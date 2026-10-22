import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import speech

class SpeechTests(unittest.TestCase):
    def test_minimal_phrase_bank_omits_unused_number_assets(self):
        text, records = speech.compile_manifest({"phrases": {"SAY_READY": "READY"}}, "minimal", False)
        self.assertEqual(len(records), 1)
        self.assertNotIn("minimal_numbers", text)
        self.assertIn("{minimal_phrases,1,0}", text)
    def test_number_expansion(self):
        expected = {0:"ZERO",19:"NINETEEN",20:"TWENTY",21:"TWENTY ONE",
                    100:"ONE HUNDRED",1001:"ONE THOUSAND ONE",
                    9999:"NINE THOUSAND NINE HUNDRED NINETY NINE"}
        for number, words in expected.items(): self.assertEqual(speech.number_words(number), words.split())
        for number in range(10000):
            self.assertLessEqual(len(speech.number_words(number)), 6)
        for number in (-1,10000):
            with self.assertRaises(ValueError): speech.number_words(number)
    def test_authored_pronunciation_and_repeated_phonemes(self):
        data, phones = speech.compile_text("STARFALL 21", {"STARFALL":"S T AA R F AO L"})
        self.assertEqual(phones[:7], "S T AA R F AO L".split())
        self.assertIn("TWENTY", speech.number_words(21))
        data, _ = speech.compile_text("READY", {"READY":["EH","EH"]})
        self.assertEqual(data, [0x0A,0x0A])
    def test_unknown_invalid_and_bounds(self):
        for text in ("unicorn", "", "@", "10000"):
            with self.assertRaises(ValueError): speech.compile_text(text)
        with self.assertRaises(ValueError): speech.compile_text("READY", {"READY":["BOGUS"]})
        with self.assertRaises(ValueError): speech.compile_text("READY "*100)
    def test_manifest_is_deterministic_and_has_numbers(self):
        manifest = json.loads((ROOT / "assets/speech.json").read_text())
        header, records = speech.compile_manifest(manifest, "demo")
        self.assertEqual(header, speech.compile_manifest(manifest,"demo")[0])
        self.assertEqual(len(records), len(manifest["phrases"])+30)
        self.assertIn("static const ti_speech_bank demo",header)
        self.assertTrue(all(0<=byte<192 for record in records for byte in record[2]))
    def test_identifiers_and_limits(self):
        for manifest in ({"phrases":{}},{"phrases":{"bad-name":"Ready"}},
                         {"phrases":{f"SAY_{i}":"Ready" for i in range(226)}}):
            with self.assertRaises(ValueError): speech.compile_manifest(manifest)

if __name__ == "__main__": unittest.main()
