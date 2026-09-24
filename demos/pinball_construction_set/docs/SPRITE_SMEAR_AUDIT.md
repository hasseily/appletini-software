# Playfield sprite smear: investigation state

2026-09-24. The user reports persistent images at previous sprite positions on Apple II hardware while playing converted pinball tables, most visibly the ball and sometimes flippers. This pass did not identify a cause or produce a verified fix. Stop here until a new, specific reproduction or hardware observation is available.

## What was checked

- `tests/test_smear.py` compares the table pixels after each incremental frame with a forced full redraw on `DEMO5`, `THESAW`, and `TABLE1`, while the ball moves and both flipper keys are pressed and released. It passes. The same visual comparison also passed the preceding disk's `PCS.SYSTEM`, so this test is coverage, not evidence of a fix.
- A longer comparison passed on the preceding program: 300 frames of `DEMO5` and 150 frames of `THESAW`, including Space launch and both flippers. No stale table pixels were found in the emulator.
- A 100-frame play sweep over all 11 converted `.PB` tables measured at most 719 AUX framebuffer bytes, 237,751 CPU cycles, and five dirty rectangles in a frame (`FIREBALL`). These are well below the roughly 16,000 posted video bytes that fit in one frame. Ordinary rendering throughput is unlikely to explain this observation.
- The RUN ball and drop-target records use pixel X with a zero high byte. Although the source spells the writes as `DIV7`/`MOD7`, `src/tables.s` defines those tables as identity/zero in the port. A proposed source rewrite was therefore redundant and was removed. The built `PCS.SYSTEM` again matches the program extracted before this investigation (SHA-256 `000200ded64e0d4a2ea5023d1426d6efbac2b2ee197ea570664ed0cfaaad8769`).
- The flipper frame tables and generated sprites use a common footprint within each flipper group. Their animation's existing dirty mark covers the old and new image in the renderer.
- `copy_arena` writes each dirty rectangle with RAMWRT enabled and turns RAMWRT off afterward, which flushes posted writes. The auxiliary fetch/store routines restore RamWorks bank 0, and the sprite pass turns ALTZP off before the framebuffer copy. No concrete bank-switch or copy defect was found.

## Open lead

`sprite_bank` caches the last auxiliary language-card bank selected. A real ProDOS MLI call might change the underlying bank without updating that cache, whereas FakeProDOS does not model such a change. This is unverified and does not yet explain a persistent trail. No production change was made for it.

For a future pass, the most useful discriminator is a reproducible table and action on hardware, followed by checking whether a forced full-table redraw removes a trail. If it does, inspect dirty marks for that exact sprite transition. If it does not, compare the hardware framebuffer, sprite bank, and imported overlay at the affected pixels. The rebuilt disk for this stopped investigation is `dist/Appletini-PCS.hdv` (SHA-256 `11565306fa5d3279f49be4d31e86c1b24b72ac5d40e41d8c3f3ac6ac03717b2e`).
