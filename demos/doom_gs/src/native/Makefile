# src/native: the native 65C02 record replay (milestone 5), assembled with
# ca65 and linked with ld65 (cc65 2.18) into build/native/obj:
#
#   gen/layout.inc, gen/rows.s   from tools/native/rowgen.py (the row
#   gen/restore.inc              blocks, fill blocks and tables; the card
#                                runner's PRIVATE copies)
#   test.lc, test.main0800, test.aux0200, test.aux0800
#                                the replay with its a2vm test driver
#                                (replay.cfg), for tools/native/loader.py
#   card.boot, card.lc          REPLAY.SYSTEM for the card (runner.cfg):
#                                tools/native/disk.py builds the disk
#   *.lbl, *.map, *.lst          symbols (VICE labels), maps, listings
#
#   make            both builds
#   make sizes      the bytes used and left in each area of the map
#   make clean      removes build/native/obj only
#
# ROOT (this directory's ../..) and OUT can be set, so a copy of these
# sources builds elsewhere (tests/test_native_replay.py plants bugs in one).
#
# The tests (tests/test_native_replay.py) and tools/native/replay_check.py
# run the build on a2vm.

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT ?= $(abspath $(HERE)../..)
OUT ?= $(ROOT)/build/native/obj
GEN := $(OUT)/gen

CA65 = ca65
LD65 = ld65
PYTHON = python3
ASFLAGS = --cpu 65C02 -g -I $(HERE) -I $(GEN)

GENERATED := $(GEN)/layout.inc $(GEN)/rows.s $(GEN)/restore.inc
TOOLS := $(ROOT)/tools/native/rowgen.py $(ROOT)/tools/native/layout.py

.PHONY: all sizes clean

all: $(OUT)/test.lc $(OUT)/prof.lc $(OUT)/card.lc

$(GENERATED): $(TOOLS)
	@mkdir -p $(GEN)
	$(PYTHON) $(ROOT)/tools/native/rowgen.py $(GEN)

$(OUT)/replay.o: $(HERE)replay.s $(GENERATED)
	$(CA65) $(ASFLAGS) -o $@ -l $(OUT)/replay.lst $<

$(OUT)/driver.o: $(HERE)driver.s $(GEN)/layout.inc
	$(CA65) $(ASFLAGS) -o $@ -l $(OUT)/driver.lst $<

$(OUT)/runner.o: $(HERE)runner.s $(GEN)/layout.inc $(GEN)/restore.inc
	$(CA65) $(ASFLAGS) -o $@ -l $(OUT)/runner.lst $<

$(OUT)/test.lc: $(OUT)/replay.o $(OUT)/driver.o $(HERE)replay.cfg
	$(LD65) -C $(HERE)replay.cfg -o $(OUT)/test -Ln $(OUT)/test.lbl \
	    -m $(OUT)/test.map $(OUT)/replay.o $(OUT)/driver.o

# the profiling build: the replay marks its parts as cost phases
$(OUT)/replay-prof.o: $(HERE)replay.s $(GENERATED)
	$(CA65) $(ASFLAGS) -D PROFILE -o $@ -l $(OUT)/replay-prof.lst $<

$(OUT)/prof.lc: $(OUT)/replay-prof.o $(OUT)/driver.o $(HERE)replay.cfg
	$(LD65) -C $(HERE)replay.cfg -o $(OUT)/prof -Ln $(OUT)/prof.lbl \
	    -m $(OUT)/prof.map $(OUT)/replay-prof.o $(OUT)/driver.o

$(OUT)/card.lc: $(OUT)/replay.o $(OUT)/runner.o $(HERE)runner.cfg
	$(LD65) -C $(HERE)runner.cfg -o $(OUT)/card -Ln $(OUT)/card.lbl \
	    -m $(OUT)/card.map $(OUT)/replay.o $(OUT)/runner.o

sizes: all
	$(PYTHON) $(ROOT)/tools/native/sizes.py $(OUT)/test.map $(OUT)/card.map

clean:
	rm -rf $(OUT)
