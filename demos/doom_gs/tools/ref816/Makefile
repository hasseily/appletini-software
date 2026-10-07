# ref816: the reference machine, a 65816 core and the minimal IIgs that
# runs upstream's DOOM on it (the captures the build takes its tables from:
# tools/native/rendercap.py).
#
#   make               build build/ref816/ref816
#   make clean
#
# Everything built goes to build/ref816, outside the source tree.

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT := $(abspath $(HERE)../..)
OUT := $(ROOT)/build/ref816

CC = cc
CFLAGS = -std=c11 -O2 -Wall -Wextra -pedantic

HEADERS := $(wildcard $(HERE)*.h)
MACHINE_OBJECTS := $(OUT)/iigs.o $(OUT)/doc.o $(OUT)/adb.o $(OUT)/cpu816.o

MACHINE := $(OUT)/ref816

.PHONY: all clean

all: $(MACHINE)

$(OUT)/%.o: $(HERE)%.c $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -c -o $@ $<

$(MACHINE): $(OUT)/main.o $(OUT)/program.o $(OUT)/trace.o \
            $(OUT)/footprint.o $(OUT)/points.o $(OUT)/calllog.o \
            $(OUT)/inject.o $(MACHINE_OBJECTS)
	$(CC) $(CFLAGS) -o $@ $^

$(OUT):
	mkdir -p $@

clean:
	rm -rf $(OUT)
