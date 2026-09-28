# DOOM GS: the Apple IIgs DOOM on the Appletini 65C02

This is a port in progress of [Webifi's Apple IIgs DOOM](https://github.com/Webifi/iigs-doom)
to an enhanced Apple //e with an Appletini card. Upstream is a complete game,
about 82,000 lines of 65816 assembly. The Appletini's accelerator is a W65C02S,
so every instruction has to be translated, interpreted or rewritten.

**Status: planning and tooling. Nothing runs on the Apple yet.**

It is separate from the existing port in [`demos/doom`](../doom/README.md),
which is a different engine written for cc65.

## What is here

| Path | Contents |
| --- | --- |
| `docs/ARCHITECTURE.md` | Draft architecture: a virtual 65816 machine on the 65C02, with an interpreter for cold code, translated regions, and hand-written kernels for the hot loops. Not yet reviewed by the project owner. |
| `docs/design-proposals/` | The three independent proposals the architecture was drawn from, each with a correctness critique and a hardware critique |
| `docs/research/` | Reports on upstream's renderer and platform layer, on the Appletini hardware, and on the existing port |
| `docs/firmware/` | Plans and adversarial reviews for Appletini firmware changes that would speed up software like this. They are proposals; none is implemented. |

The research and firmware notes were written against Appletini firmware
F1.1.4 to F1.2.1 and upstream commit `8ea2eac`. Paths shown as `<upstream>`,
`<appletini-one>` and `<scratch>` refer to local checkouts, not to this
repository.

## Upstream code is not in this repository

Upstream is GPL-2. The build fetches a pinned clone and the v1.0 release image
into `build/`, which is ignored by git, and converts them there. This follows
[The Bilestoad](../bilestoad/README.md).

Two further rules:

- `src/iigs/cal_integer.s` in upstream is a copy of the Calypsi vendor runtime.
  Its licence restricts it to that toolchain, so the port uses its own
  routines and keeps nothing derived from that file.
- The research notes quote short passages of upstream source for analysis.
  Those passages remain under upstream's licence.
