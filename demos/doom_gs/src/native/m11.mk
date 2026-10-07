# src/native/m11.mk: the 2D images and host files for the game disk
# (docs/SCREENS.md), assembled with ca65 and linked with ld65
# (cc65 2.18). The shared rules here, then each part's fragment
# src/native/m11/<part>.mk: a fragment builds into build/native/m11/<part>/
# and defines the target <part>_all (or a target named the part).
#
#   make -f m11.mk               every image and host file the disk reads
#                                (M11_HOST: fxconv's SFX.1, s2data's GFX.1,
#                                s2hud's HUDTXT.1)
#   make -f m11.mk part P=NAME   one part: only m11/NAME.mk is read
#   make -f m11.mk images        every fragment's images (with plboot's
#                                DOOM.SYSTEM link)
#   make -f m11.mk sizes         every image's size table (docs/SCREENS.md) against its
#                                room; an image over its room fails
#   make -f m11.mk check         tools/native/s2layout.py's check()
#   make -f m11.mk gen           the shared includes only
#   make -f m11.mk clean-part P=NAME   removes build/native/m11/NAME only
#
# Shared, in build/native/m11/shared/gen (written only when they change,
# atomically: several parts' makes may run at once):
#   s2.inc          s2layout.py's places for the 2D images
#   s2-release.inc  the same for the release (plboot's)
#   rlayout.inc     tools/native/rlayout.py's
#
# Each image is linked with the map s2layout.py --cfg IMAGE writes (its
# room is a MEMORY area, so ld65 fails an overflow), then s2layout.py
# --check-map writes its size table (<image>.sizes) and fails when its
# stored bytes pass its room.
#
# ROOT, M11 and TABLES can be set.

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT ?= $(abspath $(HERE)../..)
M11 ?= $(ROOT)/build/native/m11
SHARED := $(M11)/shared
GEN := $(SHARED)/gen
TABLES ?= $(ROOT)/build/native/render/tables
TOOLS := $(ROOT)/tools/native
S2LAYOUT ?= $(TOOLS)/s2layout.py

CA65 = ca65
LD65 = ld65
PYTHON = python3
ASFLAGS = --cpu 65C02 -g -I $(HERE) -I $(ROOT)/src/native -I $(GEN) \
          --bin-include-dir $(TABLES) \
          --bin-include-dir $(TABLES)/math

vpath %.s $(HERE) $(ROOT)/src/native
vpath %.inc $(HERE) $(ROOT)/src/native

LAYOUTS := $(S2LAYOUT) $(TOOLS)/rlayout.py $(TOOLS)/llayout.py \
           $(TOOLS)/layout.py $(wildcard $(TOOLS)/glayout.py)
M11_INCS := $(GEN)/rlayout.inc $(GEN)/s2.inc $(ROOT)/src/native/math.inc
# the objects every 2D image links: the far layer and the phase loader,
# the math (MATHW, AUXW at W $6000 as the render images)
M11_COMMON_OBJS := far.o math-r.o auxlc.o

IMAGES :=
MAPS :=
PARTS :=
# a fragment's host-only files that `all` makes too (fxconv's SFX.1,
# s2data's store, s2hud's HUDTXT.1)
M11_HOST :=

.PHONY: all part images sizes check gen clean-part

all: images

# ---------------------------------------------------------------------------
# The shared includes
# ---------------------------------------------------------------------------

gen: $(GEN)/s2.inc $(GEN)/s2-release.inc $(GEN)/rlayout.inc

$(GEN)/s2.inc: $(LAYOUTS)
	$(PYTHON) $(S2LAYOUT) --inc --build test $@

$(GEN)/s2-%.inc: $(LAYOUTS)
	$(PYTHON) $(S2LAYOUT) --inc --build $* $@

$(GEN)/rlayout.inc: $(TOOLS)/rlayout.py $(TOOLS)/layout.py $(S2LAYOUT)
	$(PYTHON) $(S2LAYOUT) --rlayout-inc $@

$(TABLES)/math/squares.bin:
	@echo "no tables in $(TABLES): run python3 tools/native/rtables.py" >&2
	@exit 1

check:
	$(PYTHON) $(S2LAYOUT) --check

# ---------------------------------------------------------------------------
# Rules a fragment instantiates
# ---------------------------------------------------------------------------

# M11_COMMON DIR: the common objects into DIR, and DIR/%.o from any source
define M11_COMMON
$(1)/far.o: far.s $$(M11_INCS)
	@mkdir -p $(1)
	$$(CA65) $$(ASFLAGS) -o $$@ -l $$(@:.o=.lst) $$<
$(1)/math-r.o: math.s $$(ROOT)/src/native/math.inc $$(TABLES)/math/squares.bin
	@mkdir -p $(1)
	$$(CA65) $$(ASFLAGS) -D RENDER -o $$@ -l $$(@:.o=.lst) $$<
$(1)/%.o: %.s $$(M11_INCS)
	@mkdir -p $(1)
	$$(CA65) $$(ASFLAGS) -o $$@ -l $$(@:.o=.lst) $$<
endef

# M11_IMAGE DIR,NAME,IMAGE,OBJECTS: DIR/NAME.* linked in the room of
# s2layout's IMAGE (P2DW, MENUW, AMAPW, WIW, FINW, PALW, OVLW); the target
# is its map, then its size table DIR/NAME.sizes (the build fails when the
# image passes its room)
define M11_IMAGE
$(1)/$(2).cfg: $$(LAYOUTS)
	@mkdir -p $(1)
	$$(PYTHON) $$(S2LAYOUT) --cfg $(3) $$@
$(1)/$(2).map: $(4) $(1)/$(2).cfg
	$$(LD65) -C $(1)/$(2).cfg -o $(1)/$(2) -Ln $(1)/$(2).lbl \
	    -m $(1)/$(2).map $(4)
	$$(PYTHON) $$(S2LAYOUT) --check-map $(3) $(1)/$(2).map > $(1)/$(2).sizes \
	    || { cat $(1)/$(2).sizes; rm -f $(1)/$(2).map; exit 1; }
IMAGES += $(1)/$(2).map
MAPS += $(3):$(1)/$(2).map
endef

# ---------------------------------------------------------------------------
# The fragments
# ---------------------------------------------------------------------------

ifdef P
include $(HERE)m11/$(P).mk
part: $(P)_all
clean-part:
	rm -rf $(M11)/$(P)
else
include $(sort $(wildcard $(HERE)m11/*.mk))
part:
	@echo "give the part: make -f m11.mk part P=NAME (parts: $(PARTS))" >&2
	@exit 1
clean-part: part
endif

# a fragment whose main target is the part's own name (fxconv's) builds
# by it
%_all: %
	@:

all: $(M11_HOST)

images: $(IMAGES)

sizes: $(IMAGES)
	@for m in $(MAPS); do \
	    $(PYTHON) $(S2LAYOUT) --check-map $${m%%:*} $${m#*:} || exit 1; \
	done
