# src/native/math.mk: the native math (milestone 6), assembled with ca65
# and linked with ld65 (cc65 2.18) into build/native/math/obj:
#
#   mathtest.lc1, .far, .w, .lce   the math and its a2vm test driver
#                                  (math.cfg), for tools/native/mathrun.py
#   mathtest.lbl, .map, *.lst      symbols (VICE labels), map, listings
#
# The tables it includes (rndtable.bin, cosexc.bin) and loads are Doom's
# and upstream's data: tools/native/mathtables.py writes them into
# build/native/math/tables from a capture of the reference (mathcap.py).
#
#   make -f math.mk            the build (the tables must exist: `tables`)
#   make -f math.mk tables     capture newgame on ref816, write the tables
#   make -f math.mk sizes      the bytes of each area
#   make -f math.mk check      the sample checks (tests/test_native_math*)
#   make -f math.mk check-full every routine on 1 million random inputs,
#                              every captured input and all table entries,
#                              against upstream on ref816 (or, for the
#                              divides, against C semantics), and the
#                              costs; writes build/native/math/report.json
#   make -f math.mk clean      removes build/native/math/obj only

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT ?= $(abspath $(HERE)../..)
MATH ?= $(ROOT)/build/native/math
OUT ?= $(MATH)/obj
TABLES ?= $(MATH)/tables

CA65 = ca65
LD65 = ld65
PYTHON = python3
ASFLAGS = --cpu 65C02 -g -I $(HERE) --bin-include-dir $(TABLES)

.PHONY: all tables sizes check check-full clean

all: $(OUT)/mathtest.lc1

$(TABLES)/rndtable.bin $(TABLES)/cosexc.bin:
	@echo "no tables in $(TABLES): run make -f math.mk tables" >&2
	@exit 1

tables:
	nice -n 10 $(PYTHON) $(ROOT)/tools/native/mathcap.py newgame
	$(PYTHON) $(ROOT)/tools/native/mathtables.py

$(OUT)/math.o: $(HERE)math.s $(HERE)mathgame.inc $(HERE)math.inc \
               $(TABLES)/rndtable.bin \
               $(TABLES)/cosexc.bin
	@mkdir -p $(OUT)
	$(CA65) $(ASFLAGS) -o $@ -l $(OUT)/math.lst $<

$(OUT)/mathdrv.o: $(HERE)mathdrv.s $(HERE)math.inc
	@mkdir -p $(OUT)
	$(CA65) $(ASFLAGS) -o $@ -l $(OUT)/mathdrv.lst $<

$(OUT)/mathtest.lc1: $(OUT)/math.o $(OUT)/mathdrv.o $(HERE)math.cfg
	$(LD65) -C $(HERE)math.cfg -o $(OUT)/mathtest -Ln $(OUT)/mathtest.lbl \
	    -m $(OUT)/mathtest.map $(OUT)/math.o $(OUT)/mathdrv.o

sizes: all
	$(PYTHON) $(ROOT)/tools/native/mathrun.py --sizes

check: all
	$(PYTHON) -m unittest discover -s $(ROOT)/tests -p 'test_native_math*.py'

check-full: all
	nice -n 10 $(PYTHON) $(ROOT)/tools/native/mathcheck.py --full \
	    --call-cases 8

clean:
	rm -rf $(OUT)
