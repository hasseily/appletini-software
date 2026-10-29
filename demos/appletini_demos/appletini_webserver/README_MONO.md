# A2MONO prototype

A2MONO is an A2LYNX-based web browser for Appletini. It draws text and inline
images in 560 x 384 monochrome DHGRi. The Apple CPU decodes and dithers GIF,
PNG and baseline JPEG images. It fetches images from their original URLs.
It does not use an image conversion server.

## Requirements

- Run at 33 MHz or faster. TURBO is also a target.
- Use Appletini firmware F1.3.4 with DHGRi and the native HTTP/S SmartPort service.
  This build requires its SD-download extension for page requests. Older
  firmware reports `Downloads need updated firmware` without starting a GET.
- Enable Video-7 auto monochrome or select monochrome video output. The
  browser selects Video-7 MONO560 and the Appletini DHGRi page-pair mode.
- Enable at least 256 KiB of banked auxiliary RAM. The image path uses
  RamWorks banks 0 through 3 and restores bank 0 after each access.
- Enable Ethernet and set its network configuration in the Appletini menu.
- With F1.3.4, use a writable FAT SD card and set
  the RTC to UTC. It creates missing seed pairs and embeds its public roots.
  No PEM or Python setup is needed. Certificate errors stop the request.

The local home page works without network access. Web requests use the
native HTTP/S service. This prototype has no legacy IP65 transport fallback.
The client waits while that service follows redirects. Relative links and
image URLs use the final response URL.

Each new request probes the HTTP service again to synchronize its session
counter. A firmware session reset can no longer leave every later request
failing with a stale handle. An interrupted request fails once; the browser
does not replay it. Transport errors show their API code (`E5` is a session
mismatch). A poisoned FIFO still requires restarting the browser.

Same-page fragment links jump to matching `id` or legacy `<a name>` targets
in the loaded HTML. They work through keyboard or mouse navigation, accept
URL-escaped fragments, and keep images enabled if they were already on.
`#` and `#top` return to the top; unknown or invalid targets keep the current
view. Local jumps do not fetch the page again or add a page-history entry.
Links to a different document still load that document at its top.

Requests prefer mobile pages using `User-Agent: Mozilla/5.0 (Mobile; APPLE2LYNX/1)`,
`Sec-CH-UA-Mobile: ?1` and `Save-Data: on`. These are preferences;
some sites return the same HTML. The browser does not guess `m.` hostnames
or send pages through a conversion service. F1.3.4
sends the supplied User-Agent instead of adding its own second
one and includes the SD-download extension required by this browser build.

The ZIP includes `HTTPS/ATNETCA.PEM` as an optional public root override.
F1.3.4 embeds 29 public roots and uses them when
this file is absent from the FAT SD root. An existing PEM still overrides
those roots; remove it to use the embedded bundle, or update it and reboot.
Keep your existing private seed files. See `HTTPS/README.md` for provenance.

F1.3.4 includes Go Daddy Root Certificate Authority - G2
in the 29-root bundle. With this firmware, replace an existing FAT SD-root
`ATNETCA.PEM` with the supplied bundle, or remove it so the embedded bundle
is used, then reboot. Copying the PEM into the ProDOS browser volume does
not update the ARM service's trust store. A page connection failure now
shows its TLS or DNS error instead of a numeric download error; actual file
write failures retain their numeric result.

GitHub currently sends a header line longer than 4096 bytes. F1.3.4 allows
header lines up to 8192 bytes; firmware is not inside the browser ZIP. Older
firmware can stop with a response-limit error.
An untrusted certificate issuer prompts an update of the CA bundle. Other
certificate errors still fail the request.

## Run

Mount `build/mono/A2MONO.po` on a SmartPort drive and boot it. The disk opens
the text-only welcome page. It explains A2MONO and links to Appletini and
Example.com. Press **G** to enter an HTTP or HTTPS URL.
Images start OFF on each page. Press **I** to enable them. The browser then
loads visible images and loads other images as they enter the viewport.
Navigation, Back and Reload return to images OFF.

Links marked with HTML `download` save to the Appletini FAT SD card's
`0:/downloads/` directory. A `download="name.ext"` value supplies a filename
hint. Ordinary page requests also save a response marked
`Content-Disposition: attachment`; MIME type alone does not trigger a save.
The firmware streams that same response to SD, without a second GET or the
browser's 65535-byte document limit. Images fetched for inline display do
not save attachments. Other HTML and plain text responses remain pages.

The status row shows bytes saved and a total when known. Press **Escape**
to cancel and wait for the firmware to close and remove its partial file.
Success shows the completed SD path. Success, failure and cancellation keep
the existing page, its scroll position and its image setting. A failed GET
is not replayed. No file-save confirmation is required.

To install on another ProDOS volume, use an AppleSingle-aware tool to import
`A2MONO.SYSTEM`. Copy `MONO.WEB`, `MONO.NET`, `MONO.GIF`, `MONO.PNG` and `MONO.JPG` into
the same directory. Keep these files from the same build together. The
browser checks each overlay's size before it uses the code.

An overlay error includes its failing stage and a hexadecimal error code.
`O` means OPEN, `R` means READ, `S` means the file size check, and `C` means
CLOSE. ProDOS errors keep their original codes. `S$FF` means the overlay
does not match this build's expected size.

Launch the program as a ProDOS SYS file. BLOAD/CALL entry is not supported.
The ProDOS SYS loader starts at `$2000`. It moves the resident payload to
`$6000` before the graphics backend uses the video pages. Quit returns to
the ProDOS dispatcher.

| Key | Action |
| --- | --- |
| G | Enter a URL |
| Tab / Down | Select the next link |
| Up | Select the previous link |
| Return / Right | Follow the selected link |
| Space | Scroll down |
| P | Scroll up |
| B / Left | Return to the previous page |
| R | Reload |
| I | Enable and load visible images for this page |
| H | Open the local home page |
| Q | Quit |
| Escape | Cancel a request or quit from the page view |

The initial font uses 7 x 8 cells. The screen has 80 columns and 48 rows.
The URL occupies row 0. Page content starts on row 1 and uses 43 rows with
white text on black. The URL and all three footer/status rows use black
text on white. Selected links and the mouse pointer can use an inverse cell.
Images retain normal grayscale polarity. Disabled images use a short
placeholder. Enabled inline pictures occupy fixed boxes of 546 x 144 pixels.
Images shrink to fit and retain their
proportions. The browser clips pictures to the content area.

An Apple Mousecard is optional. Enable a Mousecard slot in the Appletini
configuration. The browser probes the slot ROMs and uses
polled mouse input when it finds a supported card. Click a link to follow
it. Click the footer controls for navigation. The pointer uses a character
cell. Keyboard navigation remains available when no mouse is present.
Mouse polling is throttled to leave a stable frame for DHGRi publication.
Physical pointer smoothness needs a board test.

## Supported content and limits

- The HTML subset includes paragraphs, headings, lists, links, entities and
  inline images. It collapses whitespace. Scripts, CSS and forms do not run.
- With at least 384 KiB of banked auxiliary RAM, the document buffer holds
  up to 65535 bytes of HTML. With fewer banks, it holds the first 8192 bytes.
- A page holds up to 32 links and 12 inline images. History holds two URLs.
- Each encoded image must fit 65535 bytes.
- GIF87a and GIF89a use the first frame. Source dimensions are at most
  4096 x 4096, with a limit of 4,194,304 pixels.
  Interlaced GIFs, local palettes and transparent pixels are supported.
- PNG supports noninterlaced 1-, 2-, 4- and 8-bit grayscale and indexed
  images. It also supports 8-bit RGB, gray-alpha and RGBA images. Alpha
  composites against white. DEFLATE, PNG CRC and zlib checksum errors fail.
- JPEG supports baseline 8-bit grayscale and YCbCr images. The decoder
  uses luminance samples for monochrome output. Progressive JPEG fails.
- WebP is not supported.

The current GitHub response is about 530 KiB of raw HTML. Its first 65535
bytes contain navigation links, which this prototype can display after the
header fix. The main page content starts beyond 106 KiB and does not fit in
the document buffer. This remains a small HTML reader without JavaScript.

## Build

Install Python 3.10 or later and a cc65 snapshot newer than release 2.19.
The compiler must support `--warnings-as-errors`. Put `cl65`, `ca65` and
`ld65` on PATH.
Run from the repository root:

```powershell
python demos/appletini_demos/appletini_webserver/build_mono.py
```

The builder compiles all C sources with `-Os`. It writes the SYS executable,
five code overlays, a bootable 800 KiB ProDOS disk, maps, labels and a SHA-256
manifest into `build/mono/`. `A2MONO.zip` contains the files for installation.
The disk builder copies the unmodified boot blocks and PRODOS kernel from
the existing `assets/AD8088 MSDOS.hdv` input.

The two DHGRi page pairs occupy 32 KiB across MAIN and AUX0. Resident code
uses MAIN `$6000` upward. Overlays share MAIN `$8B00-$B6FF`. Graphics code
and its font use MAIN language-card bank 2 at `$D400-$DFFF`. The initial
payload stages those LC bytes above the resident code. Startup copies them
before it loads the browser overlay. The C software stack reserves
`$B700-$BEFF`; the program uses no C heap.

Resident BSS uses MAIN `$0880-$15FF`. The codec workspaces share
`$1600-$1FFF`; the network reply buffer uses `$1600-$17FF` while no codec
runs. The loader borrows `$1C00-$1FFF` as its ProDOS I/O buffer
while no decoder runs. It closes the file before it starts a decoder.
The decoder initializes its workspace after loading. After decoding, the
browser copies any error message before the loader reuses that workspace.
Prefix setup also uses this buffer before the first file opens. The OPEN
call rejects file I/O buffer addresses below `$0800`.
AUX0 `$6000-$9FFF` holds the GIF dictionary and decode stack. Before loading
`MONO.NET`, the resident gateway saves the complete browser overlay window
to AUX0 `$6000-$8BFF`. It restores those exact 11264 bytes from RAM when the
request finishes, including on error. HTTP finishes before an image decoder
initializes its workspace. Page sinks, transport state and copied result
messages remain resident while NET replaces WEB. After a FIFO timeout, the
gateway performs no ProDOS file operations and refuses further requests
until the browser restarts; it can still restore the page and quit. AUX0
`$A000-$BFFF` holds the fallback 8 KiB HTML buffer. With six distinct auxiliary
banks, HTML uses AUX4 `$2000-$BFFF` and AUX5 `$2000-$7FFE` instead. AUX1 holds
PNG history and filter rows. AUX2 and AUX3 hold encoded image bytes.

## Verify

Install `py65` and Pillow for the developer tests:

```powershell
python -m pip install py65 Pillow
python demos/appletini_demos/appletini_webserver/tests/mono_gfx_verify.py
python demos/appletini_demos/appletini_webserver/tests/mono_verify.py
python demos/appletini_demos/appletini_webserver/tests/mono_integration.py
python demos/appletini_demos/appletini_webserver/tests/mono_jpeg_verify.py
python demos/appletini_demos/appletini_webserver/tests/mono_mouse_verify.py
python demos/appletini_demos/appletini_webserver/tests/mono_document_verify.py
python demos/appletini_demos/appletini_webserver/tests/mono_http_redirect.py
python demos/appletini_demos/appletini_webserver/tests/mono_downloads.py --build demos/appletini_demos/appletini_webserver/build/mono
python demos/appletini_demos/appletini_webserver/tests/mono_features.py --build demos/appletini_demos/appletini_webserver/build/mono
python demos/appletini_demos/tools/test_mono_image.py
python demos/appletini_demos/tools/test_mono_png.py
```

The CPU tests execute the compiled 6502 program and decode its MAIN/AUX page
pairs into PNG captures. The integration model supplies deterministic ProDOS
files and native HTTP FIFO replies. It does not implement TLS or the physical
video capture pipeline. Nominal CPU-cycle calculations exclude network
latency and motherboard waits. The historical TURBO model is not a measured
current-board performance result. Physical display quality, HTTPS setup and
timing need a board test.

`tests/mono_real_boot.py` also boots the packaged disk through real Apple and
SmartPort ROMs and the disk's ProDOS kernel. Supply the installed native
runner library with `--native-library`, the Apple ROM with `--rom`, and the
SmartPort ROMs with `--slot7-rom` and `--slot7-c8-rom`. `--build` selects the
build directory. This test uses no MLI stand-in. It checks the initial
MONO.WEB and MONO.NET loads, the RAM browser restore, the text-only home
page with no image fetch or codec load after **I**, and
normal QUIT call. It also
changes only the OPEN buffer parameter in emulated RAM to `$0400` and checks
that real ProDOS returns `$56` and the loader reports `O$56`. These library
and ROM files are developer-supplied test inputs. They are not runtime or ZIP
dependencies.

`tools/package_mono_release.py` packages a fresh `build/mono` with the durable
records in `evidence/F1.3.4`. It needs the matching firmware file and its
SHA-256 as explicit arguments. It does not read temporary `mono-*` build
folders. Historical paths inside copied reports are provenance, not inputs.

`tests/mono_github.py --build <directory> --github-body <saved-body.html>`
feeds recorded GitHub HTML through the compiled HTTP client and renderer.
It checks navigation text, the 65535-byte cap and image requests staying OFF.
TLS and ARM response-header parsing have separate firmware tests.

The new browser components use the MIT license in `LICENSE_MONO.txt`.
The local JPEG port uses public-domain picojpeg. Its source and provenance
are in `third_party/picojpeg/`.
