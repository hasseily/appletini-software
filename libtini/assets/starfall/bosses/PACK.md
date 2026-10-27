# Compact space bosses (Kenney style)

Five spaceship bosses, each at most 100 × 80 px, in the style of Kenney's Pixel Shmup: same palette, 2px dark outline, flat fills, sparse panel lines. Every ship faces down the screen (toward the player), has a 4-frame idle loop, and has 3 destroyable weapon emplacements mounted on hull sockets.

| # | Boss | Size (px) | Shape | Weapon emplacements |
|---|------|-----------|-------|---------------------|
| 1 | Manta | 100 × 74 | Space ray with forward lobes | Left wing laser, right wing laser, plasma maw |
| 2 | Excalibur | 94 × 77 | Sword, blade toward the player | Left guard turret, right guard turret, point emitter |
| 3 | Scarab | 78 × 74 | Beetle with split wing cases and legs | Left mandible gatling, right mandible gatling, mine layer |
| 4 | Comet | 66 × 75 | Fireball with three flame fins | Left missile pod, right missile pod, tesla core |
| 5 | Bulwark | 96 × 70 | Stepped ziggurat fortress | Left flak battery, right flak battery, prow railgun |

Weapon idle animations: lasers and the point emitter charge, the plasma maw pulses, guard turrets and flak batteries recoil, gatlings spin, the mine layer's doors slide open on a live mine, missile pods blink and fire a round, the tesla core throws arcs, the railgun's coils light in sequence. Hulls animate too: engine plumes, the sword's blade runes and gem, the beetle's legs, the comet's flickering fins, the fortress's window lights.

## Palette

16 entries (`palette.hex`, `palette.gpl`, `palette.png`). Index 0 is transparent; the other 15 come from Kenney's Pixel Shmup sheet, with index 2 as his pale yellow for glows. No drop shadow. Every PNG is a true 4-bit indexed image.

## Files per boss

- `body.png`: the hull, 4 frames.
- `<weapon>_intact.png` and `<weapon>_destroyed.png`: one pair per emplacement, 4 frames each. Both strips share frame size and offset.
- `full_intact.png` / `full_destroyed.png`: pre-composited reference strips.
- `<boss>.json`: frame sizes, offsets, hitboxes and draw order.

Strips are 4 frames laid out horizontally, left to right. Frame width = image width ÷ 4. Suggested playback is 8 fps.

## Assembling a boss in-engine

Coordinates are in pixels from the boss's top-left corner (its `size` box).

1. Draw `body` at `body.offset`.
2. Draw each weapon, in `draw_order`, at its `offset`, using the intact or destroyed strip depending on its state.
3. Use each weapon's `hitbox` (`[x, y, w, h]`, intact footprint) for collision.

## Preview

`preview/` has a contact sheet (frames 1–4, then all weapons destroyed) and a GIF per boss that plays the idle loop and then knocks out the weapons one by one.
