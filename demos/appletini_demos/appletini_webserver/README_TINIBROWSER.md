# TINIBROWSER

TINIBROWSER is the web browser for Appletini (before: A2MONO). It shows
text, links, forms and pictures in 560 x 384 monochrome DHGRi.

The Appletini card does the heavy work. It makes the HTTPS connection,
filters each page to a short ASCII page, and converts each image to a
finished 1-bit picture. The Apple lays the page out and draws it. No
conversion server is used.

The old text browser (A2LYNX, `A2BROWSE.SYSTEM`, `A2LEGACY.SYSTEM`) and the
image decoders that ran on the 6502 are removed.

## Requirements

- Appletini firmware **F1.3.8dev7** or later. Older firmware has no page
  and picture service. With F1.3.4 to F1.3.8dev4, pages still load through
  the old parser in the Apple (first 64 KiB of raw HTML) and pictures do
  not show. With F1.3.8dev5, pictures show.
- 33 MHz or faster. TURBO is also a target.
- Video-7 auto monochrome, or monochrome video output. The browser selects
  Video-7 MONO560 and the Appletini DHGRi page-pair mode.
- At least 256 KiB of banked auxiliary RAM for pictures, and 384 KiB for
  pages up to 65,535 bytes. With less, a page holds 8,192 bytes.
- Ethernet enabled, with its network configuration set in the Appletini
  menu. For HTTPS: a writable FAT SD card and the RTC set to UTC.

The local home page works without network access.

## Run

Mount `build/tinibrowser/TINIBROWSER.po` on a SmartPort drive and boot it.
The disk opens the welcome page. Press **G** to enter an HTTP or HTTPS URL.

To install on another ProDOS volume, use an AppleSingle-aware tool to
import `BROWSER.SYSTEM`, and copy `TINI.WEB` and `TINI.NET` into the same
directory. Keep these files from the same build together. The demo disk
has the same three files; its menu item **7 Web Browser** starts them.

Launch the program as a ProDOS SYS file. Quit returns to the ProDOS
dispatcher.

| Key | Action |
| --- | --- |
| G | Enter a URL |
| Tab / Down | Select the next link |
| Up | Select the previous link |
| Return / Right | Follow the selected link, or fill in a form |
| Space | Scroll down |
| P | Scroll up |
| B / Left | Return to the previous page |
| R | Reload |
| I | Switch images off or on |
| H | Open the local home page |
| Q | Quit |
| Escape | Cancel a request or an input, or quit from the page view |

An Apple Mousecard is optional. Click a link to follow it, or click the
footer controls.

## Pages

The card reads up to 4 MiB of HTML and sends the browser at most 65,535
bytes. It removes `<head>`, scripts, styles, comments, SVG, frames and
hidden elements. It changes UTF-8 or Latin-1 text and all entities to
ASCII. Text in other scripts shows as `?`. A page that is still too long
ends with `[Page cut: too long]`.

A page holds up to 48 links and 12 pictures. More links show as plain
text. History holds two URLs. JavaScript and CSS do not run.

Same-page links (`#name`) jump without a new request. Links marked with
HTML `download`, and responses marked `Content-Disposition: attachment`,
save to `0:/downloads/` on the SD card.

## Pictures

- Images are on when the browser starts. **I** switches them off and on.
- The card accepts PNG, JPEG (baseline and progressive) and GIF, up to
  8 MiB and 4,194,304 pixels, and dithers each image. WebP and SVG do not
  show.
- **Display size.** When the page gives `width` and `height` in pixels,
  the picture has that size. If not, it has its natural size. In both
  cases it is at most 546 x 240 pixels, with its proportions, and the card
  does not enlarge an image. Sizes from CSS are not known. One page pixel
  is one screen pixel.
- **Inline.** A picture is a box in the text flow. It starts at the
  current column and takes the text columns and rows that its size needs.
  The text continues on its right, on its last row. A picture that does
  not fit in the rest of the line starts a new line.
- An image that is not loaded yet shows as `[Image]`. When it comes into
  view, the browser loads it and lays the page out again.
- The browser keeps the pictures of the current page in banked auxiliary
  RAM (banks 1 to 3, and 6 to 9 when they exist). A scroll draws them
  again from RAM, without the network. A new page, Back or Reload clears
  them. If the store is full, the oldest pictures load again when needed.

## Forms

The card shows each form as one link: `[Form: name, ...]` when the form
has fields to type, or `[Send form]`. Follow the link. The browser asks
for each field in the order of the names (`Input:`), then sends the form.
Return with no text sends an empty field. Escape cancels.

GET and POST forms work, with hidden fields, checked boxes and the
selected option of a list. Limits:

- The card keeps no cookies, so a login does not stay open.
- A form whose link would be longer than 232 characters shows no link.
- Typed text shows on the screen, also for password fields.

## Build

Install Python 3.10 or later and a cc65 snapshot newer than release 2.19.
The compiler must support `--warnings-as-errors`. Put `cl65`, `ca65` and
`ld65` on PATH. Run from the repository root:

```powershell
python demos/appletini_demos/appletini_webserver/build_tinibrowser.py
```

The builder writes the SYS executable, two code overlays, a bootable
800 KiB ProDOS disk, maps, labels and a SHA-256 manifest into
`build/tinibrowser/`. `TINIBROWSER.zip` contains the files for
installation. The disk builder copies the boot blocks and the PRODOS
kernel from `assets/AD8088 MSDOS.hdv`.

Memory map:

- The two DHGRi page pairs use MAIN and AUX0 `$2000-$5FFF`.
- Resident code uses MAIN `$6000` upward; it ends near `$7DC0`.
- The overlays `TINI.WEB` (browser) and `TINI.NET` (network) share MAIN
  `$8B00-$B6FF`. Before a request, the resident gateway saves the browser
  overlay to AUX0 `$6000-$8BFF` and loads `TINI.NET`; after it, the
  gateway restores the browser from RAM.
- Graphics code and its font use MAIN language-card bank 2, `$D400-$DFFF`.
- The C stack uses `$B700-$BEFF`; the program has no C heap.
- Resident BSS uses MAIN `$0880-$15FF`. The network reply buffer uses
  `$1600-$17FF`. The loader borrows `$1C00-$1FFF` for ProDOS file I/O.
- The page uses AUX4 `$2000-$BFFF` and AUX5 `$2000-$7FFE`, or AUX0
  `$A000-$BFFF` (8 KiB) with fewer banks.
- Pictures use AUX1 to AUX3 and AUX6 to AUX9, `$2000-$BFFF` each.

After a FIFO timeout the gateway refuses further requests until the
browser restarts; it can still restore the page and quit.

## Verify

Install `py65` and Pillow for the developer tests:

```powershell
python -m pip install py65 Pillow
python demos/appletini_demos/appletini_webserver/tests/mono_arm_images.py
python demos/appletini_demos/appletini_webserver/tests/mono_inline.py
python demos/appletini_demos/appletini_webserver/tests/mono_forms.py
python demos/appletini_demos/appletini_webserver/tests/mono_verify.py
python demos/appletini_demos/appletini_webserver/tests/mono_integration.py
python demos/appletini_demos/appletini_webserver/tests/mono_anchors.py
python demos/appletini_demos/appletini_webserver/tests/mono_features.py
python demos/appletini_demos/appletini_webserver/tests/mono_downloads.py
python demos/appletini_demos/appletini_webserver/tests/mono_http_redirect.py
python demos/appletini_demos/appletini_webserver/tests/mono_http_faults.py
python demos/appletini_demos/appletini_webserver/tests/mono_home.py
python demos/appletini_demos/appletini_webserver/tests/mono_html.py
python demos/appletini_demos/appletini_webserver/tests/mono_gfx_verify.py
python demos/appletini_demos/appletini_webserver/tests/mono_mouse_verify.py
```

The tests run the compiled 6502 program in py65 against a model of ProDOS
and of the card. The model has the picture service; most tests feed raw
HTML through the Apple parser, which stays as the path for older
firmware. `mono_forms.py` uses the model with the page service. The page
filter and the image conversion have their own tests in the firmware
repository (`test_net_page.py`, `test_net_image.py`,
`test_net_service.py`). None of these tests is a board test.

The browser uses the MIT license in `LICENSE_TINIBROWSER.txt`.
