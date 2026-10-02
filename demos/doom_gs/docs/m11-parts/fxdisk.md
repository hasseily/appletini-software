# Milestone 11, part `fxdisk`: the effects' test disk `SOUNDS.hdv`

Part `fxdisk` of wave 7 ([`docs/SCREENS.md`](../SCREENS.md) 3, 7.3, 8.2
row 6; [`tools/sound/README.md`](../../tools/sound/README.md) "Effects
(S4)": "The ten tuned effects", "The player", "The test disk SOUNDS.hdv",
"Tests"), 2026-10-02. Labels as in `NATIVE.md`: [M] measured, [R
file:line] read, [A] assumed. Nothing of upstream's is used: the part has
no upstream routine.

## 1. What was built

| File | What |
| --- | --- |
| `src/sound/sounds.s` | `SOUNDS.SYSTEM`: the boot (MUSIC.SYSTEM's, `src/sound/music.s`, as the model), the screen, the keys, the quit. Its header is the program's specification |
| `src/sound/sounds.cfg` | Its ld65 map: the program at `$2000-$3FFF`, its data `$1000-$1FFF`, its zero page `$18-$3F`; S2's player, `pl_irq.s` and `fx.s` at the game's places (`s2layout.py`: S2's code `$E900-$F504`, `FXCODE` `$F505-$F8FF`, the ring, lists and state, `SNDZP` `$D8-$F6`) |
| `src/native/m11/fxdisk.mk` | `make -f m11.mk part P=fxdisk`: `inc/s2.inc` (a copy of the release's `s2-release.inc`), `inc/sfxnames.inc` (`fxdisk.py --inc`), `fx-card.o`, `fx.o` (`-D FX_SERVICE`), `pl_irq.o`, `sounds.o`, S2's `player.o` and `probe.o` from `build/sound65` read only; links `sounds.main` and `sounds.lc` |
| `tools/sound/fxdisk.py` | The disk (part `fxconv`'s make for `SFX.1`, the program's make, `D_E1M1` converted now, the existing port's disk writer as `musicdisk.py` uses it), the a2vm runs, the key model `UiModel`, the oracle, the checks, the planted bugs |
| `tests/wip_test_m11_fxdisk.py` | 12 tests: 9 without `build/` (the names, the checksum, the screen's rows, the key model's steps, the marker's parser, the model's bank), and with it the disk's places and sizes, the checkpoint, the planted bugs |

Build output: `build/native/m11/fxdisk/` (484 KB); the disk
`build/sound/SOUNDS.hdv` (143,360 B, 280 blocks, SHA-1 `225f7d59`). Every
run is in a `build/tmp-fxdisk-*` directory deleted after it.

### 1.1 The disk

| File | Type | Bytes | What |
| --- | --- | ---: | --- |
| `SOUNDS.SYSTEM` | SYS `$2000` | 14,080 | `$2000-$3FFF` the program, `$4000-$56FF` the card image `$E900-$FFFF` |
| `PRODOS` | SYS | 17,128 | ProDOS 2.4.3 and its boot blocks (`ProDOS_2_4_3.po`) |
| `SFX.1` | BIN `$0200` | 11,385 | Part `fxconv`'s bank file, the ten tuned |
| `SFXAUTO.1` | BIN `$0200` | 12,850 | The same, every script automatic |
| `E1M1.AY` | BIN `$1000` | 15,972 | `D_E1M1`'s song file (`mus2ay.py`, at build time) |
| `PROFILE.TXT` | TXT | 2,504 | The Doom profile (`musicdisk.py`'s text) |

`fxdisk.py` runs part `fxconv`'s make first, so the owner's tuning loop of
the README ("edit `fxtune.txt`, run `python3 tools/sound/fxdisk.py`")
takes the edited file.

## 2. The program as built (decisions where the design left a choice)

1. **Banks.** `SFX.1` in bank `SFX` (103) at `$0200`, as the game. The
   ten automatic scripts of the tuned effects go after it in the bank's
   room (`s2layout.SFX_ROOM`, to `$3FFF`): `$2E79-$374A` [M]; the program
   notes both directory entries of each tuned effect, and **T** rewrites
   the effect's 4-byte entry in the bank (interrupts masked; a playing
   voice keeps the script it has). The song in bank `SONGS0` (100) at
   `$1000`; ProDOS's card saved in bank 1 (spare); RamWorks banks 1-103
   checked distinct (MUSIC.SYSTEM's check, to bank 103). Without native
   mode the two effect files are still loaded (the screen's list, marks
   and checksums), the song is not.
2. **Boot order** as FXPLAY-3: `snd_probe`, the files, ProDOS's card
   saved, the image installed, `snd_init`, `fx_init` with the answer,
   `pl_clkset` (PAL, so the clock is defined before the first interrupt),
   the VBL, `CLI`, `pl_detect`.
3. **One effect at a time.** A play stops every effect (`fx_stopall`),
   then writes channel 0's mailbox as the channel logic does: RETURN
   separation 128 (a source ahead: the game's rule gives A), A 64, B 200.
   **C** cannot be reached by the rule while A is free, so channel 0 takes
   A and channel 1 the effect in one `fx_service`, then channel 0 is
   stopped and served again, all with interrupts masked: A never sounds
   (its level 0 at the next interrupt), the effect plays on C. Three
   voices at once are `fxplay`'s checkpoint's.
4. **1, 2, 3** set the distance (volumes 127, 63, 6: `fxrun65.VOL_*`) for
   the next plays and send a volume mail to the last play's channel, so a
   playing effect changes level (the `VOLUME` mailbox exercised).
5. **R** repeats the last play key on the chosen effect every 50 visits
   (60 on NTSC) of the main loop; **S** stops every effect and the
   repeat. **M** starts `D_E1M1` looping by `fx_song` or stops it by
   `snd_stop`; nothing without native mode. **V** calls `pl_clkset` with
   the other standard (the effects' tempo follows `CLK_STD`) and starts
   the song again on the other tables, as MUSIC.SYSTEM's V.
6. **The main loop** once a VBL: the repeat, one key, a frame
   (`fx_service`, then `snd_refill`: the game's frame images' order), the
   screen. Every step but a song start runs with interrupts masked; the
   frame runs with them on, right after the VBL.
7. **`sds_mark`** (main zero page): each step stores its kind first
   (`fxrun65.py`'s action codes, and `TOGGLE` 11, `STD` 12, `QUIT` `$FF`),
   a frame `$80` and `$81`, 0 between. The checks read it in the write
   log; nothing else of the program is instrumented.
8. **The screen** (PAL, the music and the repeat on, the cursor on
   `POSACT` after T and a play on B at distance 2; the rows as the checks
   build them, `fxdisk.py` `machine_row`, `list_rows`, `effect_row`):

   ```
   DOOM GS: THE EFFECTS ON THE PHASOR
   PAL //E  PHASOR NATIVE  CHIP 3 MUSIC REP
     PISTOL T     PLPAIN T     PDIEHI
     SHOTGN T     DMPAIN       PODTH1
     ...                       (3 columns of 18; T tuned, A a tuned
                                effect set to its automatic script)
   POSACT AUTO  SUM 63AB MID  B RIGHT
   ARROWS CHOOSE  RETURN PLAY  A B C VOICE
   1 NEAR 2 MID 3 FAR  T TUNED  R REPEAT
   M MUSIC  S STOP  V PAL/NTSC  Q QUIT
   ```

   Row 20: the effect, `TUNED` or `AUTO`, `SUM` (the checksum of the
   script the bank's directory gives, read through `fx_copy`: for each
   byte the 16-bit sum rotated left one bit, then the byte added), the
   distance, and after a play the voice its channel got (read in the card
   after the frame's service; `-` when none). Without native mode row 1
   is `PAL //E  NO EFFECTS: NO NATIVE MODE`. Up and down move one effect
   (wrapping), left and right a column.

## 3. Checkpoint

Commands, from `demos/doom_gs` (`df -h /System/Volumes/Data`: 58 GB free):

```
make -s -C src/native -f m11.mk part P=fxdisk       # no warning
python3 tools/sound/fxdisk.py --check               # the disk, then the checks: 4 s
python3 tools/sound/fxdisk.py --planted             # 4 s
python3 tools/testpar.py --jobs 2 tests/wip_test_m11_fxdisk.py   # 12 tests, 8 s
python3 tools/testpar.py --jobs 2 test_sound_ayrender test_sound_decoders \
    test_sound_disk test_sound_mus test_sound_mus2ay test_sound_player \
    test_sound_player65                             # green, unchanged
```

Every run: the disk's own `SOUNDS.SYSTEM` under the MLI trap,
`--core w65c02s`, the Doom profile `f121+phasor+window32` (`+ntsc` for
the NTSC run), `--cost-timed`, `--irq-bounds
00D8-01FF,C0A0-C0AF,C400-C4FF,E000-FFFF`, the AY log, the write log (the
voices, `FX_ON`-`FX_SVC`, the rings, `snd_playing`, `sds_mark`), range
snapshots (main, the card, banks 100 and 103). The oracle (`fxdisk.py`'s
docstring): the key model's steps must be the program's, kind for kind
and each in its visit; every interrupt's AY writes equal the models'
(`run65.RingPlayer` for chips 0-2, `fxplay.FxPlayer` for chip 3, on a
bank of the model's own where T switches the entry to `SFXAUTO.1`'s bytes
at other addresses); the main loop's writes; the chips at the end; the
rings' publish order (`fxrun65.publish_problems`) up to the quit.

Results [M, 2026-10-02], all 0 problems:

| Check | Result |
| --- | --- |
| places | the map's segments at `s2layout.py`'s places, the IRQ vector `pl_vbl` |
| left | the 52 effects by RETURN, A, C in turn at the three distances in turn: 2,551 interrupts, 2,581 chip-3 writes, every one equal; the boot's screen row for row; bank 103 holds `SFX.1` at `$0200` and the ten automatic scripts after it byte for byte (`sds_next` `$374B`); bank 100 holds `E1M1.AY` at `$1000` |
| right | the 52 effects on B: 2,551 interrupts, 2,580 chip-3 writes, equal |
| tuned | the ten tuned effects: tuned on A, T, automatic on B, T back (20 T, 20 plays, 1,063 interrupts), equal; the effect line (`TUNED`/`AUTO`, `SUM` of the right script, the distance, `A LEFT`/`B RIGHT`) and the list's `T`/`A` marks after each T of the first three |
| music | M, the 52 effects over `D_E1M1` by RETURN, A, B, C in turn, V half way (the song again on the NTSC tables, the effects' tempo NTSC), M (silence), one more effect: 1,413 interrupts, 1,077 music and 2,104 chip-3 writes, equal; row 1 `MUSIC` and `NTSC` as they change |
| ntsc | an NTSC machine (`pl_detect`): `DORCLS` with three volume mails while it plays, C, R (3 repeats), S, B, then ESC: 472 interrupts equal; row 1 `REP` on and off; the quit as below |
| quit | M and RETURN, then `q`: `snd_init`'s resets the last AY events, the chips at 0, the card's former contents (a pattern loaded before the boot) back byte for byte, the Phasor in Mockingboard mode, ProDOS's QUIT |
| nonative | `--phasor-mb-only`: RETURN, A, B, C, 2, T, R, M, down, C, V, 3, S, B, then Q: no AY event but the probe's and `snd_init`'s (and the quit's resets); 7 MLI calls (`SFX.1`, `SFXAUTO.1`, the QUIT: no song file); row 1 `NO EFFECTS: NO NATIVE MODE`, the voice `-` |
| `tests/test_sound_*` | unchanged (no file of S2 or S3 edited), green: 7 modules |
| Python 3.9.6 | `wip_test_m11_fxdisk` OK with `-W error::ResourceWarning` (12 tests, 7 s) |

## 4. Planted bugs (each in a scratch copy of `sounds.s`, built apart)

`fxdisk.PLANTED`: each is a text replacement, built with `make ... M11=<tmp>/m11
FXDISK_SRC=<tmp>/src` into a `tempfile` directory and its disk, then run
through the named checks; every named check must fail.

| Bug | Caught by | The failure |
| --- | --- | --- |
| A key playing the next effect (`snd` = cursor + 2) | left | "interrupt 6 (chip 3): write 0 is (3, 0, 1), expected (3, 0, 68)" |
| The side keys swapped (`sep_of` A 200, B 64) | right | "interrupt 6 (chip 3): write 0 is (3, 0, 68), expected (3, 0, 0)" |
| The tuned version not loaded (`SFXAUTO.1` read as the bank file) | tuned; left | "49 steps ran, the keys make 69" (T finds no tuned effect); "interrupt 6 (chip 3): write 6 is (3, 6, 0), expected (3, 6, 8)" (PISTOL plays its automatic script) |
| Effects played without native mode (`fx_init` given `SND_MUSIC`) | nonative | "interrupt 5 (chips 0-2): 11 writes, expected 0": chip 3's writes reach VIA-B's only AY, the music's chip 2 |

## 5. Sizes

| Item | Size [M] | Room |
| --- | ---: | ---: |
| `SOUNDS.SYSTEM`'s code (`SDSCODE`) | 2,422 B | |
| its data (`SDSDATA`: strings, names, tables) | 1,056 B | |
| main in all with `fx_service` (396 B) and S2's probe (117 B) | `$2000-$2F96`, 3,991 B | 8,192 B |
| its runtime data (`SDSBSS`), zero page (`SDSZP`) | `$1000-$1313`; `$18-$35` | `$1000-$1FFF`; `$18-$3F` |
| the card image | S2's player, `pl_vbl` and `fx.s`'s card part as the game (`FXCODE` 983 of 1,019 B) | `$E900-$FFFF` |
| bank 103 | `SFX.1` and the automatic scripts, `$0200-$374A` | `SFX_ROOM` `$0200-$3FFF` |

The part's budget is its time (1.5 hours); it has no game code.

## 6. Requests (for the integrator)

No stand-in: the part uses `s2layout.py`'s places as they stand (its own
`inc/s2.inc` is a copy of `s2-release.inc`, equal to the test build's
today).

### FXDISK-1. `tools/sound/README.md` "Effects (S4)": the test disk as built

**Evidence:** sections 1-4. **Effect on others:** none.

Replace the section "The test disk `SOUNDS.hdv` (`tools/sound/fxdisk.py`)"
from its first paragraph to the line "`fxdisk.py --check` runs it on a2vm
(MLI trap, `--irq-bounds`, the AY log): every key's writes equal
`fxplay.py`'s." with:

> `SOUNDS.SYSTEM` (`src/sound/sounds.s`, `sounds.cfg`; with S2's player,
> `pl_vbl` and `fx.s` at the game's places), like `MUSIC.SYSTEM` above:
> the mouse card, RamWorks banks 1-103, the probe, `SFX.1` into bank
> `SFX` at `$0200` and the ten tuned effects' automatic scripts from
> `SFXAUTO.1` after it (`$2E79-$374A`), `E1M1.AY` into bank 100 at
> `$1000`, ProDOS's card saved in bank 1, `snd_init`, `fx_init`, PAL or
> NTSC (`pl_detect`). The disk (143,360 B): `SOUNDS.SYSTEM`, `PRODOS`,
> `SFX.1`, `SFXAUTO.1`, `E1M1.AY`, `PROFILE.TXT`.
>
> ```
> DOOM GS: THE EFFECTS ON THE PHASOR
> PAL //E  PHASOR NATIVE  CHIP 3 MUSIC REP
>   PISTOL T     PLPAIN T     PDIEHI
>   ...  (52 effects, 3 columns of 18; > the chosen; T tuned, A a tuned
>         effect set to its automatic script)
> POSACT AUTO  SUM 63AB MID  B RIGHT
> ARROWS CHOOSE  RETURN PLAY  A B C VOICE
> 1 NEAR 2 MID 3 FAR  T TUNED  R REPEAT
> M MUSIC  S STOP  V PAL/NTSC  Q QUIT
> ```
>
> Row 20: the chosen effect, its version, `SUM` (a checksum of the script
> the bank's directory gives: for each byte the 16-bit sum rotated left
> one bit, then the byte added), the distance, and after a play the voice
> it got. A play stops every effect, then starts the chosen one by the
> game's mailbox (channel 0), one effect at a time.
>
> | Key | What |
> | --- | --- |
> | Up, down | The previous or next effect; left, right a column |
> | RETURN | Play it as a source ahead (separation 128): the game's rule gives voice A |
> | A, B | Play it on A (separation 64, left) or B (200, right) |
> | C | Play it on C (left): channel 0 takes A and channel 1 the effect in one service, then channel 0 is stopped, interrupts masked: A never sounds |
> | 1, 2, 3 | Distance: volume 127, 63 (about 680 units), 6 (1,150); the playing effect's volume follows |
> | T | Its tuned or automatic script (the ten tuned only): its directory entry in the bank is rewritten |
> | R | Repeat the last play every second (50 or 60 VBLs), to compare by ear |
> | M | `D_E1M1` under the effects (`fx_song`), or silence (`snd_stop`) |
> | S | Stop every effect, and the repeat |
> | V | PAL or NTSC: the effects' tempo (`pl_clkset`) and the song again on the other tables |
> | Q, ESC | Quit as `MUSIC.SYSTEM` (the chips reset, ProDOS's card back, the Phasor in Mockingboard mode) |
>
> On a card without native mode the second line says `NO EFFECTS: NO
> NATIVE MODE`, the song is not loaded, and no key writes an AY register.
>
> `fxdisk.py --check` runs it on a2vm (MLI trap, `--irq-bounds`, the AY
> log, a write log of the effects' state and the program's step marker):
> the program's steps equal a model of the keys, each in its visit, and
> every interrupt's writes equal the models' (`fxplay.py`'s for chip 3,
> S2's for the music): every effect on a left voice and on the right one
> at the three distances, the ten tuned tuned and automatic, every effect
> over `D_E1M1` with V and M, NTSC with the volume, the repeat, S and
> ESC, q, and `--phasor-mb-only` (no AY write past the probe's and
> `snd_init`'s); the screen's rows; the quit as `MUSIC.SYSTEM`'s; four
> planted bugs caught (`docs/m11-parts/fxdisk.md`).

In "The ten tuned effects", paragraph "How the owner tunes them", nothing
changes (the tool runs part `fxconv`'s make, so an edited `fxtune.txt` is
taken). In "Tests", row `fxdisk`, replace "The disk on a2vm" with "The disk
on a2vm: the keys' steps against a model of the keys, every effect left
and right at three distances, the ten tuned both ways, over the music
with V and M, NTSC, the repeat, the quit, `--phasor-mb-only`; the screen;
the planted bugs". In the "Effects (S4)" status line, add "the test disk
is built (part `fxdisk`, wave 7, 2026-10-02:
[`docs/m11-parts/fxdisk.md`](../../docs/m11-parts/fxdisk.md))".

### FXDISK-2. `src/native/m11.mk`: `SOUNDS.SYSTEM` in `make -f m11.mk` (optional)

`fxdisk.mk` adds itself to `PARTS` only, so `make -f m11.mk` (all) does
not build `SOUNDS.SYSTEM`; `make -f m11.mk part P=fxdisk` and
`fxdisk.py` do. If the integrator wants `all` to build it, one line in
`fxdisk.mk` (mine, but it changes what `all` does for everyone): `M11_HOST
+= fxdisk_all`. `make -n -f m11.mk all` with the fragment included gives
no warning and no override today [M].

### FXDISK-3. `docs/SCREENS.md` 4.5, row 103 (a note)

Append to the row: "The test disk `SOUNDS.hdv` puts the ten tuned
effects' automatic scripts after `SFX.1` in `SFX_ROOM` (`$2E79-$374A`,
part `fxdisk`); the game does not." **Evidence:** section 2 item 1. No
address of the game moves.

## 7. Open problems

1. Nothing has run on the card or been heard: the owner tunes at
   milestone 12 (the README's loop). ProDOS's own restart after the
   quit is untested (the MLI is a trap on a2vm), as MUSIC.SYSTEM's.
2. The disk plays one effect at a time (a play stops the others); three
   voices at once, an effect held across a song start and the underrun
   are `fxplay`'s checkpoint's, not this disk's.
3. C reaches voice C by taking A for one masked service; it writes A's
   level 0 at the next interrupt (silent already after the play's stop).
4. T rewrites a directory entry in bank 103; the game never does. The
   test disk's automatic scripts take `$2E79-$374A` of `SFX_ROOM`, which
   the game leaves empty (FXDISK-3).
5. V calls `pl_clkset`, which restarts the tic clock and the VBL count:
   harmless here (no game), and the main loop resynchronizes its count.
6. The README's screen of the design (FXDISK-1) differed in layout from
   the one built: rows 1 and 20 as above.

## 8. The wave 7 integration (2026-10-02)

What the integrator did with each request (`docs/SCREENS.md` 8.11,
"Wave 7 as integrated"):

| Request | Outcome |
| --- | --- |
| FXDISK-1 | Applied as written: `tools/sound/README.md` "The test disk `SOUNDS.hdv`" replaced by the text as built, the "Tests" row, and the "Effects (S4)" status line (which now also names the player and the channel logic as built) |
| FXDISK-2 | Applied: `fxdisk.mk` adds `fxdisk_all` to `M11_HOST`, so `make -f m11.mk` (all) builds `SOUNDS.SYSTEM` (not the disk: `fxdisk.py` makes it). `all` already needed S2's objects in `build/sound65` for the frame images, so nothing new is required; `m11.mk`'s comments name it |
| FXDISK-3 | Applied: SCREENS.md 4.5's row 103 |

After the integration the disk is the same bytes (SHA-1 `225f7d59`);
`fxdisk.py --check` and `--planted` give section 3's and 4's results.
