# SPDX-License-Identifier: GPL-2.0-only
# Compile the shared machine directly from the maintained a2vm sources.
HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
A2VM := $(abspath $(HERE)/../../demos/doom_gs/tools/a2vm)
OUT := build
CC ?= cc
CFLAGS ?= -O2 -std=c11 -Wall -Wextra -pedantic
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
LIB := $(OUT)/libappletini.dylib
SHARED := -dynamiclib
else
LIB := $(OUT)/libappletini.so
SHARED := -shared
endif
SOURCES := native.c cards.c audio.c speech_state.c $(A2VM)/a2vm.c $(A2VM)/cost.c $(A2VM)/prodos.c $(A2VM)/cpu65c02.c
HEADERS := native.h cards.h audio.h speech_state.h $(wildcard $(A2VM)/*.h)

.PHONY: all clean
all: $(LIB)

$(LIB): $(SOURCES) $(HEADERS) Makefile | $(OUT)
	@tmp=$$(mktemp "$(OUT)/.libappletini.XXXXXX"); \
	trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	$(CC) $(CPPFLAGS) $(CFLAGS) -fPIC $(SHARED) -I"$(A2VM)" $(SOURCES) $(LDFLAGS) -lm -o "$$tmp" && \
	mv -f "$$tmp" "$@"

$(OUT):
	mkdir -p "$@"

clean:
	rm -rf "$(OUT)"
