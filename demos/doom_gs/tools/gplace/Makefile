# tools/gplace: the C11 halves of the placement's model (docs/speed-parts/
# place.md): gtrace, the call traffic of the tic phase from a2vm's write
# log; gsim, the dry run of a placement on that traffic.
#
#   make        build/gplace/gtrace and build/gplace/gsim
#   make clean  removes build/gplace's binaries
#
# C11 and the standard library only; no warnings.

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT := $(abspath $(HERE)../..)
OUT := $(ROOT)/build/gplace

CC = cc
CFLAGS = -std=c11 -O2 -Wall -Wextra -pedantic

.PHONY: all clean

all: $(OUT)/gtrace $(OUT)/gsim

$(OUT):
	mkdir -p $@

$(OUT)/%: $(HERE)%.c | $(OUT)
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(OUT)/gtrace $(OUT)/gsim
