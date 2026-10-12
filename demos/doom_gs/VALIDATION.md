# v1.5 reference rebuild

Checked on 2026-10-12 using Python 3.12, GCC and cc65 in WSL Ubuntu.
The Appletini port remains native 65C02; v1.5 supplies the verified upstream
reference and converted data. This is not a claim that every new IIgs-only
feature has been ported.

## Inputs and artifact

| Item | Value |
|---|---|
| Upstream source commit (v1.5) | `e645893f3d1ac6826e560e0ed3b28e0062c33995` |
| Upstream `doom-hd.hdv` SHA-256 | `917212c62acf08d4ff27752e44a97543b8e142a1587e26dc0ee3f22e0053a9e5` |
| Download | [DOOM.hdv](DOOM.hdv), 4,034,048 bytes |
| Download SHA-256 | `b5568227b1b0f37efb7b46e143d20b3350970ba17c763a408fe79f40455996c1` |

The published disk matches `build/native/DOOM.hdv` byte for byte. The original
IIgs disk and fetched upstream source remain in ignored build directories.

## Checks performed

- Reassembled the reference game, boot block and loader: **239,104 bytes,
  zero differences**. The v1.5 frontend generates and includes the sound-volume
  tables and exit-screen text as well as the renderer and loader font.
- Ran all five reference capture scenarios: 53 new-game frames, 11 demo
  samples, 583 title/demo frames, 51 tour frames across E1M1–E1M9 and 12
  lighting frames; **710 captures** in total. The reference uses 12 MHz so
  upstream's boot speed test installs the full view through its normal code.
- Verified renderer table formulas, output read-back and consistency across
  13 level sources. Converted map, texture and patch stores fit the native
  bank budgets; source, placement and read-back checks pass.
- Built and linked the native renderer, level loader, menus, game logic,
  Phasor music and 52 sound effects. Wrote the ProDOS disk with 12 bank files.
- Passed the ADB regression: delayed register-3 identity response, preserved
  queued key-down/up events and empty register-0 response.
- Ran the published disk's contents through the `f122-nod2` TURBO model with
  a read-only block device, ProDOS MLI emulation, 8 MB RamWorks and Phasor:

| Scenario | Observed progress | Phasor writes |
|---|---|---:|
| Menu, new game, E1M1 movement | game tics 764 to 1,025; changing view | 2,203 |
| E1M7 attract demo | game tics 1,282 to 1,672; changing view | 3,729 |

Both runs reached their scripted stop with no crash/halt, the expected level,
closed menus and the expected demo/play mode. Title and gameplay screenshots
were also inspected. No new physical-board or ROM-level ProDOS boot test was
performed. The earlier port's hardware validation does not qualify this disk.

## Reproduce

From this directory, after moving an old v1.0 `build/` aside:

```sh
./build.sh
make -C tools/ref816 test
python3 tools/native/check_release.py
```

Evidence is written to `build/match-report.json`,
`build/native/render/rendercap.json`, `build/native/render/tables/tables.json`
and `build/validation-v15/validation.json`. Native run snapshots, screenshots,
events and AY logs are retained under `build/validation-v15/`.
