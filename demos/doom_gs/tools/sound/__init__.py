"""Music of DOOM on the Phasor: host tools of the sound track (NATIVE.md S1).

The source is the WAD's MUS songs (the D_* lumps). Upstream's DOC song
units and its SoundFont converter are not used. All of this is original
code, written from the published MUS, MIDI, WAD and GENMIDI layouts and
from the Appletini's HDL of the Phasor.

Modules:
  mus       the WAD directory and the MUS parser (first decoder)
  mus2mid   MUS to a standard MIDI file, a second decoder written apart
  midi      a minimal standard MIDI file reader, for the second decoder
  genmidi   the GENMIDI instrument bank: carrier envelopes, note offsets
  tables    the tables the 65C02 player shares with the host: periods,
            bend multipliers, levels, tempo, the voice layout (native12)
  mus2ay    the converter: MUS to a song file of AY voice commands
  player    the model of the 65C02 player: song file to AY register writes
  ayrender  AY register writes to a WAV file, after the Phasor's HDL
  report    all songs: statistics for README.md, and WAV renders

tools/sound/README.md describes the song file and the player.
"""
