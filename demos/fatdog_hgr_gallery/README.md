# FATDOG HGR Gallery

This self-booting 800K ProDOS image combines all 32 HGR images from fgr1.po
and fgr2.po. It preserves their filenames, 8192-byte contents, and $4000 load
addresses. The gallery fills all 192 HGR lines and loads each new image
into the hidden graphics page before switching pages.

HGR conversions by FATDOG. Original artwork by its original creators.

dist/FATDOG_HGR.po contains 1600 blocks (819,200 bytes) in ProDOS block order,
matching an 800K Apple 3.5-inch disk. Mount it in an emulated 3.5-inch
drive, write it to an 800K disk with a compatible disk-image tool, or
mount it as a SmartPort boot volume. ProDOS
starts GALLERY.SYSTEM automatically. The credit/help screen waits for
1800 display frames (about 30 seconds at 60 Hz, or 36 seconds at 50 Hz),
then the slideshow starts and loops through both disks in their original
directory order. Press any key to start sooner. No keypress is required.

Controls:

- Right arrow, N, or Return: next image.
- Left arrow or P: previous image.
- Space: pause or resume automatic playback.
- R: return to the first image.
- H: help, conversion credit, current filename, and playback state.
- Any key on the help screen: return to the current image.
- Esc: quit to the ProDOS program selector.

Each picture stays up for 480 display frames: about 8 seconds at 60 Hz,
or 9.6 seconds at 50 Hz. On machines without a usable VBL signal, the
viewer uses a delay of about 8 seconds at 1 MHz. An accelerator can
shorten that fallback delay. Manual navigation keeps the pause state.

The disk includes ProDOS 2.4.3 and BASIC.SYSTEM from the bundled
assets/ProDOS_2_4_3.po master. To restart from BASIC, enter -GALLERY.SYSTEM.

Rebuild from the appletini-software repository root:

    python demos/fatdog_hgr_gallery/tools/build_fatdog_hgr_disk.py
    python demos/fatdog_hgr_gallery/tools/verify_disk.py

The build uses the two bundled input disks in assets/ and writes its
800K image to dist/FATDOG_HGR.po. It needs no sibling firmware checkout
or Downloads files. Pass input paths and --output to override them.

Building needs Python 3, Java, AppleCommander, and ACME. Set APPLECOMMANDER
(or APPLECOMMANDER_JAR) to the JAR path and ACME_EXE to the assembler path
when they are not in their default locations. dist/manifest.json records
every input and image hash, the viewer hash, and the disk-image hash.

The source is gallery.a65; generated assembly inputs, symbols, and the
viewer binary go in build/. The 800K .po image is the build output.
Git ignores build/, dist/, and validation/, including local disk images,
manifests, emulator captures, test reports, and one-off test scripts.
The three disks in assets/ are required inputs and belong in the repo.

Technical references:

- https://prodos8.com/docs/techref/writing-a-prodos-system-program/
- https://prodos8.com/docs/techref/memory-use/
- https://apple2.gs/technotes/tn-iigs-040/

The builder and verification tool check image payloads, system files,
boot order, boot blocks, and block allocation. Verification uses the
bundled inputs and the current build manifest; it needs no old test
captures or local history. It writes dist/validation.json.

These file checks do not run an emulator or test a physical drive.
