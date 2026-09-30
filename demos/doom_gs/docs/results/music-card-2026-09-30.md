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
- Not yet reported: how the arrangements sound, the default-window run
  (512), and ProDOS after quitting.
