"""Music of DOOM on the Phasor: host tools of the sound track.

The source is the WAD's MUS songs (the D_* lumps). Upstream's DOC song
units and its SoundFont converter are not used. All of this is original
code, written from the published MUS, MIDI, WAD and GENMIDI layouts and
from the Appletini's HDL of the Phasor.

Modules:
  mus       the WAD directory and the MUS parser
  genmidi   the GENMIDI instrument bank: carrier envelopes, note offsets
  tables    the tables the 65C02 player shares with the host: periods,
            bend multipliers, levels, tempo, the voice layout (native12)
  tables65  those tables as the 65C02 player's ca65 include
  mus2ay    the converter: MUS to a song file of AY voice commands
  player    the song file's format
  songs     the 13 songs for the disk's SONGS.1
  fxconv    the sound effects to AY scripts for chip 3, the bank SFX.1
  fxchan    the channel logic's generated include

tools/sound/README.md describes the song file and the player.
"""
