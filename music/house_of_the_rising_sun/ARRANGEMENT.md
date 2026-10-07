# House of the Rising Sun — Phasor No. 1

An original blues-rock arrangement of the traditional song for the Phasor in
Appletini One F1.2.5 or later, or a real Phasor: one singing SSI-263 voice, mirrored to both speech sockets, eight AY
melodic channels, and three synthesized drum channels. “No. 1” identifies this
project's first complete arrangement; it is not a researched claim that no
earlier Phasor performance exists.

## The music

- **C minor, 6/8, dotted quarter = 66**, 56 bars plus a release tail, **1:42.32**.
- The main SSI melody spans C3–C4, approximately 131–262 Hz, with a low G2
  pickup that makes the opening rise more pronounced. Phrase endings vary
  between verses and the reprise; stressed syllables have shaped attacks,
  small pitch scoops, and delayed vibrato of at most 20 cents.
- A four-bar introduction leads to two sixteen-bar verses, an eight-bar AY
  instrumental, an eight-bar vocal reprise, and a four-bar coda.
- Each vocal section has a two-eighth-note pickup. The first word starts at
  6.67 seconds. The named section boundaries mark downbeats; exact extraction
  must include the earlier word onset listed in `cues.json`.
- The harmony opens out through **Cm–Eb–F–Ab**, then returns through
  **Cm–Eb–G7–G7**. The major F chord adds a brighter sixth against the minor key.
- Verse one uses alternating plucked contours. Verse two changes to a
  syncopated pattern with short chord strums, a moving bass, and stronger
  drums. Brief instrumental answers occupy the singer's breath gaps.
- The rising introduction motif develops into a written eight-bar solo with
  shorter runs, bent attacks, and higher phrase peaks. The vocal reprise
  begins with two sparse bars, builds, then gives way to a descending coda,
  two stop-time hits, a pause, and the final fading minor chord.

The bass uses AY voice 0; plucked strings use 1 and 4; chord strums use 2, 5,
and 8; the lead and vocal answers use 6; occasional lead harmonies use 7.
Voice 3 is unused. Voices 9–11 on the fourth AY chip are reserved for kick,
snare, and hat. The kick uses a falling tone; snare and hat independently gate
the chip's shared noise generator. All sounds use AY tone/noise/volume or SSI
register writes, with no recorded samples or external instruments.

AY volume codes use a logarithmic ladder. The revised balance lifts every
nonzero melodic and percussion level by one AY step, bringing the music
forward relative to the voice. Plucks attack at codes 11–12 and decay by three
codes; bass and solo attacks reach 12–14. Strums spread their three attacks
slightly in time. The SSI uses syllable envelopes and section levels instead
of a constant maximum amplitude. These dynamics are stored in the score and
apply on hardware as well as in the listening render; no separate backing
gain is added after rendering.

## Traditional source and new decisions

The tune is a manually entered adaptation of the traditional melody. Its
contour was checked against the anonymous-song melody in Frank Nordberg's
[Musica Viva transcription](https://abcnotation.com/tunePage?a=trillian.mit.edu/~jc/music/abc/mirror/musicaviva.com/tunes/usa/house-of-the-rising-01/0000)
and the [Digital Tradition variant](https://abcnotation.com/tunePage?a=sniff.numachi.com/~rickheit/dtrad/abc_dtrad.tar.gz/abc_dtrad/HOUSESUN/0000).
These references identify the tune; their modern editions are not described
as CC0, and their files or accompanying arrangements are not included here.

The older female-narrator text is documented in the Georgia Turner / Bert
Martin material in John and Alan Lomax's *Our Singing Country* (1941):
[historical notation and collection details](https://www.traditionalmusic.co.uk/our-singing-country/our-singing-country%20-%200468.htm)
and [continuation and text](https://www.traditionalmusic.co.uk/our-singing-country/our-singing-country%20-%200469.htm).
The 1941 edition is a historical reference, not a claim that the book itself
is public domain. This performance uses the old opening verse and the warning
to a baby sister, with a small grammatical adaptation, “many **a** poor girl.”

The rhythmic grouping, instrumental parts, harmony, voicings, register,
phrasing, dynamics, SSI phonetic timings, and vocal reprise were created for
this arrangement. It is not a transcription of the Animals' recording or an
attempt to reproduce Eric Burdon's voice. No human recording is used as an
input or included in the output.

## Sung text

There is a house in New Orleans,  
They call the Rising Sun.  
It's been the ruin of many a poor girl,  
And me, O God, for one.

Go tell my baby sister,  
Never do like I have done.  
To shun that house in New Orleans,  
They call the Rising Sun.

The reprise repeats the opening two lines.

## Build and edit

Run from the repository root:

```sh
python3 music/house_of_the_rising_sun/arrangement.py
PYTHONPATH=music/song_to_phasor python3 -m phasor compile \
  music/house_of_the_rising_sun/score.json \
  --out music/house_of_the_rising_sun/build/pal --clock pal
```

The musical source uses only Python's standard library and the sibling
framework. Edit these files, then regenerate:

- `arrangement.py`: `VERSE_ONE` / `VERSE_TWO`, vocal phrasing, tempo, and
  transposition. The written pitches are in A minor; `TRANSPOSE = 3` moves the
  vocals and melodic accompaniment to the performed key of C minor.
- `backing.py`: harmony, bass, plucked patterns, strums, instrumental phrases,
  and their volume/pitch envelopes. `SONG_CHORDS` also supplies the cue sheet.
- `percussion.py`: section grooves, accents, and fills. Drum pitches are
  synthesized by the framework and are independent of the musical transposition.

Every vocal melody entry stores a syllable, an eighth-note offset, one or
more MIDI pitches with durations, and an SSI spelling. The spelling format is
`onset consonants/vowel>optional diphthong/closing consonants`.

The generator produces:

| File | Purpose |
|---|---|
| `score.json` | Editable, complete Phasor framework score |
| `cues.json` | Section boundaries, chords, sung text, syllables, MIDI melody, exact phone intervals |
| `phonemes.json` | Framework-compatible timed SSI annotations |
| `vocal-reference.mid` | The intended monophonic melody and rests for independent audition |

The MIDI uses a technical 60-quarter-note/minute clock at 100 ticks/quarter
so each MIDI tick equals one 10 ms score tick. Its timing is correct, but the
musical 6/8 meter and dotted-quarter tempo are carried in `cues.json`, not in
the MIDI tempo map. The reference contains nominal notes, without vibrato or
phonemes; it is not a human-singing reference.

Consonants last 50–70 ms each. Vowels occupy the remaining syllable duration;
diphthongs change near the end. Long-vowel pitch updates preserve the running
phoneme. A real phone/syllable onset explicitly retriggers it. Line endings
leave a short breath. Filter codes progress from 116 to 122 to 126 across the
vocal sections, with a four-code reduction at vowel onsets. The phonetic
spellings and filter choices are authored controls, not a claim of verified
intelligibility or a calibrated vocal-tract match.

The spellings were checked against the phoneme chart on page 3 of the
[Silicon Systems SSI-263A datasheet](https://downloads.reactivemicro.com/Electronics/Speech/SSI-263A%20Data%20Sheet%20v2.pdf).
SSI labels are not generic English respellings: `A` is the vowel in *made*,
`E` in *meet*, `U` in *tune*, `OU` in *boat*, and `UH1` in *love*.
`HF` supplies the consonant in *heart*; `HV` is a **hold-vocal control** and
must not be used as an ordinary /h/. The final score uses `A` for “they,”
`E` for the stressed vowel in “leans” and “me,” `U` for “do,” and `HF` for
“have.” Closing /l/ sounds use `LF`.

The arrangement contains 363 percussion hits. The compiler's `report.json`
records the current stream size, register-write counts, and static pitch
quantization. Static pitch error is distinct from measured pitch in rendered
or physical audio.
