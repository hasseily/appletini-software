# ref816: the 65816 core of the reference machine, its vector harness, and
# the minimal IIgs that runs upstream's DOOM on it.
#
#   make               build build/ref816/ref816 (the machine),
#                      build/ref816/vectors, build/ref816/selftest and
#                      build/ref816/machinetest
#   make selftest      run the core tests the vectors do not cover
#                      (interrupts, WAI, STP, reset)
#   make machinetest   run the tests of the machine (memory map, DOC,
#                      ADB, firmware traps)
#   make vectors       run every SingleStepTests case (after
#                      python3 tools/ref816/fetch_vectors.py)
#   make sample        run the first 20 cases of each vector file
#   make clean
#
# Everything built goes to build/ref816, outside the source tree.

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT := $(abspath $(HERE)../..)
OUT := $(ROOT)/build/ref816
VECTOR_FILES = $(wildcard $(ROOT)/build/vectors/bin/*.bin)

CC = cc
CFLAGS = -std=c11 -O2 -Wall -Wextra -pedantic

HEADERS := $(wildcard $(HERE)*.h)
MACHINE_OBJECTS := $(OUT)/iigs.o $(OUT)/doc.o $(OUT)/adb.o $(OUT)/cpu816.o

MACHINE := $(OUT)/ref816
HARNESS := $(OUT)/vectors
SELFTEST := $(OUT)/selftest
MACHINETEST := $(OUT)/machinetest

.PHONY: all selftest machinetest vectors sample clean check-vectors

all: $(MACHINE) $(HARNESS) $(SELFTEST) $(MACHINETEST)

$(OUT)/%.o: $(HERE)%.c $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -c -o $@ $<

$(MACHINE): $(OUT)/main.o $(OUT)/program.o $(OUT)/trace.o \
            $(OUT)/footprint.o $(MACHINE_OBJECTS)
	$(CC) $(CFLAGS) -o $@ $^

$(HARNESS): $(OUT)/vectors.o $(OUT)/cpu816.o
	$(CC) $(CFLAGS) -o $@ $^

$(SELFTEST): $(OUT)/selftest.o $(OUT)/cpu816.o
	$(CC) $(CFLAGS) -o $@ $^

$(MACHINETEST): $(OUT)/machinetest.o $(MACHINE_OBJECTS)
	$(CC) $(CFLAGS) -o $@ $^

$(OUT):
	mkdir -p $@

check-vectors:
	@test -n "$(VECTOR_FILES)" || { echo "no vectors in build/vectors/bin:" \
	    "run python3 tools/ref816/fetch_vectors.py first"; exit 1; }

selftest: $(SELFTEST)
	$(SELFTEST)

machinetest: $(MACHINETEST)
	$(MACHINETEST)

vectors: $(HARNESS) check-vectors
	$(HARNESS) $(VECTOR_FILES)

sample: $(HARNESS) check-vectors
	$(HARNESS) --limit 20 $(VECTOR_FILES)

clean:
	rm -rf $(OUT)
