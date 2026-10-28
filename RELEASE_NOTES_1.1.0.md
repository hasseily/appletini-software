# Software 1.1.0

STARFALL adds an online leaderboard at https://appletini.org/leaderboards/starfall.
The card submits `platform: appletini`; the browser player submits `platform: web`.
Each finished run keeps its ID and exact score/name across retries. Rankings
use server UTC and each public name's best score. Names and scores are public
claims. Offline play remains available without the network service.

STARFALL also adds five bosses, fixes Excalibur's brief centre-screen flash,
and fires a collected bomb at the maximum inventory while keeping that count.
The release disk matches the version accepted in the full card gameplay and
leaderboard test. Use 33 MHz or TURBO; the game needs at least about 26 MHz.

A2LYNX browses HTTPS text directly through the F1.3.3 ARM service. It follows
redirects, checks certificates and hostnames, accepts HTML/plain text, and
limits a page to 10 KiB. It does not run JavaScript. Older firmware selects
the included IP65 browser. The demos disk includes both browser programs.

libtini adds an optional start/poll/read/cancel HTTP/S API and JSON Pointer
lookups. It leaves the Ethernet TCP/IP and TLS work on the ARM. The SDK
includes the `net_check` example, target tests, developer reference and the
leaderboard backend source. One shared fault flag protects NET and AMEM
from reusing an uncertain private FIFO. Existing CPU paths stay available.

For card networking, install [F1.3.3](https://github.com/hasseily/appletini-one/releases/tag/F1.3.3)
and run its HTTPS setup once per board. Set the RTC date/time, UTC offset
and Ethernet DNS. HTTP owns Ethernet during a request; FTP/SD maintenance
and concurrent IP65 connections cannot share it. Heavy RSA can stutter:
the combined board test measures up to 70.056 ms between USB1 service calls.
Both CPU speeds pass saved-file, filesystem, source-video and capture checks.

All registered SDK checks pass, including isolated source builds, native
65C02 transport/fault tests and ROM boots with Mockingboard and Phasor.
These checks stay separate from the physical-card results. A2LYNX passes
public HTTPS, redirects, rejection, cancellation and stock-firmware fallback
tests on the card. The user accepts STARFALL gameplay and the leaderboard.

The package includes STARFALL.po, A2LYNX.po, the updated Appletini-Demos.po,
libtini source and SDK archives, checksums and the retained 1.0.0 game disks.
Every other 1.0.0 game image is copied unchanged, with its prior licence and
media terms. `RELEASE_MANIFEST.json` records those source release hashes.
The source-only SDK archive omits ProDOS. Boot disks and the local SDK
archive contain the separately installed ProDOS kernel; retain its terms.
Browser player sources and notices remain available beside the web player.
