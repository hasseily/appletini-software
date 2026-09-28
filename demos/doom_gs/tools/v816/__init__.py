"""Host-side tools for the V816 port of Apple IIgs DOOM to the 65C02.

Modules:
  prodos    read-only access to a ProDOS volume image
  b1        decoder for upstream's B1 compression
  hdv       the release disk image: header, segment table, loaded segments
  memimage  sparse 24-bit memory image built from loaded segments

The front end, from upstream's sources to the intermediate representation:
  cpp       C-style preprocessor
  lexer     tokens of a line of Calypsi assembly
  expr      expressions: syntax tree, parser, evaluation
  macro     .macro definitions and their expansion
  mnemonics the instruction names of the 65816
  parse     preprocessed lines to the IR
  ir        the data classes of the IR, and their JSON dump
  stats     counts over the sources and over the IR
  report    the Markdown report docs/FRONTEND_STATS.md
  frontend  driver: all sources of upstream's default build
  cppcheck  cross-check of cpp against clang -E

The back end, from the IR to an image that equals the release:
  opcodes   the opcode table of the 65816
  linear    values that are known up to the placement of the program
  asm816    the instruction encoder: bytes with holes
  objfile   the assembler of a unit: fragments, labels, symbols
  scm       reader of the linker rules files (iigs.scm)
  release   the release image as the three programs that are linked
  link      names across units, the bytes of holes, the built image
  place     layout recovery: where the release has each fragment
  sections  section extents and the linker's data_init_table
  linkmap   addresses of fragments and values of symbols, for JSON
  imgmatch  driver: build, compare with the release, write the report
"""
