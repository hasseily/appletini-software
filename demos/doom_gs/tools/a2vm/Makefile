# a2vm: the model of the Appletini target: its W65C02S core, the vector
# harness, the tests of what the vectors do not cover, a speed
# measurement, and the machine (a2vm) with its compatibility core.
#
#   make               build build/a2vm/a2vm (the machine),
#                      build/a2vm/py65check (the compatibility core on a
#                      flat memory, for py65_diff.py), build/a2vm/vectors,
#                      build/a2vm/selftest, build/a2vm/bench and
#                      build/a2vm/vm816 (the interpreter's vector harness)
#   make selftest      run the core tests the vectors do not cover
#                      (IRQ, NMI, WAI, STP, reset, BRK, cycle kinds)
#   make viatest       the tests of --via-timers, the Phasor VIAs' timer 1
#                      and its interrupt (viatest.py)
#   make vectors       run every SingleStepTests case (after
#                      python3 tools/a2vm/fetch_vectors.py)
#   make sample        run the first 20 cases of each vector file
#   make bench         measure instructions per second
#   make vmsample      the first 20 cases of each SingleStepTests 65816
#                      file through the 65816 interpreter of src/vm, on
#                      a2vm (vm816.c; builds src/vm first)
#   make vmvectors     all 5,120,000 of them, with the time taken
#   make vmselftest    the interpreter's self test (traps, vm_run) and
#                      its lockstep with tools/ref816's core on random
#                      programs, on 2 and on 124 RamWorks banks
#   make contact       the first contact of the interpreter with the game:
#                      the release image in lockstep with ref816 up to its
#                      first I/O access (game816; needs build/ref816/
#                      memory.img, from tools/ref816/make_image.py)
#   make interpreter   measure the interpreter's cost and write
#                      docs/INTERPRETER.md (interpreter_report.py --run)
#   make compare       run the existing Doom port on a2vm and on a2sim.py
#                      for 20 frames and compare them at every frame, also
#                      with the memory API and the cost model on (needs
#                      build/venv with py65 and Pillow, README.md)
#   make costreport    the cost model's report on the existing port
#                      (tools/a2vm/cost_report.py)
#   make clean
#
# Everything built goes to build/a2vm, outside the source tree.

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT := $(abspath $(HERE)../..)
OUT := $(ROOT)/build/a2vm
VECTOR_DIR := $(ROOT)/build/vectors/wdc65c02
VECTOR_FILES = $(wildcard $(VECTOR_DIR)/*.bin)
VECTORS816 = $(wildcard $(ROOT)/build/vectors/bin/*.bin)
VM := $(ROOT)/build/vm

CC = cc
CFLAGS = -std=c11 -O2 -Wall -Wextra -pedantic

HEADERS := $(wildcard $(HERE)*.h)
REF816 := $(abspath $(HERE)../ref816)/

HARNESS := $(OUT)/vectors
SELFTEST := $(OUT)/selftest
BENCH := $(OUT)/bench
MACHINE := $(OUT)/a2vm
PY65CHECK := $(OUT)/py65check
VM816 := $(OUT)/vm816
GAME816 := $(OUT)/game816

.PHONY: all selftest viatest vectors sample bench compare costreport clean \
	check-vectors check-vectors816 vm vmsample vmvectors vmselftest \
	contact interpreter

all: $(MACHINE) $(PY65CHECK) $(HARNESS) $(SELFTEST) $(BENCH) $(VM816) \
	$(GAME816)

$(OUT)/%.o: $(HERE)%.c $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -c -o $@ $<

$(HARNESS): $(OUT)/vectors.o $(OUT)/cpu65c02.o
	$(CC) $(CFLAGS) -o $@ $^

$(SELFTEST): $(OUT)/selftest.o $(OUT)/cpu65c02.o
	$(CC) $(CFLAGS) -o $@ $^

$(BENCH): $(OUT)/bench.o $(OUT)/cpu65c02.o
	$(CC) $(CFLAGS) -o $@ $^

$(MACHINE): $(OUT)/main.o $(OUT)/a2vm.o $(OUT)/cost.o $(OUT)/prodos.o \
	    $(OUT)/cpu65c02.o
	$(CC) $(CFLAGS) -o $@ $^

$(PY65CHECK): $(OUT)/py65check.o
	$(CC) $(CFLAGS) -o $@ $^

$(VM816): $(OUT)/vm816.o $(OUT)/a2vm.o $(OUT)/cost.o $(OUT)/prodos.o \
	    $(OUT)/cpu65c02.o $(OUT)/cpu816.o
	$(CC) $(CFLAGS) -o $@ $^

# The 65816 core of tools/ref816, the reference of vm816's lockstep, and
# its IIgs, the reference of game816.
$(OUT)/cpu816.o: $(REF816)cpu816.c $(REF816)cpu816.h | $(OUT)
	$(CC) $(CFLAGS) -c -o $@ $<

REF816_HEADERS := $(wildcard $(REF816)*.h)

$(OUT)/ref816-%.o: $(REF816)%.c $(REF816_HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -c -o $@ $<

$(GAME816): $(OUT)/game816.o $(OUT)/a2vm.o $(OUT)/cost.o $(OUT)/prodos.o \
	    $(OUT)/cpu65c02.o $(OUT)/cpu816.o $(OUT)/ref816-iigs.o \
	    $(OUT)/ref816-doc.o $(OUT)/ref816-adb.o
	$(CC) $(CFLAGS) -o $@ $^

$(OUT)/game816.o: $(HERE)game816.c $(HEADERS) $(REF816_HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -I$(REF816) -c -o $@ $<

$(OUT)/vm816.o: $(HERE)vm816.c $(HEADERS) $(REF816)cpu816.h | $(OUT)
	$(CC) $(CFLAGS) -I$(REF816) -c -o $@ $<

$(OUT):
	mkdir -p $@

check-vectors:
	@test -n "$(VECTOR_FILES)" || { echo "no vectors in $(VECTOR_DIR):" \
	    "run python3 tools/a2vm/fetch_vectors.py first"; exit 1; }

selftest: $(SELFTEST)
	$(SELFTEST)

viatest: $(MACHINE)
	python3 $(HERE)viatest.py --a2vm $(MACHINE)

vectors: $(HARNESS) check-vectors
	$(HARNESS) $(VECTOR_FILES)

sample: $(HARNESS) check-vectors
	$(HARNESS) --limit 20 $(VECTOR_FILES)

bench: $(BENCH)
	$(BENCH)

check-vectors816:
	@test -n "$(VECTORS816)" || { echo "no vectors in build/vectors/bin:" \
	    "run python3 tools/ref816/fetch_vectors.py first"; exit 1; }

vm:
	$(MAKE) -C $(ROOT)/src/vm OUT=$(VM)

vmsample: $(VM816) vm check-vectors816
	$(VM816) --vm $(VM) --limit 20 $(VECTORS816)

vmvectors: $(VM816) vm check-vectors816
	$(VM816) --vm $(VM) $(VECTORS816)

vmselftest: $(VM816) vm
	$(VM816) --vm $(VM) --selftest
	$(VM816) --vm $(VM) --lockstep 1 2000 5000 2
	$(VM816) --vm $(VM) --lockstep 2 2000 5000 124

MEMORY_IMG := $(ROOT)/build/ref816/memory.img

contact: $(GAME816) vm
	@test -f $(MEMORY_IMG) || { echo "no $(MEMORY_IMG): run python3" \
	    "tools/ref816/make_image.py first"; exit 1; }
	$(GAME816) --vm $(VM) contact $(MEMORY_IMG)

interpreter:
	python3 $(HERE)interpreter_report.py --run

VENV_PYTHON := $(ROOT)/build/venv/bin/python

compare: $(MACHINE)
	@test -x $(VENV_PYTHON) || { echo "no $(VENV_PYTHON): see" \
	    "tools/a2vm/README.md"; exit 1; }
	$(VENV_PYTHON) $(HERE)compare_a2sim.py --a2vm $(MACHINE) --frames 20
	$(VENV_PYTHON) $(HERE)compare_a2sim.py --a2vm $(MACHINE) --frames 1 \
	    --mode prodos --every 5000000
	$(VENV_PYTHON) $(HERE)compare_a2sim.py --a2vm $(MACHINE) --frames 20 \
	    --amem --cost f121

costreport: $(MACHINE)
	python3 $(HERE)cost_report.py --a2vm $(MACHINE)

clean:
	rm -rf $(OUT)
