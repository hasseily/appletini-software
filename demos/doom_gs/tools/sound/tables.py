"""Constants and tables shared by the converter (mus2ay.py), the effects
(fxconv.py) and the 65C02 player's generated tables (tables65.py).

Facts about the card come from the
Appletini's HDL (FW/ = the appletini-one-main firmware snapshot):

- The PSG clock enable is one pulse an Apple bus cycle (data_en), plus a
  second pulse in Phasor native mode: FW/hdl/apple/mockingboard.sv:262
  ("psg_clock = via_bus_clock || psg_ce_extra_q") and :542-549 ("The
  Phasor native mode doubles the PSG clock"). So the PSG clock is the bus
  clock in Mockingboard mode and twice it in native mode, the only mode
  the music plays in.
- Tone: a /8 prescaler (FW/hdl/apple/YM2149.sv:139-162) and a counter
  that toggles the output every P prescaled ticks (:203-226): the tone is
  clock / (16 P). P = 0 silences a channel whose tone is on (:218-220).
- Levels: the AY-3-8913 table of the YM2149 core (entries 32 + 2n for a
  fixed level n; YM2149.sv:345-349 and :389-420), the default of the
  Phasor menu
  (FW/ps_sources/frontend/config_menu_phasor.c:186).

The bus clock is 1,015,625 Hz on a PAL //e (65 cycles in a 64 us line)
and 1,020,484 Hz on an NTSC //e (the usual figure, with the long cycle).
The Bilestoad's music tool uses 2 x 1,020,484 Hz in native mode
(demos/bilestoad/tools/make_music.py:22), which is the NTSC case.
A video frame is 312 lines of 65 cycles on PAL and 262 on NTSC.
"""

import math
from collections import namedtuple

TICK_HZ = 140                  # MUS time unit
ATT_MAX = 80                   # attenuation in 0.5 dB steps; 80 = silent
ATT_UNIT_DB = 0.5
HW_DRUM_ATT = 12               # a drum hit this loud or louder (6 dB) uses
                               # the chip's envelope generator

Machine = namedtuple('Machine', 'name bus_hz vbl_cycles psg_multiplier')

# The music plays only with the card in native mode (no 6-voice
# fallback), so these are the only machines.
PAL_NATIVE = Machine('pal-native', 1015625, 312 * 65, 2)
NTSC_NATIVE = Machine('ntsc-native', 1020484, 262 * 65, 2)


def psg_clock(machine):
    return machine.bus_hz * machine.psg_multiplier


# ---------------------------------------------------------------------------
# The voice layout. A voice is (chip, channel). Chips 0 and 1 are the first
# and second AY behind VIA-A ($C41x), chips 2 and 3 behind VIA-B ($C48x),
# the numbering of the Bilestoad, Bosconian and Pinball drivers; all four
# exist in the card's native mode. A drum voice owns the noise period (R6)
# and the envelope registers (R11-R13) of its chip. There is one layout,
# native12: the 6-voice fallback for a card in Mockingboard mode was
# removed on 2026-09-30. Its id is byte 1 of a
# song file.
# ---------------------------------------------------------------------------

Layout = namedtuple('Layout', 'name ident melodic drums effects chips')

NATIVE12 = Layout(
    'native12', 0,
    melodic=((0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (2, 0), (2, 1)),
    drums=((1, 2), (2, 2)),
    effects=((3, 0), (3, 1), (3, 2)),
    chips=(0, 1, 2, 3))


def voices(layout):
    """Music voices in player order: the melodic voices, then the drums."""
    return tuple(layout.melodic) + tuple(layout.drums)


def owned_registers(layout):
    """{chip: ascending registers the music player compares and writes}."""
    out = {}
    for chip, channel in voices(layout):
        regs = out.setdefault(chip, set())
        regs.update((2 * channel, 2 * channel + 1, 7, 8 + channel))
    for chip, _ in layout.drums:
        out[chip].update((6, 11, 12, 13))
    return {chip: tuple(sorted(regs)) for chip, regs in sorted(out.items())}


# ---------------------------------------------------------------------------
# Chip 3's voices for the effects (S4): the one table of their sides. The
# effect player (src/sound/fx.s, through tables65.py's FX_VOICE_* and
# FX_SEP_* equates) reads it.
#
# A voice is (name, side, pan): its channel of chip 3 is its index, its
# pan the value the Doom profile gives it in the Appletini's Phasor menu
# (the menu's "AY3 A", "AY3 B", "AY3 C", keys phasor.pan.10-12 of
# appletini_cfg.txt: FW/ps_sources/frontend/config_menu_phasor.c:16-29,
# :234-243). The menu's scale is 0-15; the HDL's gains
# (FW/hdl/apple/mockingboard.sv:316-343) are left 16/16 for pans 0-8 and
# right 16/16 for pans 8-15, so 8 is the one centred value, both sides
# full (also the value RETURN on a pan item resets it to,
# config_menu_phasor.c:398-409). Pans 5 and 11 are the menu's defaults
# for A and B (config_menu_phasor.c:9-14): 5 is left 16/16, right 10/16;
# 11 is left 9/16, right 16/16. The menu's default for C is 5 (left); the
# Doom profile sets it to 8 (tools/sound/README.md "Stereo by voice").
# ---------------------------------------------------------------------------

FxVoice = namedtuple('FxVoice', 'name side pan')

FX_VOICES = (FxVoice('A', 'left', 5),
             FxVoice('B', 'right', 11),
             FxVoice('C', 'centre', 8))

# The voice choice at a sound's start, from its separation (upstream's:
# 128 the centre, below it the left: left = vol x (254 - sep) / 127,
# s_sound65.s:698-712). Below FX_SEP_LEFT the left voice is tried first,
# above FX_SEP_RIGHT the right one, from FX_SEP_LEFT to FX_SEP_RIGHT the
# centre; a busy voice falls back to the nearest free voice in pan, the
# centre to the side the separation leans to (128 to the left).
FX_SEP_LEFT = 96
FX_SEP_RIGHT = 160
FX_SEP_CENTRE = 128


def fx_voice(side):
    """The index (chip 3's channel) of the voice on `side`."""
    return next(k for k, v in enumerate(FX_VOICES) if v.side == side)


# ---------------------------------------------------------------------------
# Pitch
# ---------------------------------------------------------------------------

def note_hz(note):
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


def period_of_hz(clock, hz):
    return int(math.floor(clock / (16.0 * hz) + 0.5))


def period_table(machine):
    """Tone period of each note 0-127: clock / (16 f), rounded; a note
    whose period exceeds 4095 is raised by octaves until it fits."""
    clock = psg_clock(machine)
    table = []
    for note in range(128):
        n = note
        while period_of_hz(clock, note_hz(n)) > 4095:
            n += 12
        table.append(max(1, period_of_hz(clock, note_hz(n))))
    return table


def bend_magnitude(bend):
    """|2^(-(bend - 128) / 768) - 1| x 2048, rounded: the period change of
    a MUS bend (128 is none; the range is +-2 semitones, 64 steps a
    semitone, the range DMX's OPL playback uses)."""
    factor = 2.0 ** (-(bend - 128) / 768.0)
    return int(math.floor(abs(factor - 1.0) * 2048.0 + 0.5))


BEND_MAGNITUDE = tuple(bend_magnitude(b) for b in range(256))


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------

# The YM2149 core's AY-3-8913 table (YM2149.sv:389-420) at 32 + 2n: the
# 8-bit output of fixed level n. The 32-step envelope reads entry 32 + e.
AY_TABLE = (0x00, 0x00, 0x03, 0x03, 0x04, 0x04, 0x06, 0x06,
            0x0a, 0x0a, 0x0f, 0x0f, 0x15, 0x15, 0x22, 0x22,
            0x28, 0x28, 0x41, 0x41, 0x5b, 0x5b, 0x72, 0x72,
            0x90, 0x90, 0xb5, 0xb5, 0xd7, 0xd7, 0xff, 0xff)
AY_OUT = tuple(AY_TABLE[2 * n + (n >> 3)] for n in range(16))
AY_DB = (None,) + tuple(20.0 * math.log10(v / 255.0) for v in AY_OUT[1:])


def level_of_attenuation(att):
    """The AY level nearest in dB to an attenuation of att / 2 dB; 0 at
    40 dB and more (level 1 is -38.6 dB)."""
    if att >= ATT_MAX:
        return 0
    db = -att * ATT_UNIT_DB
    return min(range(1, 16), key=lambda n: (abs(db - AY_DB[n]), -n))


LEVEL = tuple(level_of_attenuation(a) for a in range(ATT_MAX + 1))


def midi_attenuation(value):
    """The General MIDI volume law, 40 log10(value / 127) dB, in steps of
    0.5 dB, rounded, at most ATT_MAX."""
    if value <= 0:
        return ATT_MAX
    return min(ATT_MAX, int(math.floor(-80.0 * math.log10(value / 127.0)
                                       + 0.5)))


ATTENUATION_OF_VALUE = tuple(midi_attenuation(v) for v in range(128))


# ---------------------------------------------------------------------------
# Tempo: MUS ticks of 1/140 s against one interrupt a video frame. The
# player adds TEMPO_FRAC to a 16-bit fraction each interrupt and runs
# TEMPO_INT ticks plus the carry.
# ---------------------------------------------------------------------------

def tempo(machine):
    """(whole ticks, 16-bit fraction) of MUS ticks an interrupt."""
    per = TICK_HZ * machine.vbl_cycles / machine.bus_hz
    whole = int(per)
    return whole, int(math.floor((per - whole) * 65536.0 + 0.5))
