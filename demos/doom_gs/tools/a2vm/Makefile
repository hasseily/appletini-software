# a2vm: the model of the Appletini target (its W65C02S core, the //e with
# RamWorks, the devices, the ProDOS MLI trap and the cost model), which
# tools/native/playdisk.py --run plays DOOM.hdv on.
#
#   make               build build/a2vm/a2vm
#   make clean
#
# Everything built goes to build/a2vm, outside the source tree.

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT := $(abspath $(HERE)../..)
OUT := $(ROOT)/build/a2vm

CC = cc
CFLAGS = -std=c11 -O2 -Wall -Wextra -pedantic

HEADERS := $(wildcard $(HERE)*.h)

MACHINE := $(OUT)/a2vm

.PHONY: all clean

all: $(MACHINE)

$(OUT)/%.o: $(HERE)%.c $(HEADERS) | $(OUT)
	$(CC) $(CFLAGS) -c -o $@ $<

$(MACHINE): $(OUT)/main.o $(OUT)/a2vm.o $(OUT)/cost.o $(OUT)/prodos.o \
	    $(OUT)/cpu65c02.o
	$(CC) $(CFLAGS) -o $@ $^

$(OUT):
	mkdir -p $@

clean:
	rm -rf $(OUT)
