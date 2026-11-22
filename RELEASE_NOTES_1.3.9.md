# Appletini Software 1.3.9

This is the software for Appletini firmware **F1.3.9**.

## Changes

- **ONEWWW** is a new web browser for the Apple II+ and the Apple //e. The
  Appletini card gets each web page, lays it out, draws it and sends the
  picture to its HDMI output at 640 x 400 in true colour. The Apple program
  sends the keys and the mouse.
  - Layout with style sheets, tables and pictures in full colour.
  - Forms with GET and POST, and cookies while the browser is open.
  - Proportional fonts with smooth edges.
  - Keyboard and mouse control.
  [ONEWWW program](demos/onewww/README.md) ·
  [ONEWWW guide](https://github.com/hasseily/appletini-one/blob/F1.3.9/README_ONEWWW.md)

## Files

| File | Content |
|---|---|
| `ONEWWW.po` | Boots the ONEWWW web browser (140 KiB ProDOS disk). |

All other files are the files of Software 1.3.8, byte for byte.
`RELEASE_MANIFEST.json` marks them. TINIBROWSER stays in the release: it
shows pages on the Apple video output, in monochrome.

## Limits

- ONEWWW needs firmware F1.3.9, Ethernet, and a display on the HDMI output
  of the card. The video output of the Apple does not show the page.
- JavaScript is not supported. A page that needs JavaScript shows only a
  part of its content, or no content.
- WebP and SVG pictures do not show. The cookies are gone when the browser
  closes.
- The Apple IIgs has no ONEWWW client program yet.

## Validation

The ONEWWW test runs the 6502 program in an emulator against a model of the
card: the SmartPort calls, the keys, the mouse and the quit to ProDOS.

The development build of the program was tested on a card with firmware
F1.3.9dev22: the disk boots and loads the home page. The released program
has one text changed (the firmware version in its error message). This note
records no board test of the final file.
