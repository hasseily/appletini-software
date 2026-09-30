# tools/native: the host tools of the native rewrite written in C.
#
#   make        build/native/math/mathref: upstream's math routines on
#               ref816's machine (mathref.c), built from the unmodified
#               sources of tools/ref816 into build/native/math/refobj
#   make clean  removes build/native/math/refobj and mathref only
#
# C11 and the standard library only; no warnings.

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT := $(abspath $(HERE)../..)
REF := $(ROOT)/tools/ref816
OUT := $(ROOT)/build/native/math
OBJ := $(OUT)/refobj

CC = cc
CFLAGS = -std=c11 -O2 -Wall -Wextra -pedantic

REF_OBJECTS := $(OBJ)/iigs.o $(OBJ)/doc.o $(OBJ)/adb.o $(OBJ)/cpu816.o \
               $(OBJ)/program.o
REF_HEADERS := $(wildcard $(REF)/*.h)

.PHONY: all clean

all: $(OUT)/mathref

$(OBJ):
	mkdir -p $@

$(OBJ)/%.o: $(REF)/%.c $(REF_HEADERS) | $(OBJ)
	$(CC) $(CFLAGS) -I$(REF) -c -o $@ $<

$(OBJ)/mathref.o: $(HERE)mathref.c $(REF_HEADERS) | $(OBJ)
	$(CC) $(CFLAGS) -I$(REF) -c -o $@ $<

$(OUT)/mathref: $(OBJ)/mathref.o $(REF_OBJECTS)
	$(CC) $(CFLAGS) -o $@ $^

clean:
	rm -rf $(OBJ) $(OUT)/mathref
