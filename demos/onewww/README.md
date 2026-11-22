# ONEWWW

ONEWWW is a web browser for an Apple II+ or Apple //e with an Appletini ONE.
The card gets each web page, lays it out, draws it and sends the picture to
its HDMI output at 640 x 400 in true colour. This program is the Apple side:
it sends the keys and the mouse to the card. It is 591 bytes of 6502 code.

`ONEWWW.po` boots to the browser. To install it on another ProDOS volume,
copy `ONEWWW.SYSTEM`.

## What you need

- Appletini firmware **F1.3.9** or later.
- Ethernet with a link and an IP address.
- A display on the HDMI output of the card. The video output of the Apple
  does not show the page.
- A mouse card is optional. The program finds it in slots 1 to 6.

The [ONEWWW guide](https://github.com/hasseily/appletini-one/blob/F1.3.9/README_ONEWWW.md)
of the firmware gives the keys, the functions and the limits. JavaScript is
not supported.

## Build and test

```sh
python demos/onewww/build_onewww.py
python demos/onewww/test_onewww.py
```

The build needs Python 3 and cc65 (`ca65`, `ld65`). It writes
`demos/onewww/build/ONEWWW.SYSTEM` and `ONEWWW.po`. The boot blocks and the
ProDOS kernel come from the demo disk template.

The test runs the program in py65 against a small model of the card: the
SmartPort calls, the keys, the mouse and the quit to ProDOS.
