# libtini design notes

These Markdown files record why libtini is built the way it is: the plan,
the contracts each module keeps, layout decisions and measurements. They
describe the code as of 2026-10-22. For how to use the library, open the
developer reference, [docs/index.html](../docs/index.html), in a browser.

| File | Contents |
| --- | --- |
| [PLAN.md](PLAN.md) | Scope, agreed boundaries, checkpoints and release checks |
| [CONTRACTS.md](CONTRACTS.md) | Public ABI, launch and lifecycle, near pointers and handles, mapping, interrupts, timing and feature lifetimes |
| [MEMORY_MAP.md](MEMORY_MAP.md) | Main and auxiliary memory ownership, the linker layouts and STARFALL's budget |
| [GAMES.md](GAMES.md) | Game manifests, layouts, the near arena and a fixed-rate loop |
| [GRAPHICS.md](GRAPHICS.md) | Surfaces, drawing, publication, sprite scenes, asset formats and their checks |
| [AUDIO.md](AUDIO.md) | The audio driver, scores and pattern songs, envelopes, speech, input and their checks |
| [STORAGE.md](STORAGE.md) | ProDOS files, the AUX0 loan and TPK1 packs |
| [AMEM.md](AMEM.md) | The optional private memory transport and its failure rules |
| [BENCHMARKS.md](BENCHMARKS.md) | Benchmark and profiler method and recorded emulator results |
| [WEB.md](WEB.md) | The browser player, its publication and its checks |

Emulator figures in these notes are model evidence, not board timing.
