# STARFALL music

The STARFALL song is an arrangement of **stg_bs001_88pro.mid**, one of two
free demo MIDI files of the **SHMUP MIDI Pack** by doranarasi. The file has
the notice "Copyright (C) doranarasi 2024".

- Pack page and terms: <https://doranarasi.itch.io/shmup-midi-pack>
- Demo release note: <https://doranarasi.itch.io/shmup-midi-pack/devlog/884676/free-demo-mid-file-released>

On 2026-10-21, the pack page gave these terms. The demo files have the same
terms as the paid assets. All copyright belongs to doranarasi. You can use the
assets in free and commercial works of any genre, but not for NFT content.
You can change the assets for a work. The author welcomes MIDI files in games.

Do not publish the MIDI files on the Internet as they are. You can publish
arranged music that comes from them. Only the author can sell or redistribute
the songs. Credit is not necessary, but the author recommends it. This is a
summary; the pack page is the authority.

Thus this folder contains the arrangement, not the MIDI file. The STARFALL
title screen gives credit to doranarasi, and the generated C header contains
the credit line.

| File | Contents |
| --- | --- |
| [arrangement.json](arrangement.json) | Bar range, loop bar, rows per beat, and the MIDI channel, chord slot, volume, decay and floor of each track |
| [song.json](song.json) | The arranged song that the build compiles; you can edit it by hand |

This command makes `song.json` from the demo file:

```powershell
python tools/midi.py stg_bs001_88pro.mid assets/starfall/music/arrangement.json --output assets/starfall/music/song.json
```

The arrangement uses the loop of the original, bars 26-49, at 152 bpm with
eight rows for each beat. Its eight tracks are:

- The saw lead (channel 4).
- The fingered bass (channel 8).
- The two notes of the power chords of the overdrive guitar (channel 2).
- The top two notes of the organ (channel 5).
- The top two notes of the high strings (channel 6).

The arrangement does not contain the drums (channel 10) or the orchestra hits
(channel 3), which follow the guitar rhythm one octave or more higher. It
also does not contain the low strings (channel 1) or the third note of the
organ and string chords. Channel 7 plays the lead one octave lower and
channel 9 plays the bass again, thus the arrangement omits them too.

Decay gives the guitars and the bass a plucked attack. The strings keep their
volume.

The build compiles `song.json` with `tools/music.py` into
`build/starfall_music.h`. It never reads a MIDI file.
[Music, effects and speech](../../../docs/guides/sound.html) describes the two
tools, and [data formats](../../../docs/reference/formats.html#song) gives the
song format.
