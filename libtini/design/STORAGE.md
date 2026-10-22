# Standard ProDOS files and resource packs

Include `libtini/storage.h`. These synchronous foreground APIs use existing
ProDOS MLI calls through `$BF00`; they do not require private SmartPort
services. Only one transaction may run at a time. A reentrant call returns
`TI_E_BUSY` before opening another file.

## Files

`ti_file_read(name, dst, capacity, &length)` reads a whole file into a validated
near buffer. Names are relative to the current ProDOS prefix: 1..15 uppercase
characters, starting with a letter, then letters, digits or periods. Paths,
lowercase and underscores are rejected. The buffer and length pointer remain
borrowed only until return. An empty file can use a null buffer and zero
capacity. A file larger than capacity returns `TI_E_RANGE` without truncating
the read into a partial successful result. Use the streamed pack loader for
larger banked resources. Ordinary file I/O does not require `ti_init` while
graphics is inactive.

`ti_file_write(name, src, length)` creates or opens a file, writes its contents,
sets its exact EOF and closes it. Writing a shorter value truncates the old
file; zero length creates/truncates an empty file. The source must be a valid
near buffer for the whole synchronous call. The aligned 1024-byte ProDOS I/O
buffer is reserved at MAIN `$B000-$B3FF`; applications must not borrow it.
The address comes from the linker layout's `_ti_file_buffer`. A game's own
layout can leave that symbol out and use the memory, and then no file call
links; see [games](GAMES.md#layouts).

Only `TI_OK` makes a returned read length/data a completed file transaction.
On an error, discard that transaction's output even if some bytes were read.
A failed write can leave a changed or partial file. Use independently
validated alternating save slots rather than treating a single write as
atomic. Files are closed on success and all handled errors;
a close/flush error is itself reported as `TI_E_IO`.

`ti_file_last_error` preserves the underlying ProDOS error for I/O failures.
Successful transactions reset it to zero. An unexpected successful short
read or write records `$4C`. Argument, range or resource errors do not imply
a new ProDOS error; interpret the error byte alongside the API result.
The MLI adapter preserves application bytes `$4E/$4F` around OS calls.

## AUX0 and driver ownership

Standard ProDOS `/RAM` can use the same AUX0 bytes that hold SHR. A mode change
alone cannot make those bytes safe for file I/O. When graphics is active, a
transaction therefore needs one additional temporary resource slot and 32768
bytes. Before any MLI call it saves the picture, disables SHR and restores the
latest OS AUX0 image. After the transaction, it captures any OS changes into
that backup, restores the picture and re-enables SHR. Final graphics cleanup
restores the updated OS image, not the old launch snapshot.

If that temporary allocation fails, the call returns `TI_E_NOMEM` before any
MLI operation or OS-memory handoff. Reserve resource capacity accordingly:
the backbuffer, persistent OS backup and temporary storage picture consume
three of eight slots during a displayed save/load, in addition to assets.
No `/RAM` device is disconnected, reformatted or replaced.

Registered driver pause/resume hooks surround the transaction, including
allocation-error recovery. They let the shared audio driver stop its timer
and device activity while the OS owns the machine. Storage never runs inside
an IRQ. Long operations mark a timing-service gap; they do not manufacture
missed display frames or silently advance simulation. Buffers, bank selectors
and C8 device ownership must not be changed by another foreground owner during
the call.

## TPK1 resources

`ti_pack_load(file, entry, &handle, &size)` validates the complete directory,
allocates one resource and streams the selected payload in 128-byte pieces.
The successful caller owns the returned handle. Every error closes the file,
frees any partially loaded resource, and leaves both outputs zero, including
a final CLOSE failure. Allocation and resource operations require an active
`ti_init` grant. Entry names permit uppercase letters, digits, periods and
underscores after their initial letter; file names retain ProDOS's narrower
rules.

The directory has 1..16 entries. Header `TPK1` is followed by LE16 count and
LE16 reserved zero. Every 24-byte entry contains a 16-byte NUL-padded name,
LE32 absolute payload offset and LE32 nonzero size. Names must be unique and
strictly sorted; padding must be all zero. Offsets must follow the complete
directory and be sorted without overlap, with every byte inside the 24-bit
ProDOS file EOF. Unselected entries are checked too. Missing entries return
`TI_E_UNAVAILABLE`; malformed structure returns `TI_E_FORMAT`; disk/read/seek
errors return `TI_E_IO`. Resource exhaustion returns `TI_E_NOMEM`.

The pack loader does not expose a mapped pointer or convert an image header
into a surface automatically. Read/validate TI4/TIF/TIM metadata, then make
the explicit handle/offset views described in [GRAPHICS.md](GRAPHICS.md).
`tools/assets.py pack` creates deterministic matching packs. The current disk
packager supports seedling/sapling files up to 131072 bytes each; larger packs
require another documented ProDOS packaging tool even though the runtime can
stream them into sufficient granted memory.

## Checks and limits

```powershell
python tests/storage_validate.py --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe
python -m unittest discover -s tests -p test_disk_release.py -v
```

The compiled storage suite passes 1666 checks across twelve focused CPU-model
runs, and 1451 checks on each native `vtw33`/historical `turbo-f122` run. It
tests real target MLI parameter construction, reads, creates, overwrite/EOF,
empty files, invalid names/ranges, every directory validation class, absent
entries, allocation failure, file/resource cleanup, reentrancy and injected
READ/WRITE/short-transfer/SETEOF/CLOSE failures. The focused OS model changes
AUX0 during MLI calls and verifies that repeated loans restore the picture
while final shutdown retains the new OS bytes. It also mutates `$4E/$4F` to
verify the target adapter restores them.

Three host volume tests cover 32-file directories, empty saves, sapling index
high bytes, an 8192-block volume with a second allocation bitmap, corruption,
directory/volume limits and repeatable payloads. Evidence is
`build/storage/validation.json`; the fixture disk is `build/storage/storage.po`.

These are host/emulator results. The native MLI stand-in is not real ProDOS,
and the focused AUX mutation fixture is not a real `/RAM` filesystem. Board
tests must save/load while displaying SHR at 33 MHz and TURBO, verify existing
`/RAM` files after exit, and exercise actual disk-error/flush behavior.
