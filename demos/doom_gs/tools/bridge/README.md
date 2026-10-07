# bridge: upstream's symbols, constants and structures

A small standard-library Python package that describes upstream's game as
its include files and link map do, for the build tools in `tools/native`
(`glayout.py`, `llayout.py`, `levelconv.py`, `rtables.py`, `umodel.py`,
`gcallgraph.py`, `s2msgs.py`). It copies nothing from upstream: the
files are read in `build/` at run time, so `tools/fetch_upstream.py` and
`tools/v816/imgmatch.py` (which writes `build/linkmap.json`) must have run
first, as `build.sh` does.

| File | What it is |
| --- | --- |
| `linkmap.py` | `Symbols`: the labels of `build/linkmap.json` |
| `incfile.py` | A parser of upstream's `.inc` files (`NAME .equ EXPR`) |
| `fields.py` | Field types and structures |
| `schema.py` | Upstream's structures: offsets from the include files, types written by hand |
| `upstream.py` | `Schema`: the constants and the structures, built once |
| `layout.py` | `Leaf`: one value of a native layout and its encoding |

## Symbols (`linkmap.py`)

`Symbols()` reads `build/linkmap.json`. `address('unit:label')` gives a
label's address; a bare `label` works when only one unit has it, and is an
error otherwise. Lookups are exact, never the nearest label.
`label(ref)` gives the label with its size (up to the next label of its
fragment, or the fragment's end), its section and kind. `units` holds each
unit's labels and `.equ` values; `fragments` the placed fragments in
address order; `by_address` the labels at each address.

## Constants (`incfile.py`)

`incfile.parse(path)` reads the lines `NAME .equ EXPRESSION` of one of
upstream's `src/iigs/*.inc` files, in file order. Expressions take
decimal and `0x` numbers, `'c'` characters, names defined earlier in the
file or given by the caller, `+ - * / % << >> & | ^ ~` and parentheses.
Lines inside `#if`/`#endif` are read as they come (the files use the
guards only to be included once). `as_dict` turns the list into a dict.

## Structures (`fields.py`, `schema.py`)

A structure (`Struct`) is a list of fields that tile its size exactly:
every byte of a record belongs to one field, or the structure is refused
(`StructError`). A field has an offset, a type and a class (`state` by
default; also `cache`, `list` (a link of a list), `thinker` (the thinker
header) and `kindcache`). The types:

| Type | Meaning |
| --- | --- |
| `Int(size, signed)` | a number of 1, 2 or 4 bytes, little-endian |
| `Ref(targets)` | a far pointer to one of the object kinds `targets` |
| `Fn()` | a thinker function: 24 bits |
| `Array(elem, n)` | n values of a type |
| `Sub(struct)` | a structure inside a structure |
| `Raw(size)` | bytes that are not numbers or pointers (names) |

`fields.spec` reads a short form: `i8 u8 i16 u16 i32 u32 fixed angle`,
`raw:N`, `ref:K1|K2`, `fn`, with `*N` for arrays (`i16*6`).

`schema.py` builds upstream's structures (`build_structs`):

- Offsets and record sizes come from `offsets.inc` (`OFS_<S>_<FIELD>`,
  `SIZEOF_<S>`). Every `OFS_` of a structure must have a type in `TYPES`
  or be a declared alias (`ALIASES`), and the fields must tile the record,
  so a new or moved field in upstream stops the tools.
- The structures `offsets.inc` lacks (the lights, the floor mover, the
  scroller, `wbstartstruct_t`) come from their source files' `.equ`
  values as the link map has them (`LOCAL_STRUCTS`).
- Field types (fixed, int, pointer and to what, thinker function) are the
  only hand-written facts, from the C structs of Doom8088 that
  `offsets.inc` mirrors. No offset or address is typed in.

`schema.Constants` holds `offsets.inc`, `memmap.inc` and `info.inc`
parsed (`c['NAME']` looks in the three) and `c.local(unit, name)` for a
source file's `.equ`. `BYTE_KINDS` are the kinds whose references carry a
byte offset rather than a field name (`lump`, `blockmap`, `reject`,
`symbol`, `table`).

`upstream.Schema()` builds both once: `Schema().c` (the constants) and
`Schema().structs` (the structures by name).

## Layout leaves (`layout.py`)

A leaf is one value of an object laid out natively: its `path` and its
encoding `enc`. `Leaf.width` is the number of byte planes the encoding
needs:

| Encoding | Planes |
| --- | --- |
| `int` | `{"bytes": n, "signed": b}`: n, little-endian |
| `ref` | tag, id low, id high (and offset low, offset high when `"offset"`); tag 0 is null, tag i the leaf's `codes[i - 1]` |
| `enum` | one, the index |
| `raw` | `{"bytes": n}`: n |
| `list` | the head of a list: a ref (3), or a handle when it carries `"ranges"` (`"bytes"`, default 2) |
| `seq` | start low, start high, length low, length high into a pool |
| `table` | the base of an object table: none |
| `blob` | length low, length high, then one address |
| `handle` | `{"bytes": 1 or 2, "ranges": [...]}`: one value of `bytes` planes |
| `sxbyte` | one, a signed byte |
| `bit` | one, the base of a bitmap |

`tools/native/llayout.py` lays out upstream's player and buttons natively
with these (`native_struct`).
