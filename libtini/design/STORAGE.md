# Standard ProDOS files and resource packs

Include `libtini/storage.h`. These synchronous foreground APIs use existing
ProDOS MLI calls through `$BF00`. They need no private SmartPort services.
Only one transaction can run at a time. A reentrant call returns `TI_E_BUSY`
before it opens another file.

## Files

`ti_file_read(name, dst, capacity, &length)` reads a whole file into a
checked near buffer. Names are relative to the current ProDOS prefix: 1..15
uppercase characters, a letter first, then letters, digits or periods. The
call rejects paths, lowercase letters and underscores.

The buffer and the length pointer are borrowed only until the call returns.
An empty file can use a NULL buffer and a zero capacity. A file larger than
the capacity returns `TI_E_RANGE`. The call does not truncate the read into a
partial successful result.

Use the streamed pack loader for larger banked resources. Ordinary file I/O
needs no `ti_init` while graphics is not active.

`ti_file_write(name, src, length)` creates or opens a file, writes its
contents, sets its exact EOF and closes it. A shorter write truncates the old
file. A zero length creates or truncates an empty file. The source must be a
valid near buffer for the whole synchronous call.

The aligned 1024-byte ProDOS I/O buffer is reserved at MAIN `$B000-$B3FF`.
Applications must not use it. The address comes from the `_ti_file_buffer`
symbol of the linker layout. The layout of a game can leave that symbol out
and use the memory. Then no file call links. See
[GAMES.md](GAMES.md#layouts).

Only `TI_OK` makes a returned read length and its data a completed file
transaction. After an error, discard the output of that transaction, also if
some bytes were read. A failed write can leave a changed or partial file.

Use two save slots that are checked independently, in turn. Do not treat a
single write as atomic. The calls close the file on success and on all
handled errors. A close or flush error returns `TI_E_IO`.

`ti_file_last_error` keeps the ProDOS error of an I/O failure. A successful
transaction resets it to zero. An unexpected short read or write that ProDOS
reports as successful records `$4C`.

Argument, range and resource errors do not set a new ProDOS error. Read the
error byte together with the API result. The MLI adapter keeps the
application bytes `$4E/$4F` around OS calls.

## AUX0 and driver ownership

Standard ProDOS `/RAM` can use the same AUX0 bytes that hold SHR. A mode
change alone does not make those bytes safe for file I/O. Thus, when graphics
is active, a transaction needs one more temporary resource slot and 32768
bytes.

Before any MLI call, the transaction saves the picture, disables SHR and
restores the latest OS AUX0 image. After the transaction, it keeps all OS
changes in that backup, restores the picture and enables SHR again. The final
graphics cleanup restores the updated OS image, not the launch snapshot.

If the temporary allocation fails, the call returns `TI_E_NOMEM` before any
MLI operation or OS-memory handoff. Reserve resource capacity for this. During
a save or load with the screen on, the backbuffer, the OS backup and the
temporary picture use three of the eight slots, in addition to assets.

No `/RAM` device is disconnected, formatted or replaced.

Registered driver pause and resume hooks surround the transaction, the
recovery from an allocation error included. They let the shared audio driver
stop its timer and device activity while the OS owns the machine. Storage
never runs inside an IRQ.

Long operations mark a timing-service gap. They do not invent missed display
frames or advance the simulation. No other foreground code can change
buffers, bank selectors or C8 device ownership during the call.

## TPK1 resources

`ti_pack_load(file, entry, &handle, &size)` checks the complete directory,
allocates one resource and streams the selected entry in 128-byte pieces. On
success, the caller owns the returned handle.

Every error closes the file, frees a partly loaded resource and sets the two
outputs to zero, a final CLOSE failure included. Allocation and resource
operations need an active `ti_init` grant. Entry names permit uppercase
letters, digits, periods and underscores after the first letter. File names
keep the narrower rules of ProDOS.

The directory has 1..16 entries. The header `TPK1` is followed by an LE16
count and an LE16 reserved zero. Each 24-byte entry contains a 16-byte
NUL-padded name, an LE32 absolute data offset and an LE32 nonzero size.

Names must be unique and strictly sorted, and the padding must be all zero.
Offsets must follow the complete directory and be sorted without overlap.
Every byte must be inside the 24-bit ProDOS file EOF. The loader also checks
the entries that it does not load.

A missing entry returns `TI_E_UNAVAILABLE`. A malformed structure returns
`TI_E_FORMAT`. Disk, read and seek errors return `TI_E_IO`. Resource
exhaustion returns `TI_E_NOMEM`.

The pack loader gives no mapped pointer, and it does not convert an image
header into a surface. Read and check the TI4, TIF or TIM header, then make
the explicit handle and offset views that [GRAPHICS.md](GRAPHICS.md)
describes.

`tools/assets.py pack` makes deterministic packs in this format. The disk
packager supports seedling and sapling files of up to 131072 bytes each.
Larger packs need another ProDOS packaging tool, although the runtime can
stream them into enough granted memory.

## Checks and limits

```powershell
python tests/storage_validate.py --cc65-home D:/Repos/cc65 --cc C:/msys64/ucrt64/bin/gcc.exe
python -m unittest discover -s tests -p test_disk_release.py -v
```

The compiled storage suite passes 1666 checks over twelve focused CPU-model
runs, and 1451 checks on each of the native `vtw33` and `turbo-f122` runs. It
tests the target MLI parameters, reads, creates, overwrites and EOF, empty
files, invalid names and ranges, every directory check, absent entries,
allocation failure, file and resource cleanup and reentrancy.

It also injects READ, WRITE, short-transfer, SETEOF and CLOSE failures. The
focused OS model changes AUX0 during MLI calls. It checks that repeated loans
restore the picture and that the final shutdown keeps the new OS bytes. It
also changes `$4E/$4F` and checks that the target adapter restores them.

Three host volume tests cover 32-file directories, empty saves, sapling index
high bytes, an 8192-block volume with a second allocation bitmap, corruption,
directory and volume limits and repeatable payloads. The results are in
`build/storage/validation.json`, and the fixture disk is
`build/storage/storage.po`.
