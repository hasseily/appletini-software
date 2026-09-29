# src/vm: the 65816 interpreter, assembled with ca65 and linked with ld65
# (cc65 2.18) into build/vm:
#
#   vm.bin.d000   the opcode handlers, for language card bank 1 at $D000
#   vm.bin.e000   the core, for the main language card at $E000
#   vm.bin.f000   the far layer, at $F000
#   vm.lbl        every symbol (VICE labels, ld65 -Ln); vm.map, vm.lst
#
#   make            build
#   make sizes      the size of each part against its budget
#   make sample     the first 20 cases of each SingleStepTests 65816 file
#                   through the interpreter on a2vm (tools/a2vm/vm816.c)
#   make vectors    all 5,120,000 cases, with the time taken
#   make selftest   the self test (traps, vm_run) and the lockstep with
#                   tools/ref816's 65816 core on random programs
#   make contact    the first contact with the game: upstream's release in
#                   lockstep with tools/ref816 up to its first I/O access
#   make clean
#
# The vector targets need the vectors of tools/ref816/fetch_vectors.py.

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT := $(abspath $(HERE)../..)
OUT := $(ROOT)/build/vm

CA65 = ca65
LD65 = ld65

SOURCES := $(wildcard $(HERE)*.s)

.PHONY: all sizes sample vectors selftest contact clean

all: $(OUT)/vm.bin.e000

$(OUT)/vm.o: $(SOURCES) | $(OUT)
	$(CA65) --cpu 65C02 -g -I $(HERE) -o $@ -l $(OUT)/vm.lst $(HERE)vm.s

$(OUT)/vm.bin.e000: $(OUT)/vm.o $(HERE)vm.cfg
	$(LD65) -C $(HERE)vm.cfg -o $(OUT)/vm.bin -Ln $(OUT)/vm.lbl \
	    -m $(OUT)/vm.map $(OUT)/vm.o

$(OUT):
	mkdir -p $@

sizes: all
	@wc -c $(OUT)/vm.bin.e000 $(OUT)/vm.bin.f000 $(OUT)/vm.bin.d000 | \
	    awk '{ if ($$2 ~ /e000/) b = 4096; else if ($$2 ~ /f000/) b = 1228; \
	    else if ($$2 ~ /d000/) b = 4096; else b = 9420; \
	    printf "%-40s %5d bytes of %5d\n", $$2, $$1, b }'

sample: all
	$(MAKE) -C $(ROOT)/tools/a2vm vmsample VM=$(OUT)

vectors: all
	$(MAKE) -C $(ROOT)/tools/a2vm vmvectors VM=$(OUT)

selftest: all
	$(MAKE) -C $(ROOT)/tools/a2vm vmselftest VM=$(OUT)

contact: all
	$(MAKE) -C $(ROOT)/tools/a2vm contact VM=$(OUT)

clean:
	rm -rf $(OUT)
