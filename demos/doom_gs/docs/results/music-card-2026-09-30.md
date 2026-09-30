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
- The owner's report, the same day: "Volume is a little low but music
  sounds great"; "Exit to prodos is fine"; with the default window (512)
  "I can't really tell the difference". The last one is expected: the
  window only sets how long the CPU stays at 1 MHz after a burst, not when
  the writes reach the AY chips. At 512 the player costs 11.5-27.5 ms of
  CPU a second instead of 2.5-7.1 at 32 (`docs/research/native-sound.md`
  4.2), so the profile saves time for the game and changes nothing you can
  hear.
- A gain for each song (commit 5aba2f60: the loudest 1% of a song's
  melodic note time scaled to level 15, plus 3 dB; +3 to +10.5 dB by song)
  was played on the card the same day and refused: "I don't like the new
  music mix. The old mix, while not as loud, was better. Drums now are too
  weak, and overall everything is flat." It is reverted; the disk is the
  first one again (`MUSIC.hdv`, SHA-1 `500c6ea9`). The owner prefers the
  arrangement's balance and dynamics to loudness: a louder mix must not
  move the drums against the melody or clamp notes at full level.
