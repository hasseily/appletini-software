# Milestone 11, part `fxconv`: the effects converter (S4)

Part `fxconv` of wave 1 ([`docs/SCREENS.md`](../SCREENS.md) 7.3), after
[`tools/sound/README.md`](../../tools/sound/README.md) "Effects (S4)":
"Sources", "The converter", "The ten tuned effects"; SCREENS.md 3 and
4.5. Host only. 2026-10-01. Labels as in `NATIVE.md`: [M] measured,
[R file:line] read, [A] assumed.

## 1. What was built

| File | What |
| --- | --- |
| `tools/sound/fxconv.py` | The converter: one script a game sound, in `sfxenum_t` order; the script format version 1; the ring quantization; the bank file `SFX.1` (bank 103) with its directory and `VATT`; also `SFXAUTO.1` (every script automatic, for `fxdisk`'s T key) and the listing `SFX.lst`. Its docstring is the format's reference |
| `tools/sound/fxmodel.py` | The second model, written apart: its own WAD reader, DS and DP readers, the game sounds read from upstream's `offsets.inc`, its own copy of the divisor table, its own `fxtune.txt` reader; the level by a threshold table on the mean square (no logarithm), roundings with exact fractions, the budget by counting bytes (no encoder). Also the AY log of a script (chip 3, voice A, PAL tempo) and its render by `ayrender.py` |
| `tools/sound/fxdec.py` | The third decoder: a script's bytes to per-tick states, strict (header length, opcodes, ranges, the noise flag); `SFX.1`'s directory |
| `tools/sound/fxtune.txt` | The ten tuned effects' first versions |
| `src/native/m11/fxconv.mk` | `make -f src/native/m11/fxconv.mk` (SFX.1), `fxconv-renders`, `fxconv-clean`; its names all start with `FXCONV_`/`fxconv`, and it keeps an including makefile's default goal, so `m11.mk` can include it |
| `tests/wip_test_m11_fxconv.py` | Hand-made encoder/decoder cases, the checkpoint, the planted bugs |

Build output: `build/native/m11/fxconv/` (`SFX.1`, `SFXAUTO.1`,
`SFX.lst`, `renders.txt`, `renders.list`, `renders.stamp`);
`build/sound/fx/` (124 files: `NAME.ay` and `NAME.wav` of the 52
automatic scripts and `NAME.tuned.ay`/`.wav` of the ten tuned, 9.7 MB).
`fxconv-clean` deletes the renders by name from `renders.list`, never by
wildcard.

## 2. Decisions where the design left a choice

Each is in `fxconv.py`'s docstring and mirrored, by separate code, in
`fxmodel.py`; R-FX1 below asks for the README to say the same.

1. **DS padding.** The first and last 16 samples of a DS lump are
   dropped, as DMX does [R: Chocolate Doom `src/i_sdlsound.c`,
   `CacheSFX`: "The DMX sound library seems to skip the first 16 and last
   16 bytes of the lump"].
2. **Ticks.** Tick t is the samples `[t*rate//140, (t+1)*rate//140)`.
3. **Tone.** The published divisor table (section 4), period =
   round(2,031,250 × D / (16 × 1,193,181)); a tone byte of 0, or 128 and
   up, is silence (Chocolate Doom's bound check).
4. **Level.** RMS of (sample - 128); 0 dB is a full-scale sine (mean
   square 8,192); attenuation round(-20 log10(ms / 8192)) half-dB units,
   0-80; 80 when the tick has no DS samples.
5. **Noise: the "no tone" rule (a change from the README's table).** The
   README turns noise on only above 2,500 zero crossings a second. On
   `DOOM1.WAD` that leaves most DS sound past the DP's tones silent: the
   game's samples are mostly below 1,250 Hz, so the decay of `PISTOL`
   (ticks 27-55), `SHOTGN` (47-111) and `BAREXP` (118-231) would vanish
   [M: crossing rates of the three, this part]. So the noise is on in a
   tick that passes 2,500 crossings a second **or has no tone after the
   quantization**; its period is round(PSG × n / (32 × c × rate)), 1-31,
   31 with no crossing. This is native-sound 4.5's prototype rule
   ("noise if zcr > 2500 or (not tone and level)",
   `build/native-design/sound/sfx.py`), taken after the quantization so
   that a PC-speaker warble held by the tone rule (below) does not turn
   into tone and noise alternating.
6. **Silence.** A tick at attenuation 80, or with neither tone nor
   noise, is the state (0, 80, 0): an AY channel with both mixer bits off
   holds its level as a constant (a click). The silent ticks at the end
   are dropped.
7. **Length and trim (a change).** The longer lump's length, then the
   tail after the last tick **within 40 units (20 dB) of the effect's
   loudest tick** is cut. The README's "a tail below 40 attenuation
   units" read as absolute fails `ITEMUP`, whose loudest tick is 44 (22
   dB down) [M].
8. **Quantization stages.** The README names the rules (level changes
   under an AY step dropped, one-tick tones dropped) but not how far to
   go. Each script takes the first of 11 stages (L, H, N) whose every 42
   ticks fit 128 bytes: an attenuation change under L half-dB units is
   dropped unless from or to 80; a tone is held at least H ticks (a
   change is dropped while the current tone is younger); a noise period
   change under N is dropped unless it turns the noise on or off. Stages
   (0,1,0), (3,1,1), (3,2,2), (6,2,2), (6,2,4), (10,2,4), (10,3,6),
   (16,3,8), (16,4,12), (24,4,16), (24,6,31). Stage counts on
   `DOOM1.WAD`: 0: 4, 1: 6, 2: 8, 3: 14, 4: 1, 5: 8, 6: 7, 7: 2, 8: 1
   (`SLOP`), 9: 1 (`SGTDTH`) [M]. The converter fails naming the effect
   when no stage fits (tested with a synthetic tuned script).
9. **The budget's count.** The bytes the player reads while running
   ticks w to w+41, for every w: the header at tick 0, a set and the wait
   after it at the wait's first tick, the end (`$FF`) at the tick after
   the last. The ring holds 128 B; so a ring filled with the next 128
   bytes covers 300 ms, header included (the safe reading if `fx_service`
   copies the header into the ring).
10. **The format's open points.** A voice starts at (tone 0, attenuation
    80, noise 0); a set carries the fields that changed, in the order
    tone, attenuation, noise; a run equal to the state before (only a
    silent start) has no set. **Bit 3** ("the end follows the set"): one
    wait byte follows the set's fields, and the script ends when that
    wait expires (no `$FF`); the encoder uses it when the last run has a
    set and lasts 64 ticks or less, else ends with `$FF`. The header's
    third and fourth bytes are the length of the steps after the header.
11. **`SFX.1`.** Loaded at `$0200` of bank 103: the directory, 52 × 4 B
    (u16 bank address, u16 length of the script with its header) in
    `sfxenum_t` order from `$0200`; `VATT` (128 B, `tables.py`'s
    `ATTENUATION_OF_VALUE`: 40 log10(127 / v) dB in half-dB units, 80 at
    v = 0, the music's law) at `$02D0`; the scripts from `$0350`.
12. **Tuned text.** `att=` takes 0-40 dB in 0.5 dB steps (40 dB is the
    silent 80); `tone=HZ` is rounded to the nearest period with exact
    fractions; a script starts at (tone off, 40 dB, noise off).

## 3. Checkpoint

Commands (from `demos/doom_gs`):

    make -f src/native/m11/fxconv.mk fxconv fxconv-renders
    python3 -m unittest discover -s tests -p wip_test_m11_fxconv.py -v

`python3 tools/testpar.py tests/wip_test_m11_fxconv.py` does not run it:
`testpar.py` only knows `test*.py` modules (R-FX3). The test passes on
Python 3.9.6, 3.11.13 and 3.14.6 (15 tests, about 1.3-2.3 s, with
`-W error::ResourceWarning`).

| Item | Result |
| --- | --- |
| All 52 game sounds convert | Yes; the names equal `offsets.inc`'s `CONST_SFX_*` (the model reads them there) and the order of `sfxPriority`'s comment [R `s_sound65.s:1278-1285`] |
| Every automatic script = `fxmodel.py` per tick | 52 of 52 (`SFXAUTO.1`) and the 42 automatic ones of `SFX.1`, decoded by `fxdec.py`; the converter's stage equals the model's for each |
| The ten tuned scripts = `fxtune.txt` | 10 of 10, flag bit 0 set, decoded states equal the model's own reading of `fxtune.txt`; no other script has the flag |
| 42 ticks within 128 B | Every script of `SFX.1` and `SFXAUTO.1`, counted by the test's own walker on the bytes; worst 128 (`RXPLOD`), tuned worst 87 (`POSACT`) |
| `SFX.1` in one bank, read back | 11,385 B of 48,640 (the scripts 11,049 B); the directory's addresses consecutive from `$0350`, the scripts read back equal, `VATT` equal to the music's law |
| Renders | 62 WAVs in `build/sound/fx/` (52 automatic, 10 tuned), from `fxmodel.py`'s AY log by `ayrender.py` |
| PC speaker table | Section 4 |
| `tests/test_sound_*` | Unchanged (not edited), green: `python3 tools/testpar.py --jobs 2` on the seven modules, 152 tests, 0 failures |

Sizes and rates [M, `DOOM1.WAD`]:

| | Value | Budget |
| --- | ---: | ---: |
| `SFX.1` (10 tuned) | 11,385 B | about 15 KB, one bank (48,640 B) |
| `SFXAUTO.1` | 12,850 B | (one bank) |
| Automatic scripts, all 52 | 12,514 B for 44.2 s: 283 B/s on average | under about 420 B/s (README) |
| Worst 42 ticks | 128 B (427 B/s for 300 ms) | 128 B |
| AY writes an interrupt, one voice (model's log, PAL) | automatic 1.43, tuned 1.06 | README's cost assumes 1.6 |
| Longest effect | `BAREXP`, 232 ticks (1.66 s) | |

## 4. The PC speaker's divisor table

The table is now **read**, not reconstructed: Chocolate Doom,
`src/i_pcsound.c`, `static const uint16_t divisors[]` (128 entries, 0
then 6818 ... 179; GPL-2 or later, Simon Howard; its comment: "Use the
tone -> frequency lookup table. See pcspkr10.zip for a full discussion
of this"), with `#define TIMER_FREQ 1193181` and `freq = TIMER_FREQ /
divisors[tone]` [R: the file on GitHub, `chocolate-doom/chocolate-doom`,
branch `master`, fetched 2026-10-01; not kept offline]. `fxconv.py` and
`fxmodel.py` each hold a copy (data, not code). The reconstruction
of native-sound 4.5 (quarter tones from 175 Hz) agrees within 7.4 cents
(tone 4), -2.5 cents on average; neighbouring entries are 44-56 cents
apart [M: the test checks under 8 cents and 40-60]. The game sounds use
tone bytes 1-93 [M]. The AY period's rounding adds at most 8.9 cents
(0.52 %) [M].

The fetch was over the network: if the owner wants it checked offline,
a copy of `i_pcsound.c` (or `pcspkr10.zip`) in `build/reference/` would
let a test compare the table directly; meanwhile the test compares the
two copies and the reconstruction.

## 5. Planted bugs

Each is a text replacement in a scratch copy of `fxconv.py` (the test's
`PLANTED`, in a `tempfile` directory deleted after), loaded as a module
and run through the whole checkpoint. Each was caught; the first failing
check (`-v` prints them):

| Planted | Caught by | First difference |
| --- | --- | --- |
| The DP pitch table a quarter tone off (`DIVISORS[tone + 1]`) | `auto = model` | `PISTOL` tick 0: period 315, model 324 |
| The level from the tick's peak, not its RMS | `auto = model` | `PISTOL` tick 0: attenuation 0, model 6 |
| The noise threshold inverted (`<=` 2,500) | `auto = model` | `PISTOL` tick 0: noise 31, model 0 |
| A run length counted from 0 (`steps.append(k)`) | `auto = model` | `PISTOL` tick 1: the first state lasts 2 ticks |
| A tuned entry ignored (`BGSIT2`) | `tuned = fxtune.txt` | `BGSIT2`: tuned flag 0 |

## 6. The ten tuned effects

`fxtune.txt` holds `PISTOL`, `SHOTGN`, `PLPAIN`, `FIRSHT`, `FIRXPL`,
`STNMOV`, `POPAIN`, `BGSIT2`, `BGACT`, `POSACT`. They were written from
the automatic scripts' per-tick states (`fxmodel.py --states NAME`) and
their renders: the DP's pitch contour kept, the DS's loudness smoothed
into a few steps, the noise colour from the automatic script, and for
`BGACT`/`POSACT` the PC speaker's gating (a tone every other tick, which
the automatic script turns into tone and noise alternating at stage 7)
replaced by a clean 3-tick pulse. **Nobody has listened to them**: this
session cannot hear audio. They are the starting point the README asks
for, for the owner's ear at milestone 12.

## 7. Requests to shared files

### R-FX1. `tools/sound/README.md`, "Effects (S4)"

**What.** In "The converter":

1. Table row **Tone**: replace "(to check against a published table
   before use [A: native-sound 4.5 reconstructed it as quarter tones
   from 175 Hz])" with "(Chocolate Doom's published table, `divisors[]`
   of `src/i_pcsound.c`, PIT clock 1,193,181 Hz; native-sound 4.5's
   quarter-tone reconstruction is within 7.4 cents of it [M:
   `docs/m11-parts/fxconv.md` 4]); a byte of 0 or 128 and up: no tone".
2. Row **Level**: append "; 0 dB is a full-scale sine; the DS's first
   and last 16 samples are DMX's padding and skipped".
3. Row **Noise**: replace with "On when the `DS` tick's zero crossings
   pass 2,500 a second, or when the tick has no tone after the
   quantization (the DS's sound past the DP's tones, a shot's or an
   explosion's decay, is heard as noise); its period from the crossing
   rate, 1-31 (31 with no crossing)".
4. Row **Length**: replace "a tail below 40 attenuation units trimmed"
   with "the tail after the last tick within 40 attenuation units (20
   dB) of the effect's loudest trimmed; a tick at 80 or with neither
   tone nor noise is silent (0, 80, 0), and silent ticks at the end
   dropped".
5. The paragraph "Then **quantized for the ring**": after its first
   sentence add "The rules go in 11 stages (L, H, N): an attenuation
   change under L half-dB units dropped unless from or to 80, a tone
   held at least H ticks, a noise period change under N dropped unless
   it turns the noise on or off; each script takes the first stage that
   holds the budget (`tools/sound/fxconv.py`, `STAGES`)." and replace
   "this one must stay under about 420 [A]" with "this one averages 283
   B a second over the 52 effects, 128 B in the worst 300 ms [M:
   `docs/m11-parts/fxconv.md` 3]".
6. "The script format" table: row `$40`-`$4F`: replace "bit 3 the end
   follows the set" with "bit 3: one wait follows the fields and the
   script ends when it expires"; add a line under the table: "A voice
   starts at (tone 0, attenuation 80, noise 0); the header's last two
   bytes are the length of the steps after it."
7. The paragraph "The scripts go into one bank file": replace "All 52
   about 15 KB [A: the prototype's 14,837 B, M: sound]" with "`SFX.1` is
   11,385 B [M: `docs/m11-parts/fxconv.md`]: the directory (52 × 4 B,
   u16 address and u16 length) at `$0200`, `VATT` at `$02D0`, the
   scripts from `$0350`".
8. "Open problems", first item: replace with "The PC speaker's divisor
   table is read from Chocolate Doom's `src/i_pcsound.c` over the
   network; no copy is kept offline."

**Why.** Sections 2 and 4 above: the evidence for each change.
**Effect on others:** `fxplay` reads the format (item 6) and the silence
rule (item 4: a tuned script may still hold a tone at attenuation 80,
which composes level 0).

### R-FX2. `docs/SCREENS.md` 4.5, row 103

**What.** "the effect scripts (14,837 B in the prototype [M: sound]);
the volume table" becomes "the effect scripts and the volume table,
`SFX.1`: 11,385 B [M: `docs/m11-parts/fxconv.md`]"; label M.

### R-FX3. `tools/testpar.py`: run `wip_test_*` modules by name

**What.** In `discover`, after `found = ...`, accept a module named on
the command line when `tests/<name>.py` is a `wip_test_*.py` file:

    if not names:
        return found
    named = found + sorted(p.stem for p in tests.glob('wip_test_*.py')
                           if p.is_file())
    ...
    unknown = [n for n in wanted if n not in named]
    ...
    return [n for n in named if n in wanted]

**Why.** SCREENS.md 7.1 and every milestone-11 part's task run their
test as `python3 tools/testpar.py tests/wip_test_m11_<part>.py`; today
that stops with "testpar: no such test module". The module loads the
way `unittest discover -s tests -p <module>.py` loads it, which works
(section 3). **Effect:** none on the canonical run (no names).

### R-FX4. `src/native/m11.mk` (part `s2lay`)

Nothing to change if it includes `src/native/m11/<part>.mk` when present
(SCREENS.md 7.3): `fxconv.mk` uses only `FXCONV_*` variables, `ROOT ?=`,
and targets `fxconv`, `fxconv-renders`, `fxconv-clean`, and restores the
including file's default goal. If `m11.mk` wants SFX.1 in its `all`, it
adds `fxconv` to that target's prerequisites.

## 8. For the parts after this one

- `fxplay`: script bytes from `SFX.1` through its directory; the voice's
  start state (0, 80, 0); bit 3 as section 2 item 10; level 0 when the
  attenuation reaches 80 whatever the tone. `fxconv.convert_all(wad,
  None)` or `SFXAUTO.1` gives the automatic versions.
- `fxdisk`: `SFX.1` and `SFXAUTO.1` (same directory layout); the
  checksum shown on screen can be over the script bytes the directory
  gives.

## 9. Open problems

- The effects have not been heard; neither the automatic rules nor the
  ten tuned scripts. The renders are in `build/sound/fx/`.
- Two of the README's rules were changed (section 2 items 5 and 7), for
  the measured reasons given; R-FX1 asks the README to follow.
- The divisor table came from a network fetch; nothing offline
  reproduces it (section 4).
- The renders play one voice at full volume through the music's
  `LEVEL` table and gain, so they are quiet beside the songs' renders
  (peaks 491-8,160 of 32,767 [M: `renders.txt`]); loudness against the
  music is for `fxplay` and the owner.
- The automatic `BGACT`, `POSACT` and `DMACT` (the PC speaker's gated
  warble) keep alternating tone and noise; only the first two are tuned.
- `testpar.py` does not run the `wip_test_*` module by name (R-FX3).

## 10. The wave 1 integration (2026-10-01)

| Request | Outcome |
| --- | --- |
| R-FX1 | Applied: `tools/sound/README.md` "Effects (S4)", items 1-8 as written (and its status line: the converter is built) |
| R-FX2 | Applied: `docs/SCREENS.md` 4.5, row 103 (label M) |
| R-FX3 | Applied with S2LAY-4: `python3 tools/testpar.py tests/wip_test_m11_fxconv.py` runs the module |
| R-FX4 | Applied: `fxconv.mk` adds itself to `m11.mk`'s `PARTS` and `M11_HOST`, so `make -f m11.mk` (its `all`) makes `SFX.1` and `make -f m11.mk part P=fxconv` builds the part; the standalone `make -f src/native/m11/fxconv.mk` is unchanged |
