# Appletini Software

Apple II software and hardware demonstrations built to exercise Appletini.

## Demos

- [Appletini Invasion](demos/appletini_invasion/README.md) — an enhanced
  Apple //e fixed shooter using 33.3 MHz acceleration, DHGRi, Video-7 MIX,
  SmartPort, Mockingboard music and speech, and 8 MB RamWorks.

## Development layout

The tools use sibling checkouts by default:

```text
Repos/
├── appletini-one/
├── appletini-software/
└── gssquared/
```

Build and test the demo with:

```sh
cd demos/appletini_invasion
make disk
make smoke
```

Set `APPLETINI_ROOT` or `GSSQUARED_ROOT` when those repositories are located
elsewhere. See the demo README for toolchain and runtime details.
