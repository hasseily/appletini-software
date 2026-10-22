# Audio, speech and input

The driver uses the existing slot-4 Appletini Mockingboard and Phasor
interfaces. It does not change slots and needs no private services. The
caller gives the driver exclusive ownership of the two VIAs, their timers,
all AY chips and the two speech sockets.

The entry personality is Mockingboard, and shutdown restores it. Do not start
the driver while another driver owns this card. Enabled VIA interrupts give
`TI_E_BUSY`. A DDR save, write, read and restore probe rejects an absent VIA.

The probe is in assembly, because cc65 2.19 optimizes some C volatile store
and read sequences at fixed addresses. Probes that change pins need the
exclusive ownership grant.

`ti_audio_init` selects six Mockingboard voices or tries native Phasor mode.
For Phasor, it probes for an independent second AY. If the card aliases that
AY, the driver uses six voices. In native mode the driver doubles the tone
periods to keep the pitch.

`ti_audio_config.voices` limits the driver to fewer voices, rounded up to
whole AY chips of three. 0 keeps all voices. Initialization silences every
chip, but later updates compare and write only the chips that serve a voice.
`ti_audio_voices` reports the result. Voices above the count are out of
range.

The register flush of each update indexes the registers of all chips as one
flat array. The firmware baseline is F1.3.2.

## Device cadence and ownership

VIA-B timer 1 runs at the device cadence, independent of CPU speed. The
`via_hz` setting accepts a known or calibrated clock of 100000..4000000 Hz.
Zero selects the nominal 1000000 Hz. The latch is `via_hz / 100 - 2`, and the
free-running period is the latch plus 2 source clocks.

`TI_AUDIO_TICKS_PER_SECOND` is a nominal 100. The real accuracy depends on
the configured source, not on the CPU profile. `ti_audio_source_hz` and
`ti_audio_tick_divisor` give the configured source and the integer divisor.
No emulator profile changes this configuration.

The assembly ProDOS interrupt receiver increments a 32-bit tick counter and
acknowledges the timer. It never calls C, borrows zero page, maps AUX or
calls ProDOS. Foreground reads take an atomic snapshot of the counter.

A game can add up 30 simulation steps for each 100 device ticks.
`ti_steps_begin` and `ti_steps_due` in
[timing.h](../include/libtini/timing.h) do this. Do not use display
observations as elapsed time. For calibrated elapsed seconds, calculate
`ticks * divisor / source_hz` with wide arithmetic.

The driver installs and removes its receiver with the standard ProDOS MLI
calls `$40` and `$41`. It does not replace an IRQ vector. The receiver
follows the
[ProDOS interrupt convention](https://prodos8.com/docs/techref/adding-routines-to-prodos/):
CLD first, then RTS with carry clear when it claims the interrupt, and with
carry set when it does not.

The driver enables the hardware after a successful allocation and disables it
before the deallocation. When an SHR screen is active, the two MLI calls
restore the saved ProDOS AUX workspace for their duration. They use the same
video loan as storage.

The cleanup of the whole application restores the OS workspace of the screen
before it removes the interrupt receiver. The startup cleanup calls the
registered shutdown hook before it frees memory or returns.

Shutdown silences the AY chips, powers down the SSI sockets, removes the
receiver and restores the saved VIA port, DDR, ACR and PCR settings. It
restores the entry IRQ policy. Ownership excludes external timers and audio,
so the driver does not save their phase or a previous PSG score.

The application must give enough hardware stack space for ProDOS dispatch,
in addition to its own foreground depth.

If the MLI deallocation fails, shutdown returns `TI_E_IO` and makes the clock
invalid. The driver keeps ownership, its cleanup hook and its callback code.
The hardware is silent with its interrupts disabled, and the caller can try
the shutdown again.

After this error, the only permitted audio operation is another shutdown. Do
not resume the clock, configure voices or start playback. Startup does not
free the application or call QUIT after a failed cleanup.

Startup shows `CLEANUP ERROR. KEY RETRIES; CODE RETAINED` and waits for a key
before it tries again. This keeps the callback memory. It cannot repair a
damaged ProDOS interrupt table.

IRQ ticks are correct only while the CPU can service each IRQ within the
10 ms timer period. The SDK bank bursts are shorter than this period, even
with a 1 MHz CPU. An external SEI or a disk driver can hide more than one
period, and a VIA flag cannot count them.

Thus `ti_audio_mark_gap` makes the clock invalid, cancels speech and effects
and mutes music before blocking work. `ti_audio_resume_clock` rebases the
service and continues the score. Ticks during the gap are not elapsed
simulation time.

The SDK storage calls put these hooks around their MLI operations. Callers
must do the same around other blocking or IRQ-masked work, and rebase their
fixed-step loop. They must not use the clock as an absolute wall clock across
such a gap.

The gap hook disables the T1 interrupt of this driver, powers down speech and
acknowledges native SSI completion before slot firmware runs. Without this, a
VIA read in an IRQ can change the C8 ROM ownership during a SmartPort MLI
call.

Resume starts a full new timer period and keeps the counter. Ticks stop
during the declared gap, so they do not measure its time. While the clock is
paused, the receiver declines each interrupt before any slot I/O, also when
ProDOS dispatches the interrupt of another device.

`ti_audio_update` runs in the foreground and is not reentrant. It handles
bounded event catch-up, effects and one speech phoneme, then flushes the
grouped AY shadows.

The update compares and writes the shadows only when a device tick passed
since the previous call, or when a tone, rest, speech or SSI write asks for
it. More calls within the same tick write nothing.

More than one second between updates, or more than 32 due score events or
song rows in one call, returns `TI_E_TIMING`. The driver then silences and
cancels its work safely. A clock gap stays explicit until the resume.

Audio, input and all memory mappings keep the normal entry contract: MAIN
and bank zero. No interrupt handler can call these C APIs.

## Score and effects

A music event has a duration in 100 Hz ticks, a tone period of 0..2047 for
the base clock, a voice and a volume of 0..15. Events apply in sequence, and
a duration of zero lets several voices change at one time. The arrays stay
borrowed until a stop or shutdown.

Reserve a voice mask with `ti_audio_reserve`. The default is voices 0..2.
Music can use only reserved voices, and effects can use only the other
voices. Effects end on device ticks. A replacement with a lower priority
gives `TI_E_BUSY`.

A reservation change cannot remove a voice that the active score plays, or
reserve a voice that plays an effect. Stop those first.
`ti_audio_effect_voice(n)` returns the voice number of the nth voice, from 0,
that the reservation leaves to effects. When fewer voices are left, it
returns 255, which `ti_audio_effect` rejects with `TI_E_RANGE`.

With music on voices 0..1 of a Mockingboard, effect voice 0 is voice 2. With
music on voices 0..7 of a Phasor, effect voice 0 is voice 8. Thus one table
of effect voices works with the two cards.

Larger scores can select a six-voice arrangement and not assume twelve
voices. The event player and the song player are separate archive modules. A
program links only the player that it starts.

```powershell
python tools/music.py assets/music.json --output build/audio_music.h --symbol ti_demo_music --report build/audio_music.json
```

This command compiles a bounded, explicit event score. `--preview` prints
the timing and size. The JSON selects 6 or 12 voices and has events with
integer duration, period, voice and volume fields.

The compiler rejects more than 512 events, values outside the device ranges,
scores in which time does not advance and 32 consecutive zero-duration
events. The generated arrays are borrowed near data. The audio demo uses this
score. Tick durations use the configured device cadence, not host seconds or
display frames.

### Pattern songs

`ti_song_start(song, size, loop)` plays a pattern song, which repeats bars
and does not list every note. Each track has an order of pattern numbers.
The song goes back to its loop position, or stops after the last position
when `loop` is 0.

Track i plays on the i-th voice reserved when the song starts, counted from
voice 0. Tracks past the reserved voices do not play. Thus a Mockingboard can
play the first tracks of a song for a Phasor. The song bytes stay borrowed
like an event array, and `ti_music_stop` stops the two kinds of score.

All tracks share one row clock. A row lasts the ticks per row of the song, an
8.8 fixed-point number. Thus a row of 4.93 ticks advances 4 or 5 whole ticks
and keeps the tempo. At each row, a track whose note is finished reads its
next note, rest or hold.

A note sets the tone period and starts at the volume of the track. After
each `decay` ticks it falls one level, down to the floor of the track, so
repeated notes stay separate. Decay 0 holds the volume. A hold keeps the
current sound, and a rest silences the voice.

The decay runs before the row, so a note starts at full volume. After a late
update, the decay catches up at most 16 ticks.

Multi-byte values are little-endian:

| Offset | Bytes | Contents |
| --- | --- | --- |
| 0 | 2 | Device ticks per row, 8.8 fixed point: 256..25600 |
| 2 | 1 | Tracks: 1..12 |
| 3 | 1 | Order positions: 1..255 |
| 4 | 1 | Loop position: less than the position count |
| 5 | 1 | Notes in the period table: 1..96 |
| 6 | 1 | Patterns: 1..255 |
| 7 | 3 a track | Volume, decay ticks and floor: 0..15 each |
| then | 2 a note | Base-clock tone periods: 0..2047 |
| then | 2 a pattern | Offset of each pattern from the first byte of the song |
| then | positions a track | Pattern numbers, track 0 first |
| then | | Pattern bytes |

| Pattern byte | Meaning |
| --- | --- |
| `$00`-`$5F` | Play that note of the period table |
| `$60` | Rest |
| `$61` | Hold |
| `$80`+n | The next notes, rests and holds last n+1 rows: 1..64 |
| `$C0`+v, `$D0`+d, `$E0`+f | Set the volume, decay or floor of the track |
| `$FF` | End of the pattern |

The row count, volume, decay and floor continue into the next pattern.
Before it stops the score that plays, `ti_song_start` checks the whole song.
It checks the header ranges, that the tables end inside the song and that
every order names a pattern.

It also checks that every pattern starts after the tables and ends inside
the song after at least one note, rest or hold, with only the bytes above. A
failure returns `TI_E_RANGE`, and the old score continues. Thus the read of
one row crosses at most one pattern end.

A song outside near memory or shorter than 8 bytes returns `TI_E_ARGUMENT`.
No reserved voice returns `TI_E_RANGE`. A call before `ti_audio_init`
returns `TI_E_STATE`. More than 32 due rows in one update end the song with
`TI_E_TIMING`.

The player is 65C02 assembly. Its checks, 508 bytes, run from CODE. Its
setup, row and decay code, 612 bytes, is in LOWCODE, which the full-game
layout runs from low MAIN. Its state uses 195 bytes of BSS.

The player keeps only the low 16 bits of the shared deadline. This is
sufficient, because a gap of more than 100 ticks stops the score.

`tools/music.py` compiles a song document:

```json
{"song": {"bpm": 152, "rows_per_beat": 8, "loop": 0,
  "tracks": [{"name": "lead", "volume": 12, "decay": 4, "floor": 8, "order": ["a", "a", "b"]}],
  "patterns": {"a": "D#5:2 F#5:2 -:4 G#5:8", "b": "v10 B5:12 ^:4"}}}
```

A pattern is a list of tokens. `NOTE:ROWS` plays a note such as `C4` (MIDI
note 60), `F#3` or `Bb5`. `-:ROWS` rests and `^:ROWS` holds. `vN`, `dN` and
`fN` set the volume, decay and floor. A row count of more than 64 continues
as holds.

Every track needs the same number of positions and of rows. The compiler
writes only the notes in use, in pitch order, with periods for the nominal
1 MHz base clock, from B0 up. Each pattern starts with its row count.
`--report` gives the size and the nominal length.

`tools/midi.py song.mid arrangement.json --output song.json` arranges a
Standard MIDI File into such a document. The arrangement gives a bar range,
the loop bar, the rows per beat and one track for each voice. A track has a
MIDI channel and a chord slot: 0 for the highest note that starts on a row,
1 for the next lower note.

Each track plays one note at a time, and a later note cuts an earlier note.
The tool rounds notes to the nearest row. A note held across a bar line
continues as a hold, and the tool folds notes by octaves into the period
range.

The bar range must have one tempo and one meter. The tool leaves out drums
and unused chord slots. Its report counts the notes left out on each channel
in use. Identical bars become one pattern.

`ti_audio_envelope(mask, period, shape)` selects the AY envelope amplitude
for reserved music voices. The period must not be zero, and the shape is
0..15. The three voices of each chip share its envelope generator.

A trigger must include every voice that already uses the envelope of a chip
that it programs. Otherwise it returns `TI_E_BUSY`. Native Phasor doubles the
period and rejects periods above 32767.

Every trigger writes registers 11, 12 and 13, also for an identical shape.
Register 13 restarts the envelope. `ti_audio_envelope_stop` returns the
selected voices to their score volume. A reserved voice cannot be released
while it uses the envelope.

With Mockingboard speech enabled, voices 0..2 reject envelopes with
`TI_E_BUSY`. The VIA-A alias of the SSI can reset that AY, so the driver
cannot keep its envelope phase. Voices 3..5 support envelopes with speech,
and native Phasor supports envelopes on all voices.

The envelope code is a separate archive module, linked only when a program
calls it. Ducking mutes envelope voices during speech and then restores their
current envelope phase. AY envelopes have no programmable attenuation for
each voice.

## Prepared speech and numbers

```powershell
python tools/speech.py assets/speech.json --preview
python tools/speech.py assets/speech.json --output build/audio_speech.h --symbol ti_demo_speech
```

The JSON has `phrases`, a mapping of uppercase C identifiers to text. It can
have `pronunciations`, a mapping of words to phoneme-name arrays or strings.
The compiler includes an authored English vocabulary in `tools/speech.py`.

An unknown word stops the compiler with a request for an override. The tool
is not a general English text-to-speech engine. Pronunciations approximate
the SSI-263 vowels.

The preview prints the phonemes and an estimated duration at rate 10. It is
not an audio synthesizer. Repeated phonemes stay separate register writes.

The generated near data includes the phrase IDs, the pointer and length
descriptors, a bank descriptor and all number words. Bind the descriptor,
then call `ti_speech_say(id, priority)` or `ti_speech_number(value,
priority)`.

Numbers 0..9999 use ordinary cardinal English without "and": 1001 is "one
thousand one". Each number uses one queue item, also when it joins six words.
The bank and all its data stay borrowed until a new bind or shutdown. Do not
free a resource under them, and do not use banked addresses as near phrase
pointers.

`--no-numbers` writes a phrase-only bank with a NULL number table. STARFALL
uses this option, because its callouts are prepared phrases. The SDK and the
audio demo support every number 0..9999.

A phrase-only bank sets `number_ids` to NULL. The bind and the prepared
phrases work, and spoken numbers return `TI_E_UNAVAILABLE`.

There is one active phrase and four waiting items. Higher priorities run
first, and equal priorities keep their order. A full waiting queue returns
`TI_E_FULL`.

`TI_SPEECH_INTERRUPT | priority` replaces the current phrase only when its
priority is equal or higher. A replacement with a lower priority returns
`TI_E_BUSY`. `ti_speech_stop` cancels the current and the queued phrases and
powers down the SSI.

`ti_speech_voice` sets one of three articulation and amplitude presets, the
pitch and the rate. A voice change cancels pending speech. Optional ducking
lowers music by three volume steps during speech and keeps the effect volume.

The voice configuration leaves the SSI powered down. The first phoneme powers
it up, after the shared interrupt clock is installed and armed.

Native completion sets a ready flag for the foreground in the shared
receiver. A write to the latched inflection register acknowledges the SSI D7
and direct IRQ without a change of the current phoneme.

Mockingboard completion polls CA1, and its interrupt enable stays clear. In
Mockingboard mode, SSI writes alias VIA-A. Thus the driver repairs the port
setup, resets that AY and sends the complete shadow of that chip again. AY
writes use the no-handshake ORA to keep CA1.

A two-second deadline in device ticks finds missing or stuck speech
readiness. The driver then powers down, cancels the queued speech and
returns `TI_E_TIMING`. After that, submissions return `TI_E_UNAVAILABLE`
until audio starts again.

Configured speech is an attempt. It is not a claim that a chip is present.
Essential game messages keep visible captions.

The SSI needs a clock from the Appletini. In standalone ONE//e mode, speech
needs Appletini firmware F1.3.2 or later. F1.3.2 clocks the two SSI engines
from both edges of the virtual PHI0 in standalone mode.

Without a clock, the SSI never starts a phoneme, makes no sound and never
reports a finished phoneme. The first phrase times out after two seconds, and
later submissions return `TI_E_UNAVAILABLE`. Music, effects and the VIA clock
continue to work. `examples/speech_check` shows this condition: its RAW lines
report no finished phoneme.

## Standard input

`ti_input_poll` reads one Apple keyboard character and acknowledges its
strobe. `ti_input_key` takes characters from an eight-character queue. An
empty queue returns `TI_E_UNAVAILABLE`, and an overflow returns `TI_E_NOMEM`.

This is character input, not a simultaneous key matrix. Buttons return the
three standard Apple input bits. Keyboard and buttons work without audio
hardware.

`ti_input_held` returns the newest key while any key is down, or 0, for
hold-to-move controls. The //e keyboard latch keeps the code of the last key,
and bit 7 of `$C010` shows that a key is down.

A read of `$C010` also clears the keyboard strobe. Thus the call reads it only
when no key event is pending. A pending key counts as held and stays for
`ti_input_poll`.

A key that arrives between the two reads loses its strobe. The new code in
the latch then puts it in the queue. A second press of the same key in that
window is not visible, which does not matter for a held key. The //e reports
only one key: hold A, press Space, and the call returns Space until all keys
are up.

Paddle reads need initialized audio, because audio owns the VIA. The read
measures each standard paddle pulse against VIA-B timer 2 at the 1 MHz device
clock. It scales about 11 us for each unit and limits the device time to 4 ms
and the number of polls.

A clock interrupt during the polls delays the detection. Thus a finished
measurement during which the clock counter changed is taken again, up to
three times. A measurement that reached the limit is not taken again: that
axis is absent or out of range.

On the //e, any read or write of $C070-$C07F starts the paddle timers,
RamWorks selector writes at $C073 included. A 558 timer that still runs
ignores a new start. A read started too soon after such an access measures
from the previous start, and the result is too short.

This affects only long readings, which on a stick are right and down. Thus
CPU AUX transfers for bank 0, which include all video publication, do not
write the selector, because it is already 0 by contract. Banked resource
transfers select their bank and restore 0.

Before each start, the read waits until the two paddle inputs are finished.
The wait is limited to 4 ms, counted in T1C-H steps. It lasts at most the
rest of the previous timing, up to about 2.8 ms for a reading of 255. An axis
that never finishes makes the whole read last about 8 ms.

The first read checks that timer 2 moves within 256 bounded reads. A VIA or
model whose timer 2 never counts uses a fallback. The fallback uses windows
that start and end where the T1C-H byte of the running clock decreases by
one, and it interpolates each paddle time from its poll position.

The fallback reads only T1C-H, because a read of T1C-L clears the clock
interrupt flag. Any other T1C-H change inside a window means a stall of at
least 256 device clocks, for example another interrupt, or the T1 reload with
its clock IRQ. Such a window makes the two axes too long, so the read
measures it again, up to three times.

A paddle that still runs at the 4 ms limit reads 255, and the call returns
`TI_E_TIMING`. The other axis stays a valid reading. Thus a disconnected
stick reads 255 on the two axes.

When interrupts disturb every attempt, the call returns `TI_E_BUSY` and does
not change the state. A later read can succeed. Without timer ownership, the
call returns `TI_E_UNAVAILABLE`. These are raw readings: rest position,
travel and polarity are different for each stick.

`ti_stick_read`, in a separate archive member, changes them into
`TI_STICK_UP`, `DOWN`, `LEFT` and `RIGHT` bits. The first reading within
48..207 on the two axes after startup or `ti_stick_recalibrate` becomes the
rest position.

A direction engages past one third of the largest travel seen on that side,
at least 16 units. It releases at three quarters of that threshold. Each side
starts with an assumed travel of 60 units.

After a stick answers, an axis that still runs at the limit counts as full
deflection, and a disturbed read keeps the last directions. Before an answer,
two unfinished axes mean that no stick is present, and the call returns
`TI_STICK_ABSENT`.

After four such reads, the call returns `TI_STICK_ABSENT` for three seconds
of audio ticks without a measurement. Thus an absent stick costs a game
little time. `ti_mouse_read` is a reserved call that always reports
`TI_E_UNAVAILABLE`.

## Checks

`python -m unittest discover -s tests -p test_speech.py -v` tests every
number 0..9999, overrides, unknown words, lengths, identifiers and the
deterministic output.

`python tests/audio_validate.py` builds a cc65 driver test and runs its 65C02
instructions against independent VIA, AY and SSI register models. It checks
the two personalities, clock IRQ delivery at different CPU and device clock
ratios, queue limits, priorities, cancellation and repeated phoneme writes.
It also checks timeouts, reservations, envelope ownership and restart writes,
input, clean silence, the restored zero page and the ProDOS IRQ allocation
and removal.

The same test checks held keys, a key that arrives between the two reads,
calibrated stick directions at rest and in each direction, and the no-stick
wait, during which no paddle access occurs. It checks fixed steps from a
scripted clock and a two-voice request that updates only chip 0. It injects a
failed deallocation, checks an explicit retry, and checks the retained-code
and key-retry path of startup.

The test plays the pattern songs in `tests/audio_songs.json` through the
linked player. Python builds the AY registers again from the recorded writes.
It checks the notes, the rest, the steady row spacing, the loop position, the
decay to the floor at one level each tick and the third track.

It also checks a song on one reserved voice, which plays only its first track
and ends silent, and an update with more than 32 due rows, which returns
`TI_E_TIMING`. Twelve damaged copies of a song return `TI_E_RANGE`. A NULL or
short song returns `TI_E_ARGUMENT`, and a song before initialization returns
`TI_E_STATE`. The ProDOS dispatcher of this test is a test fixture.

`python -m unittest discover -s tests -p test_music.py -v` checks the two
compilers and the MIDI arranger on the host. `python tests/test_input.py`
compiles the stick and step code for the host. It checks the thresholds, the
hysteresis, the travel adaptation and 20,000 random step frames against
reference accounting.

`python tests/audio_native_validate.py --cc C:/msys64/ucrt64/bin/gcc.exe`
boots the packaged audio demo with the installed local motherboard and slot
ROMs and real ProDOS, without MLI traps. It checks the two personalities in
`vtw33` and `turbo-f122`. It checks the interrupt registration and removal,
the phoneme-ready progression, AY silence, powered-down speech and the return
to Bitsy Bye with no remaining IRQs.

The results and screenshots are in `build/audio_native/`. The NTSC Apple bus
of the model is 65 clocks per 63.695246 us, about 1.020484 MHz. Thus the
default configuration gives about 102 ticks per model second in the two CPU
profiles. A test with a configured `via_hz` of 1020484 gives about 100 ticks.
