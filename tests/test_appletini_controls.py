"""Keyboard controller behavior, independent of the browser and machine core."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE = Path(__file__).resolve().parents[1] / "tools" / "appletini" / "controls.py"
SPEC = importlib.util.spec_from_file_location("appletini_controls", MODULE)
controls = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(controls)


def state(codes):
    return {(event["kind"], event["x"]): event["y"] for event in controls.events(codes)}


class KeyboardControlsTests(unittest.TestCase):
    def test_eight_grid_directions_match_paddles_and_snes_bits(self):
        cases = {
            "KeyQ": (0, 0, 0x50), "KeyW": (128, 0, 0x10),
            "KeyE": (255, 0, 0x90), "KeyA": (0, 128, 0x40),
            "KeyD": (255, 128, 0x80), "KeyZ": (0, 255, 0x60),
            "KeyX": (128, 255, 0x20), "KeyC": (255, 255, 0xA0),
        }
        for code, (x, y, pad) in cases.items():
            with self.subTest(code=code):
                current = state([code])
                self.assertEqual(current[("paddle", 0)], x)
                self.assertEqual(current[("paddle", 1)], y)
                self.assertEqual(current[("pad", 0)], pad)

    def test_center_overrides_directions_but_preserves_buttons(self):
        for codes in ([], ["KeyS"], ["KeyS", "KeyQ", "KeyX", "Space"]):
            with self.subTest(codes=codes):
                current = state(codes)
                self.assertEqual(current[("paddle", 0)], 128)
                self.assertEqual(current[("paddle", 1)], 128)
                self.assertEqual(current[("pad", 0)] & 0xF0, 0)
        current = state(["KeyS", "KeyQ", "Space"])
        self.assertEqual(current[("button", 0)], 1)
        self.assertEqual(current[("pad", 0)], 1)

    def test_opposite_directions_cancel_even_with_multiple_keys_on_one_side(self):
        cases = [
            (["KeyA", "KeyD"], 128, 128),
            (["KeyW", "KeyX"], 128, 128),
            (["KeyQ", "KeyC"], 128, 128),
            (["KeyQ", "KeyE"], 128, 0),
            (["KeyQ", "KeyA", "KeyD"], 128, 0),
        ]
        for codes, x, y in cases:
            with self.subTest(codes=codes):
                current = state(codes)
                self.assertEqual(current[("paddle", 0)], x)
                self.assertEqual(current[("paddle", 1)], y)

    def test_release_emits_complete_neutral_state(self):
        held = state(["KeyE", "Space", "KeyJ", "KeyK"])
        self.assertEqual(held[("pad", 0)], 0x193)
        released = state([])
        self.assertEqual(released, {
            ("paddle", 0): 128, ("paddle", 1): 128,
            ("button", 0): 0, ("button", 1): 0, ("button", 2): 0,
            ("pad", 0): 0,
        })
        self.assertEqual(state(["Space"])[("pad", 0)], 1)

    def test_all_buttons_have_the_expected_snes_and_apple_bits(self):
        expected = {
            "Space": 0x001, "KeyK": 0x002, "Tab": 0x004, "Enter": 0x008,
            "KeyJ": 0x100, "KeyU": 0x200, "KeyI": 0x400, "KeyO": 0x800,
        }
        for code, mask in expected.items():
            with self.subTest(code=code):
                current = state([code])
                self.assertEqual(current[("pad", 0)], mask)
                self.assertEqual(current[("button", 0)], int(code == "Space"))
                self.assertEqual(current[("button", 1)], int(code == "KeyJ"))
                self.assertEqual(current[("button", 2)], int(code == "KeyK"))
        self.assertEqual(state(set(expected))[("pad", 0)], 0xF0F)

    def test_order_and_duplicate_keys_do_not_change_state_or_mutate_input(self):
        codes = ["KeyW", "Space", "KeyW"]
        before = codes[:]
        self.assertEqual(controls.events(codes), controls.events({"Space", "KeyW"}))
        self.assertEqual(codes, before)

    def test_rejects_unknown_and_nonfinite_input_shapes(self):
        invalid = ["KeyQ", None, {"KeyQ": True}, ["KeyF"], [None],
                   [1], [["KeyQ"]], ["KeyQ"] * 100, iter(["KeyQ"])]
        for codes in invalid:
            with self.subTest(codes=repr(codes)):
                with self.assertRaises(ValueError):
                    controls.events(codes)


if __name__ == "__main__":
    unittest.main()
