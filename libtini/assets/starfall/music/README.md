# STARFALL music

STARFALL's song is an arrangement of **stg_bs001_88pro.mid**, one of two
free demo MIDI files of the **SHMUP MIDI Pack** by doranarasi. The file
carries the notice "Copyright (C) doranarasi 2024".

- Pack page and terms: <https://doranarasi.itch.io/shmup-midi-pack>
- Demo release note: <https://doranarasi.itch.io/shmup-midi-pack/devlog/884676/free-demo-mid-file-released>

The pack page, read on 2026-10-21, says that the demo files have the same
terms as the paid assets. All copyright belongs to doranarasi. The assets
may be used in free and commercial works of any genre, but not for NFT
content; they may be processed for a work. The author welcomes MIDI files
embedded in games. The MIDI files cannot be published on the Internet as
they are, but arranged music based on them can be. Sales or redistribution
of the songs by anyone but the author are not allowed. Credit is not
required but is recommended. These terms are summarized here; the pack
page is the authority.

This directory therefore holds the arrangement, not the MIDI file. The
STARFALL title screen credits doranarasi, and the generated C header
repeats the credit line.

| File | Contents |
| --- | --- |
| [arrangement.json](arrangement.json) | Bar range, loop bar, rows per beat and each track's MIDI channel, chord slot, volume, decay and floor |
| [song.json](song.json) | The arranged song that the build compiles; hand edits are allowed |

`song.json` was made from the demo file with:

```powershell
python tools/midi.py stg_bs001_88pro.mid assets/starfall/music/arrangement.json --output assets/starfall/music/song.json
```

The arrangement takes the loop of the original, bars 26-49, at 152 bpm
with eight rows a beat. Its eight tracks are the saw lead (channel 4), the
fingered bass (8), both notes of the overdrive guitar's power chords (2),
the top two notes of the organ (5) and the top two notes of the high
strings (6). Left out are the drums (10), the orchestra hits (3), which
follow the guitar's rhythm an octave or more higher, the low strings (1)
and the third note of organ and string chords. Channel 7 doubles the lead
an octave lower and channel 9 doubles the bass, so they are left out too.
Decay gives the guitars and bass a plucked attack; the strings hold their
volume.

The build compiles `song.json` with `tools/music.py` into
`build/starfall_music.h`; it never reads a MIDI file.
[Music, effects and speech](../../../docs/guides/sound.html) describes both
tools, and [data formats](../../../docs/reference/formats.html#song) the song
format.
