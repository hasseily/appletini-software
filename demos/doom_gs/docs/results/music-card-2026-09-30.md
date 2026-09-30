# Music disk on the card, 2026-09-30

The owner booted `build/sound/MUSIC.hdv` (sound milestone S3,
`tools/sound/musicdisk.py`) on the Appletini: PAL //e, TURBO, RamWorks, the
mouse card in slot 2, the virtual Phasor in slot 4, and the DOOM
configuration profile (`vtw.slowdown.cycles=32`). It played D_E1M8; the
screen photo shows it stopped at 0:46 of 2:32, then the timing test (T).

| Measurement | Card | a2vm (milestone S3 checks) |
| --- | --- | --- |
| VIA-A timer 1 counts in one VBL (PAL detection) | 20,281 | 20,280 |
| Phasor mode found by the probe | native, 4 AY chips | native, 4 AY chips |
| One AY register write (the player's 41-cycle burst loop) | 40.4 us (expected 40.4) | 41.0 cycles = 40.4 us |
| Slow-window tail after a burst | 32.2 cycles = 31.7 us | 31.9-32.8 cycles, by code alignment |
| Verdict printed | "the window is 32: the DOOM profile" | window 32 |

- The disk boots, probes the card, detects PAL and plays on hardware.
- The timing model of the Phasor path (a2vm's slot-4 slowdown, milestone S2)
  matches the card within one cycle: the second hardware anchor of the cost
  model after the replay's frames.
- The DOOM profile is active on the owner's card: the window is 32 cycles.
- The owner's report, the same day: "Volume is a little low but music sounds
  great"; "Exit to prodos is fine"; with the default window (512) "I can't
  really tell the difference". The last one is expected: the window only
  sets how long the CPU stays at 1 MHz after a burst, not when the writes
  reach the AY chips. At 512 the player costs 11.5-27.5 ms of CPU a second
  instead of 2.5-7.1 at 32 (`docs/research/native-sound.md` 4.2), so the
  profile saves time for the game and changes nothing you can hear.
- The low volume: measured in the player model over 60 s of each song, the
  voices that sound average level 8.7 of the AY's 15 (6.4 to 12.1 by song),
  and D_E1M2 and D_E1M5 never go above 12. The converter is being changed
  to scale each song to full level. (Corrected after review: that mean
  counted a drum on the chip's envelope as level 15 for as long as the
  player leaves it there; the melodic voices alone average 8.0, 6.1 to
  10.0 by song, `tools/sound/README.md`'s loudness table.)
- Done the same day (`tools/sound/README.md`, "The song gain"): each song
  gets a gain of +3 to +10.5 dB, so that the loudest 1% of its melodic
  note time plays at level 15, and notes up to 3 dB quieter also reach 15
  (the boost). That clamps 3% (D_VICTOR) to 87% (D_E1M1) of a song's
  melodic note time at full level, where it loses its dynamics; the
  owner chooses the boost (`mus2ay.py --boost`, 0 clamps only the loud
  1%). The renders' RMS rises 3.1 to 8.7 dB and the mix still never
  saturates. The drums do not keep their balance with the melody: hits
  already on the chip's envelope cannot get louder, soft ones the gain
  moves there jump to full level, so the drums move by -7.4 to +2.8 dB
  against the melody by song, for the owner's ear. The louder songs
  exceed the design's writes a second or p99 burst in 7 figures, accepted
  because the player's bus cost stays inside the design's range. The
  rebuilt disk, with the review's fixes (`MUSIC.hdv`, SHA-1 `1344e6cf`),
  awaits a card run.
