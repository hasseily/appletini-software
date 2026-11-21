# Appletini Software 1.3.8

This is the software for Appletini firmware **F1.3.8**.

## Changes

- **TINIBROWSER** is the new web browser. It replaces A2MONO and the old
  text browser A2LYNX. The Appletini card does the heavy work, so the
  browser needs firmware F1.3.8.
  - The card filters each web page, so long modern pages show their text.
  - The card converts PNG, JPEG and GIF images. Pictures stand in the text
    flow at the size that the page gives, and a scroll does not load them
    again. Images are on at start; **I** switches them off and on.
  - Forms work, with GET and POST: follow the `[Form: ...]` link and type
    each field.
  - A page holds 48 links.
  [TINIBROWSER guide](demos/appletini_demos/appletini_webserver/README_TINIBROWSER.md)
- **Demo disk.** Menu entry **7 Web Browser** now starts TINIBROWSER. The
  old `A2BROWSE.SYSTEM` and `A2LEGACY.SYSTEM` are no longer on the disk.
- **Removed.** The old text browser (A2LYNX) and the image decoders that
  ran on the 6502. `A2LYNX.po` and `A2MONO.po` are no longer part of the
  release.

## Files

| File | Content |
|---|---|
| `TINIBROWSER.po` | Boots the web browser. |
| `TINIBROWSER.zip` | The browser files, to install on another ProDOS volume. |
| `Appletini-Demos.po`, `.zip` | The demo disk (32 MB) with the HGR menu. |
| `Appletini-Network-Apps.po` | `A2WEBSRV.SYSTEM` (web server) and `A2IMG.SYSTEM` (SHR image viewer). |

All other disks and the libtini archives are the files of Software 1.3.4,
byte for byte. `RELEASE_MANIFEST.json` marks them.

## Limits

- JavaScript and CSS layout do not run. The card keeps no cookies, so a
  login does not stay open. WebP and SVG images do not show.
- The browser needs monochrome video (Video-7 auto monochrome), 256 KiB of
  banked auxiliary RAM, and Ethernet.
- With firmware older than F1.3.8, pictures do not show and pages are cut
  after 64 KiB of raw HTML.

## Validation

The browser tests run the compiled 6502 program in an emulator against a
model of the card: pages, links and anchors, pictures, inline layout, form
links, downloads and fault handling. The demo disk checks pass, and the
browser files on the demo disk are the same bytes as the browser build.

This note records no board test of the final files.
