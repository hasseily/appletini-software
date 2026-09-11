# FATDOG MAGIC

This self-booting 32 MB ProDOS disk opens a full-screen HGR folder menu,
styled like the Appletini demo disk: a large title, mixed-case bitmap font,
and a highlighted selection bar. Choose a folder to start its slideshow.

All 32 images from fgr1.po and fgr2.po are in **Standard HGR**. ProDOS names
cannot contain spaces, so the directory is stored as `STANDARD.HGR` with
mixed-case metadata. The menu displays periods as spaces and honors GS/OS
case bits. The original image filenames, 8192-byte contents, $4000 load
addresses, and directory order are preserved.

Conversions by FATDOG - Code by RIKKLES. Original artwork by its creators.

The **Brooks SHR-3200** folder contains 20 images randomly selected from
`~/Downloads/brooks_shr`. Their original exports and fixed selection are
bundled in `assets/brooks_shr/`, so ordinary rebuilds keep the same images.
The legal ProDOS directory name is `BROOKS.SHR.3200`; the menu restores
the hyphen for this display label. Both image fields and all line palettes
are preserved. Only palette bank/address pointers are changed on import.

The full interlaced Brooks images use matching palette locations: first
field AUX $0400-$1CFF, second field MAIN $0400-$1CFF. The loader uses the
existing slot-7 LINTXT interface to ARM a temporary 6400-byte capture window
for each CPU palette copy, then issues OFF and waits for capture to stop.
It never issues SHOW or HIDE. Normal capture ranges, firmware and renderer
are unchanged; extra capture is disabled throughout the slideshow wait.
Shared-palette exports are copied into both banks. Separate second palettes
are uploaded independently. Both 200-line fields remain intact for 400-line
interlace; the earlier 200-line compatibility disk remains in validation/.
The MAIN palette is installed after the final ProDOS CLOSE because SmartPort
uses MAIN $07F8 as slot workspace. No disk call follows that upload until
navigation starts the next operation.

Appletini hardware needs the LINTXT v1.0 interface identified by its slot-7
ROM descriptor and live DEVSEL identity. Full-memory emulators can display the same RAM layout without
this interface; the loader skips its commands when the descriptor is absent.
Older Appletini firmware without this interface cannot receive the extra
palette RAM writes. The disk does not silently reduce images to 200 lines.

## Folder menu

- Up/Down, Left/Right, or P/N: select a folder; wrap at either end.
- Return or Space: open the selected folder.
- Esc: quit to the ProDOS program selector.

The menu waits for a choice. It lists the disk's root subdirectories in
directory order, scrolling when there are more than 12. Folder names are
read from disk each time you return to the menu; the selected folder's
images are scanned each time it is opened. Neither list is compiled into
the viewer. Files at the volume root are not slideshow entries.

Moving the selection updates only the old and new highlight rows and the
current number in "x of y". Scrolling repaints the visible folder rows;
the title, credits, controls and total stay in place.

Create more root folders and add images with your usual ProDOS disk tool;
no viewer rebuild is needed. Each folder loops independently, starting at
its first image. The loader accepts raw ProDOS BIN and uncompressed picture ($C1) files.
It recognizes the demo disk's HGR, HGRi/HGRp, DHGR, DHGRi/DHGRp, SHR,
SHR4, RGGB, PAL256, and Brooks 3200 layouts, including SHR interlace and
page-flip pairs. Other file sizes/types and nested directories are skipped. An empty folder or a folder with no supported
images shows a message and returns to the menu after a keypress.

Folders can have any name, and one folder can contain several formats.
The loader distinguishes ambiguous sizes by the embedded A2Li signature:
16K with an A2Li marker in the second main page is HGRi/HGRp; otherwise it
is ordinary DHGR. At 32K, an A2Li marker in the fourth 8K chunk identifies
DHGRi/DHGRp; otherwise the file is SHR. Use the self-describing paged files
produced by the Appletini/SDD tooling. The marker selects interlace (1) or
page flip (2); the Apple program itself never alternates PAGE1/PAGE2.

Video-7 MIX/COL140M is selected for DHGR images in a folder ending in
`.MIX`, such as `DHGR.MIX`. This uses the demo loader's Video-7 switch
sequence (needed by its FACE.I example). Other folders use normal Video-7
mode. Video-7 selection is separate from the A2Li interlace marker.

The viewer holds up to 64 folder names and 255 images per folder; an image
list exceeding the limit shows a message instead of playing a truncated list.

## Slideshow controls

- Right arrow, N, or Return: next image.
- Left arrow or P: previous image.
- Space: pause or resume automatic playback.
- R: return to the first image in this folder.
- H: HGR help with conversion credit, folder, filename, and playback state.
- Any key on help: reload and return to the current image.
- Esc from the slideshow or help: return to the folder menu.

Each picture uses its full image mode and stays up for 480 display frames:
about 8 seconds at 60 Hz, or 9.6 seconds at 50 Hz. On machines without a
usable VBL signal, the viewer uses a delay of about 8 seconds at 1 MHz.
An accelerator can shorten that fallback delay. Manual navigation keeps
the pause state. Reopening a folder starts automatic playback at image 1.

Images load into their actual display memory, visibly replacing the previous
image. PAGE1 stays selected: both pages are available to interlaced/paged
formats, and AUX is available to DHGR and SHR. Menu and help draw HGR in
main page 1. Returning from help reloads the current image and preserves
the pause state. Native hardware without the relevant extended video
renderer shows only the modes it supports; Appletini interprets the
embedded extension markers.

The raw file-to-memory layouts match the Appletini demo loader:

| Format | File bytes in order | Destination |
| --- | --- | --- |
| HGR | 8K | MAIN $2000-$3FFF |
| HGRi / HGRp | 8K + 8K | MAIN $2000, then MAIN $4000 |
| DHGR | 8K + 8K | AUX $2000, then MAIN $2000 |
| DHGRi / DHGRp | four 8K chunks | AUX $2000, MAIN $2000, AUX $4000, MAIN $4000 |
| SHR family | first 32K | AUX $2000-$9FFF |
| Brooks 3200 (39168 bytes) | remaining 6400 bytes | MAIN $2000-$38FF line palettes |
| SHR pair (64K) | remaining 32K | MAIN $2000-$9FFF second field |
| Brooks pair (71936 bytes) | AUX field, shared 6400-byte palettes, MAIN field | AUX $2000, palettes copied to AUX and MAIN $0400, MAIN $2000 |
| Brooks pair (78336 bytes) | same, plus second 6400-byte palettes | AUX $2000, first palette AUX $0400, MAIN $2000, second palette MAIN $0400 |

The 71936/78336-byte Brooks files use the normalized palette pointers from
`tools/brooks.py`; their file order follows SuperDuperDisplay/extras/MemoryLoader.cpp.
Each field's control bytes at $9DF9-$9DFB select its own bank and $0400 pointer.
Auxiliary data is staged through main memory with main writes selected for
ProDOS calls, then copied using RAMWRT. A2Li mode and SHR magic are published
after their pixels are complete; loading uses no frozen-frame transaction.

## Disk and build

`dist/FATDOG_MAGIC.po` is exactly 32 MiB (33,554,432 bytes), in ProDOS
block order. The volume uses 65,535 blocks, with one final padding block,
matching the Appletini demo disk. Mount it as a SmartPort/hard-disk boot
volume. Its volume name is FATDOG.MAGIC; ProDOS starts MAGIC.SYSTEM.

The disk includes ProDOS 2.4.3 and BASIC.SYSTEM from the bundled
`assets/ProDOS_2_4_3.po` master. To restart from BASIC, enter -MAGIC.SYSTEM.

Rebuild from the appletini-software repository root:

```sh
python demos/fatdog_magic/tools/build_fatdog_magic_disk.py
python demos/fatdog_magic/tools/verify_disk.py
```

The build uses the two bundled HGR disks and the fixed Brooks selection
in assets/ and writes
dist/FATDOG_MAGIC.po. Pass input disk paths and --output to override them.
Rebuilding creates a fresh disk from these inputs; preserve any manually
added folders by keeping your customized disk separately.

Building needs Python 3, Java, AppleCommander, and ACME. Set APPLECOMMANDER
(or APPLECOMMANDER_JAR) to the JAR path and ACME_EXE to the assembler path
when needed. dist/manifest.json records input and image hashes, image
paths, the viewer hash, and the disk-image hash. Brooks source filenames
and original hashes are recorded in assets/brooks_shr/selection.json. Builds are self-contained
and do not need a sibling firmware checkout.

`magic.a65` contains startup and slideshow playback, `directories.a65`
contains directory scanning, `formats.a65` handles bank routing and video
switches, `palettes.a65` contains the commented ARM/upload/OFF support,
and `ui.a65` contains the HGR interface. The bank layouts and
switch sequences follow appletini-one/software/a2imgview.a65.
Code lives at MAIN $A000-$BAFF, outside the MAIN/AUX $2000-$9FFF image range.
The ProDOS I/O buffer occupies MAIN $BB00-$BEFF. Brooks palettes occupy
MAIN/AUX $0400-$1CFF. The MAIN palette is staged at AUX $A000-$B8FF, then
swapped pagewise with MAIN $0400-$1CFF after CLOSE. The old low MAIN contents
are restored before menu/help/next-image OPEN, including names and paths
saved at AUX $A500-$B5FF and SmartPort's slot workspace. The
AUX-read restore loop executes in zero page with interrupts masked so
RAMRD cannot bank out the running code. The prior interrupt state is restored.
Folder/image names share $0900-$18FF; the current folder label is saved
before the image list reuses that memory. Paths occupy $1900-$19FF,
and directory/probe reads $1D00-$1EFF, just beyond the palette window.
`assets/font7x8.bin` bundles the Appletini demo launcher's 768-byte font
(ASCII 32-127, eight scanlines per glyph, low bit at the left), originally
generated by appletini-one/scripts/gen_hgr_assets.py. The builder generates
the FATDOG title and HGR row tables from this bundled font.

The independent disk verifier checks the complete directory tree, parent
links, directory counts, allocation bitmap, boot order, boot blocks, system
files, image metadata, and all 52 image payloads. Brooks verification
permits only palette pointer changes; all pixels and palettes match the originals. It writes
dist/validation.json. These checks alone do not run an emulator.

For runtime tests, use a built GSSquared checkout and Pillow:

```sh
python demos/fatdog_magic/tools/smoke_test.py --gssquared-root PATH_TO_GSSQUARED
```

The test boots an enhanced IIe and a IIgs, compares all 32 displayed images
to the source bytes, verifies both fields and all palettes of the 20 Brooks
images, exercises controls and timing, and modifies a separate
disk copy after compilation to test folder discovery, scrolling, and
unsupported files. Pass --emulator for a non-default executable, or
--platform 3 / --platform 5 for one machine. Windows additionally uses the
installed gs2-mcp.exe (override with GS2_MCP) because CPython does not expose
AF_UNIX there. Reports and HGR framebuffer captures go in validation/.
`python demos/fatdog_magic/tools/verify_menu_updates.py` additionally uses
py65 to execute the assembled menu, compare every resulting pixel, and
trace every HGR write. It checks all navigation keys, scrolling, wrap,
digit changes, and menus with 0, 1, 2, 12, 13, 18 and 64 folders.
To test every bank layout with the actual Appletini demo image corpus:

```sh
python demos/fatdog_magic/tools/smoke_test.py --gssquared-root PATH_TO_GSSQUARED --formats-from PATH_TO_APPLETINI_ONE
```

This creates a separate 800K validation disk, mixes all formats in one
folder, verifies every destination byte, tests help/reload for every format,
and checks Video-7 MIX selection/reset. --formats-only runs just that suite.
The output disk contains 32 images in Standard HGR and 20 in Brooks SHR-3200.
Pass --appletini with a compatible --emulator to exercise Appletini video modes.
Emulator tests do not substitute for physical hardware tests.

The loader/capture test executes the assembled 6502 program with modeled
ProDOS reads and LINTXT acknowledgements, filters the actual RAM writes
through the normal and temporary windows, and sends the resulting shadows
to the unchanged Appletini renderer:

```sh
python demos/fatdog_magic/tools/verify_palette_upload.py --firmware-root PATH_TO_APPLETINI_ONE
```

This checks all 20 images and a synthetic distinct-second-palette case
against an independent pixel reference, verifies catalog restoration, and
exercises ARM errors, capture loss and bounded timeouts. It also checks that
absent-interface machines receive no DEVSEL writes. Reports include artifact
hashes and are separate from physical hardware validation. Host test code
is never included in MAGIC.SYSTEM. The old static-range regression remains
available in `verify_brooks_capture.py` for reproducing the previous failure
with the preserved original disk under validation/original-full-before-upload/.

Git ignores build/, dist/, and validation/. The bundled input disks and
font are required source assets and belong in the repository.

Technical references:

- https://prodos8.com/docs/techref/writing-a-prodos-system-program/
- https://prodos8.com/docs/techref/memory-use/
- https://prodos8.com/docs/techref/file-organization/
- https://prodos8.com/docs/techref/calls-to-the-mli/
- https://apple2.gs/technotes/tn-iigs-040/
