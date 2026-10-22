# Audio, speech and input

The driver uses the existing slot-4 Appletini Mockingboard/Phasor interfaces.
It does not change slots or require private services. The caller explicitly
grants exclusive ownership of both VIAs, their timers, all AYs and both speech
sockets. Entry personality is Mockingboard; shutdown restores that personality.
Do not initialize while another driver owns this card. Enabled VIA interrupts
produce `TI_E_BUSY`; a DDR save/write/read/restore probe rejects an absent VIA.
This probe is assembly because cc65 2.19 optimizes some fixed-address C volatile
store/read sequences. Pin-changing probes require the exclusive ownership grant.

`ti_audio_init` selects six Mockingboard voices or attempts native Phasor.
The latter probes an independent second AY and degrades to six voices if the
card aliases it. Native periods are doubled to retain pitch.

`ti_audio_config.voices` limits the driver to fewer voices, rounded up to
whole AY chips of three; 0 keeps every voice. Initialization still silences
every chip, but later updates compare and write only the chips that serve a
voice, and `ti_audio_voices` reports the result. Voices above the count are
out of range. The per-update register flush indexes all chips' registers as
one flat array. Compared with the earlier two-dimensional indexing it is
less than half the code, and the unchanged target-model audio checks ran in
less than half the 65C02 instructions. This is capability
evidence, not identification of the firmware release. Board baseline remains
F1.3.1; real pitch, speech quality and timing at both CPU modes are hardware gates.

## Device cadence and ownership

VIA-B timer 1 runs at the device cadence, independent of CPU speed. Configuration
`via_hz` accepts an explicitly known/calibrated 100000..4000000 Hz source;
zero assumes nominal 1000000 Hz. Its latch is `via_hz / 100 - 2` and the
free-running period is latch+2 source clocks. `TI_AUDIO_TICKS_PER_SECOND` is
**nominally** 100: physical accuracy depends on the configured source, not the
CPU profile. `ti_audio_source_hz` and `ti_audio_tick_divisor` expose the assumed
source and actual integer divisor. No emulator profile silently changes this
configuration. Board clock calibration remains pending. The assembly
ProDOS interrupt receiver increments a 32-bit tick counter and acknowledges the
timer. It never calls C, borrows zero page, maps AUX or calls ProDOS. Foreground
reads atomically snapshot the counter. Games can accumulate 30 simulation steps
per 100 device ticks, which `ti_steps_begin` and `ti_steps_due` in
[timing.h](../include/libtini/timing.h) do; they must not use display
observations as elapsed time.
For calibrated elapsed seconds, use `ticks * divisor / source_hz` with wide
arithmetic. The game's 100-to-30 accumulator is a nominal design cadence until
the board's VIA source has been measured and its configuration set accordingly.

Installation/removal use standard ProDOS MLI `$40`/`$41`, rather than replacing
an IRQ vector. The receiver follows the [ProDOS interrupt convention](https://prodos8.com/docs/techref/adding-routines-to-prodos/):
CLD first, RTS with carry clear when claimed, carry set otherwise. Hardware is
enabled after successful allocation and disabled before deallocation. Both MLI
calls temporarily restore the saved ProDOS AUX workspace when an SHR screen is
active, using the same video loan as storage. Whole-application cleanup restores
that screen's OS workspace before deallocating the interrupt receiver.
Startup cleanup calls the registered shutdown hook before freeing memory or returning.
Shutdown silences AYs, powers down SSI sockets, removes the receiver and restores
saved VIA port, DDR, ACR and PCR configuration. It restores the entry IRQ policy.
External running timers/audio are excluded by ownership; their phase and prior
PSG score are not saved. The application supplies sufficient hardware stack
space for ProDOS dispatch in addition to its own foreground depth.

If MLI deallocation fails, shutdown returns `TI_E_IO`, invalidates the clock and
retains ownership, its cleanup hook and executable callback. Hardware is already
silent and its interrupts disabled; the caller may retry shutdown.
After this error the permitted audio operation is another shutdown attempt;
do not resume the clock, reconfigure voices or submit new playback.
Startup refuses to free the application or issue QUIT after a failed cleanup. It displays
`CLEANUP ERROR / KEY RETRIES / CODE RETAINED` and waits for a key before retrying.
This retains callback memory; it cannot repair a damaged ProDOS interrupt table.

IRQ ticks are reliable only while IRQs can be serviced within each 10 ms timer
period. SDK bank bursts are bounded below that interval even at a 1 MHz CPU;
this is an instruction budget, not board timing proof. An arbitrary external
SEI or disk driver can hide multiple periods, which a VIA flag cannot count.
`ti_audio_mark_gap` therefore invalidates the clock, cancels speech/effects and
mutes music before blocking work. `ti_audio_resume_clock` rebases service and
resumes the score; intervening ticks are not elapsed simulation time. Standard
SDK storage brackets its MLI operations with these hooks. Callers must do the
same around other blocking/IRQ-masked work and rebase their fixed-step loop.
They must not claim an absolute wall clock across such a gap.
The gap hook disables this driver's T1 interrupt, powers down speech and
acknowledges native SSI completion before entering slot firmware. A VIA read in
an IRQ can otherwise change C8 ROM ownership while a SmartPort MLI is running.
Resume arms a full new timer period without clearing the accumulated counter.
Ticks deliberately stop during the declared gap; they do not measure its time.
While paused, the registered receiver returns unclaimed before any slot I/O,
including when ProDOS dispatches another device's interrupt.

`ti_audio_update` is foreground and non-reentrant. It handles bounded event
catch-up, effects and one speech phoneme, then flushes grouped AY shadows.
It compares and writes the shadows only when a device tick has passed since
the previous call, or when a tone, rest, speech or SSI write asks for it;
further calls within the same tick write nothing. More than one second
between services, or more than 32 due score events or song rows in one
call, returns `TI_E_TIMING` and silences/cancels safely. A clock gap remains
explicit until resumed. Audio, input and all memory mappings retain the normal
MAIN/bank-zero entry contract. No interrupt handler may call these C APIs.

## Score and effects

Music events contain a duration in 100 Hz ticks, a base-clock tone period
0..2047, voice and volume 0..15. Events apply in sequence; duration zero permits
several voices at one time. Arrays remain borrowed until stopped/shutdown.
Reserve a voice mask with `ti_audio_reserve` (default voices 0..2). Music may
use only reserved voices; effects may use only other voices. Effects expire
on device ticks and reject a lower priority replacement with `TI_E_BUSY`.
Reservation changes reject removing a voice that the active borrowed score
plays or reserving a voice currently playing an effect; stop those users first.
`ti_audio_effect_voice(n)` returns the voice number of the nth voice, from 0,
that the reservation leaves to effects, or 255, which `ti_audio_effect`
rejects with `TI_E_RANGE`, when fewer are left. With music on voices 0..1 of a
Mockingboard, effect voice 0 is voice 2; with music on voices 0..7 of a
Phasor, it is voice 8. One table of effect voices then suits either card.
Larger scores can select a six-voice arrangement instead of assuming twelve.
The event player and the song player below are separate archive modules: a
program links only the one it starts.

`tools/music.py assets/music.json --output build/audio_music.h --symbol
ti_demo_music --report build/audio_music.json` compiles a bounded, explicit
event score; `--preview` prints timing/size information. JSON selects voices
6 or 12 and events with integer duration, period, voice and volume fields.
It rejects more than 512 events, invalid device ranges, scores without time
progress and 32 consecutive zero-duration events. Generated arrays remain
borrowed near data. The audio demo uses this generated score. Tick durations
use the explicitly configured device cadence, not host seconds or display frames.

### Pattern songs

`ti_song_start(song, size, loop)` plays a pattern song, which repeats bars
instead of listing every note. Each track has an order of pattern numbers;
the song loops to its loop position, or stops after the last position when
`loop` is 0. Track i plays on the i-th voice reserved when the song starts,
counting from voice 0. Tracks beyond the reserved voices are not played, so a Mockingboard can
play the first tracks of a song arranged for a Phasor. The song bytes stay
borrowed like an event array, and `ti_music_stop` stops either kind.

All tracks share one row clock. A row lasts the song's ticks per row, an
8.8 fixed-point number, so a row of 4.93 ticks advances 4 or 5 whole ticks
and keeps the tempo. At each row, a track whose note has ended reads its
next note, rest or hold. A note sets the tone period and starts at the
track's volume. Each `decay` ticks it falls one level, down to the track's
floor, so repeated notes stay separate; decay 0 holds the volume. A hold
keeps the current sound, and a rest silences the voice. Decay runs before
the row, so a note starts at full volume. After a late update the decay
catches up at most 16 ticks.

Multi-byte values are little-endian:

| Offset | Bytes | Contents |
| --- | --- | --- |
| 0 | 2 | Device ticks per row, 8.8 fixed point: 256..25600 |
| 2 | 1 | Tracks: 1..12 |
| 3 | 1 | Order positions: 1..255 |
| 4 | 1 | Loop position: below the positions |
| 5 | 1 | Notes in the period table: 1..96 |
| 6 | 1 | Patterns: 1..255 |
| 7 | 3 a track | Volume, decay ticks and floor: 0..15 each |
| then | 2 a note | Base-clock tone periods: 0..2047 |
| then | 2 a pattern | Offset of each pattern from the song's first byte |
| then | positions a track | Pattern numbers, track 0 first |
| then | | Pattern bytes |

| Pattern byte | Meaning |
| --- | --- |
| `$00`-`$5F` | Play that note of the period table |
| `$60` | Rest |
| `$61` | Hold |
| `$80`+n | Later notes, rests and holds last n+1 rows: 1..64 |
| `$C0`+v, `$D0`+d, `$E0`+f | Set the track's volume, decay or floor |
| `$FF` | End of the pattern |

The row count, volume, decay and floor carry over into the next pattern.
Before it stops the playing score, `ti_song_start` checks the whole song:
the header ranges above; that the tables end inside the song; that every
order names a pattern; and that every pattern starts after the tables and
ends inside the song after at least one note, rest or hold, using only the
bytes above. A failure returns `TI_E_RANGE` and the old score plays on.
A song outside near memory or shorter than 8 bytes returns `TI_E_ARGUMENT`;
no reserved voice returns `TI_E_RANGE`; before `ti_audio_init`,
`TI_E_STATE`. Reading one row therefore crosses at most one pattern end.
More than 32 due rows in one update end the song with `TI_E_TIMING`.

The player is 65C02 assembly. Its checks, 508 bytes, run from CODE. Its
setup, row and decay code, 612 bytes, is in LOWCODE, which the full-game
layout runs from low MAIN; its state takes 195 bytes of BSS. It keeps only the low 16 bits of the shared deadline, which is
enough because a gap over 100 ticks stops the score.

`tools/music.py` compiles a song document:

```json
{"song": {"bpm": 152, "rows_per_beat": 8, "loop": 0,
  "tracks": [{"name": "lead", "volume": 12, "decay": 4, "floor": 8, "order": ["a", "a", "b"]}],
  "patterns": {"a": "D#5:2 F#5:2 -:4 G#5:8", "b": "v10 B5:12 ^:4"}}}
```

A pattern is a list of tokens. `NOTE:ROWS` plays a note such as `C4` (MIDI
note 60), `F#3` or `Bb5`; `-:ROWS` rests and `^:ROWS` holds. `vN`, `dN`
and `fN` set volume, decay and floor. A row count over 64 continues as
holds. Every track needs the same number of positions and of rows. The
compiler emits only the notes used, in pitch order, with periods for the
nominal 1 MHz base clock, B0 and up. Each pattern starts with its row
count. `--report` gives the size and the nominal length.

`tools/midi.py song.mid arrangement.json --output song.json` arranges a
Standard MIDI File into such a document. The arrangement names a bar range,
the loop bar, the rows per beat and one track per voice: a MIDI channel and
a chord slot, 0 for the highest note that starts on a row, 1 for the next
lower one. Each track plays one note at a time, and a later note cuts an
earlier one. Notes are rounded to the nearest row. A note held across a
bar line continues as a hold, and notes are folded by octaves into the
period range. The bar range must have one tempo and one meter. Drums and
unused chord slots are left out; the printed report counts the notes left
out on each channel used. Identical bars become one pattern.

`ti_audio_envelope(mask, period, shape)` selects AY envelope amplitude for
reserved music voices. Period must be nonzero and shape is 0..15. The three
voices on each chip share its envelope generator: a trigger must include every
existing envelope user on a chip it reprograms, or it returns `TI_E_BUSY`.
Native Phasor doubles the period and rejects periods above 32767. Every trigger
writes registers 11, 12 and 13, including repeated identical shapes; register 13
restarts the envelope. `ti_audio_envelope_stop` returns selected voices to their
score volume. Reserved voices cannot be released while using the envelope.
With Mockingboard speech enabled, voices 0..2 reject envelopes with `TI_E_BUSY`:
SSI's VIA-A alias can reset that AY, so its envelope phase cannot be retained.
Voices 3..5 support envelopes alongside speech; native Phasor supports all voices.
Envelope code is a separate archive module, linked only when called. Ducking
mutes envelope voices during speech and restores their current envelope phase
afterward, since AY envelopes have no per-voice programmable attenuation.

## Prepared speech and numbers

```powershell
python tools/speech.py assets/speech.json --preview
python tools/speech.py assets/speech.json --output build/audio_speech.h --symbol ti_demo_speech
```

The JSON has `phrases`, a mapping of uppercase C identifiers to text, and
optional `pronunciations`, a mapping of words to phoneme-name arrays/strings.
The compiler includes an explicitly authored initial English vocabulary in
`tools/speech.py`. Unknown words fail with a request for an override; this is
not an unrestricted English text-to-speech engine. Pronunciations approximate
SSI-263 vowels and require listening on the board before claiming quality.
Preview prints phonemes and an estimated duration at rate 10; it is not an
audio synthesizer. Repeated phonemes remain separate register writes.

Generated near data includes phrase IDs, pointer/length descriptors, a bank
descriptor and all numeric words. Bind the descriptor, then call
`ti_speech_say(id, priority)` or `ti_speech_number(value, priority)`. Numbers
0..9999 use ordinary cardinal English without "and": 1001 is "one thousand
one". Each number occupies one queue item even when it joins six words.
The bank and all data remain borrowed until rebind/shutdown; do not free an
underlying resource or use banked addresses as near phrase pointers.

`--no-numbers` emits a phrase-only bank with a NULL numeric table. STARFALL
uses this option because its callouts are prepared phrases; the SDK and audio
demo still support every number 0..9999. Binding a phrase-only bank is valid;
runtime number requests then return `TI_E_UNAVAILABLE`.
An optional phrase-only bank sets `number_ids` to NULL; binding and prepared
phrases still work, while spoken numbers return `TI_E_UNAVAILABLE`.

There is one active phrase and four waiting items. Higher priorities run first;
equal priorities retain order. A full waiting queue returns `TI_E_FULL`.
`TI_SPEECH_INTERRUPT | priority` replaces the current phrase only when its
priority is at least as high; a lower priority replacement returns `TI_E_BUSY`.
`ti_speech_stop` cancels the current and queued phrases and powers down SSI.
Three articulation/amplitude presets, pitch and rate are configurable through
`ti_speech_voice`; voice changes cancel pending speech. Optional ducking lowers
music three volume steps during speech and preserves effect volume.
Voice configuration leaves SSI powered down; submission of the first phoneme
powers it up after the shared interrupt clock has been installed and armed.

Native completion sets a foreground-ready flag in the shared receiver. Writing
the latched inflection register acknowledges SSI D7/direct IRQ without changing
the current phoneme. Mockingboard completion polls CA1; its interrupt enable is
kept clear. SSI writes alias VIA-A in Mockingboard mode, so the driver repairs
the port setup, resets its AY and fully resends that chip's shadow. AY writes
use no-handshake ORA to preserve CA1. A two-second device-tick deadline detects
missing/stuck speech readiness, powers down, cancels queued speech and returns
`TI_E_TIMING`. Further submissions return `TI_E_UNAVAILABLE` until re-init.
Configured speech is an attempt, not a chip-presence claim. Essential game
messages retain visible captions.

Speech needs the Apple's Q3 clock. Appletini F1.3.1 clocks both SSI engines
only from the physical Q3 pin. In standalone ONE//e mode no motherboard drives
that pin, and any Apple clock edge would end the session. The SSI then never
starts a phoneme, makes no sound and never reports one finished. The first
phrase times out after two seconds and later submissions return
`TI_E_UNAVAILABLE`. On the board in that mode, music, effects and the VIA
clock kept working. `examples/speech_check` shows the condition: its RAW
lines report no finished phoneme.

## Standard input

`ti_input_poll` reads one Apple keyboard character and acknowledges its strobe.
`ti_input_key` drains an eight-character queue; an empty queue reports
`TI_E_UNAVAILABLE`, overflow reports `TI_E_NOMEM`. This is character input,
not a simultaneous key matrix. Buttons return the three standard Apple input
bits. Keyboard/buttons work without audio hardware.

`ti_input_held` returns the newest key while any key is down, or 0, for
hold-to-move controls. The //e keyboard latch keeps the last key's code and
`$C010` reports any-key-down in bit 7. Reading `$C010` also clears the
keyboard strobe, so the call reads it only when no key event is pending; a
pending key counts as held and stays for `ti_input_poll`. A key that arrives
between the two reads would lose its strobe; its new code in the latch then
queues it. The same key again in that window cannot be told apart, which is
harmless for a held key. The //e reports one key only: hold A, tap Space and
the call returns Space until every key is up.

Optional paddle sampling requires initialized audio, which owns the VIA. It
measures each standard paddle pulse against VIA-B timer 2 at the 1 MHz device
clock, scales about 11 us per unit and bounds both device time (4 ms) and
iterations. A clock interrupt during the polls would delay detection, so a
finished measurement during which the clock counter changed is taken again,
up to three times. A measurement that reached the limit is not repeated:
that axis is absent or beyond the range.

On the //e, any read or write of $C070-$C07F strobes the paddle timers. That
includes RamWorks selector writes at $C073. A 558 timer that is still running
ignores a strobe. A read triggered too soon after such an access therefore
measured a long paddle from the earlier strobe, and the result came out short
by the time between the two. Only long readings were affected, which on a
stick are right and down. CPU AUX transfers for bank 0, which include all
video publication, no longer write the selector: it is already 0 by
contract. Banked resource transfers still select their bank and restore 0.
Before every trigger the read also waits until both paddle inputs have
finished, bounded by 4 ms counted in T1C-H steps. The wait lasts at most the
rest of the earlier timing, up to about 2.8 ms for a reading of 255. An axis
that never finishes makes the whole read last about 8 ms.

The first read
checks that timer 2 moves within 256 bounded reads. A VIA or model whose timer
2 never counts uses a fallback instead: windows that start and end where the
running clock's T1C-H byte steps down by one, with each paddle time
interpolated from its poll position. Only T1C-H is read, because reading
T1C-L would clear the clock interrupt flag. Any other T1C-H change inside a
window means a stall of at least 256 device clocks, such as another
interrupt, or the T1 reload with its clock IRQ. Such a window would inflate
both axes, so it is measured again, up to three times.

A paddle still running at the 4 ms limit reads 255 and the call returns
`TI_E_TIMING`; the other axis remains a valid reading. A disconnected stick
therefore reads 255 on both axes. When interrupts disturb every attempt the
call returns `TI_E_BUSY` and leaves the state unchanged; a later read can
succeed. Absent timer ownership returns `TI_E_UNAVAILABLE`. These are raw
readings: rest position, travel and polarity vary between sticks.

`ti_stick_read` turns them into `TI_STICK_UP`, `DOWN`, `LEFT` and `RIGHT`
bits, in a separate archive member. It takes the first reading within
48..207 on both axes after startup or `ti_stick_recalibrate` as the rest.
A direction engages beyond a third of the furthest travel seen on that side,
at least 16 units, and releases at three quarters of that threshold. Each
side starts with an assumed travel of 60 units. Once a stick has answered,
an axis still running at the limit counts as full deflection and a disturbed
read keeps the last directions. Before that, both axes unfinished means no
stick: the call returns `TI_STICK_ABSENT`. After four such reads it returns
`TI_STICK_ABSENT` for three seconds of audio ticks without measuring, so an
absent stick costs a game little. Board validation of real sticks remains
pending.
No mandatory mouse is installed; `ti_mouse_read` explicitly reports unavailable.

## Checks

`python -m unittest discover -s tests -p test_speech.py -v` exercises every
number 0..9999, overrides, unknown words, lengths, identifiers and deterministic
generation. `python tests/audio_validate.py` builds an actual cc65 driver test
and runs its 65C02 instructions against independent VIA/AY/SSI register models.
It checks both personalities, clock IRQ delivery at differing CPU/device ratios,
queue limits, priorities, cancellation, repeated phoneme writes, timeouts,
reservations, envelope ownership/retrigger writes, input, clean silence, restored
ZP and ProDOS IRQ allocation/removal. It also checks held keys, including a
key arriving between the two reads; calibrated stick directions at rest and
in each direction; the no-stick wait, during which no paddle access occurs;
fixed steps from a scripted clock; and a two-voice request that updates only
chip 0. It plays the pattern songs in `tests/audio_songs.json` through the
linked player. Python rebuilds the AY registers from the recorded writes and
checks the notes, the rest, steady row spacing, the loop position, decay to
the floor at one level a tick and the third track. It also checks a song
on one reserved voice that plays only its first track and ends silent, and
an update with more than 32 due rows, which returns `TI_E_TIMING`. Twelve
damaged copies of a song return `TI_E_RANGE`, a NULL or short song
`TI_E_ARGUMENT`, and a song before initialization `TI_E_STATE`.
`python -m unittest discover -s tests -p test_music.py -v` checks both
compilers and the MIDI arranger on the host. `python tests/test_input.py` compiles the stick and step code for the
host and checks its thresholds, hysteresis, travel adaptation and 20,000
randomized step frames against reference accounting. It injects a failed deallocation, checks an
explicit retry, and checks startup's retained-code/key-retry path.
Its ProDOS dispatcher is a test fixture; it does not establish real ROM boot,
speech synthesis, hardware timer drift or board output at 33 MHz/TURBO.

`python tests/audio_native_validate.py --cc C:/msys64/ucrt64/bin/gcc.exe` boots
the packaged audio demo with installed local motherboard/slot ROMs and actual
ProDOS, without MLI traps. It checks both personalities in `vtw33` and historical
`turbo-f122`, actual interrupt registration/removal, phoneme-ready progression,
AY silence, powered-down speech, and Bitsy Bye return with no remaining IRQs.
Evidence and screenshots are in `build/audio_native/`. The model's NTSC Apple
bus is 65 clocks per 63.695246 us, about 1.020484 MHz. Default configuration
therefore gives about 102 ticks per modeled second in both CPU profiles.
An additional explicitly configured 1020484 Hz test gives about 100; this is a
test of the public calibration input, not a board calibration. The separate
speech synthesizer is absent; these results do not prove audible pronunciation.
