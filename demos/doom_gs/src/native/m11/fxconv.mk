# src/native/m11/fxconv.mk: part fxconv of milestone 11 (docs/SCREENS.md
# 7.3; tools/sound/README.md "Effects (S4)"): the effect scripts, host
# only.
#
#   build/native/m11/fxconv/SFX.1      the bank file of bank 103 (SFX):
#                                      directory, VATT, the 52 scripts,
#                                      the ten of fxtune.txt tuned
#   build/native/m11/fxconv/SFXAUTO.1  the same, every script automatic
#                                      (for the test disk's T key)
#   build/native/m11/fxconv/SFX.lst    the listing
#   build/sound/fx/NAME.ay, NAME.wav   fxmodel.py's AY log of each script
#                                      and its render by ayrender.py
#                                      (NAME.tuned.* for the ten)
#
#   make -f src/native/m11/fxconv.mk               SFX.1 and the listing
#   make -f src/native/m11/fxconv.mk fxconv-renders   the WAV renders
#   make -f src/native/m11/fxconv.mk fxconv-clean  removes what it made
#
# src/native/m11.mk (part s2lay) may include this file; its variables
# and targets all start with FXCONV_ or fxconv, and it leaves the
# including makefile's default goal alone. ROOT can be set, so a copy of
# the tools builds elsewhere (FXCONV_OUT and FXCONV_FX with it).

FXCONV_HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
FXCONV_SAVED_GOAL := $(.DEFAULT_GOAL)
ROOT ?= $(abspath $(FXCONV_HERE)../../..)
FXCONV_OUT ?= $(ROOT)/build/native/m11/fxconv
FXCONV_FX ?= $(ROOT)/build/sound/fx
FXCONV_PYTHON ?= python3
FXCONV_WAD := $(ROOT)/build/upstream/data/DOOM1.WAD
FXCONV_TOOLS := $(ROOT)/tools/sound/fxconv.py $(ROOT)/tools/sound/mus.py \
                $(ROOT)/tools/sound/tables.py $(ROOT)/tools/sound/fxtune.txt
FXCONV_MODEL := $(ROOT)/tools/sound/fxmodel.py \
                $(ROOT)/tools/sound/ayrender.py \
                $(ROOT)/tools/sound/tables.py $(ROOT)/tools/sound/fxtune.txt

.PHONY: fxconv fxconv-renders fxconv-clean

# (read by src/native/m11.mk: the part's name, and SFX.1 in its `all`)
PARTS += fxconv
M11_HOST += fxconv

fxconv: $(FXCONV_OUT)/SFX.1

$(FXCONV_OUT)/SFX.1: $(FXCONV_TOOLS) $(FXCONV_WAD)
	$(FXCONV_PYTHON) $(ROOT)/tools/sound/fxconv.py --out $(FXCONV_OUT)

$(FXCONV_OUT)/renders.stamp: $(FXCONV_MODEL) $(FXCONV_WAD)
	@mkdir -p $(FXCONV_OUT)
	$(FXCONV_PYTHON) $(ROOT)/tools/sound/fxmodel.py --render $(FXCONV_FX) \
	    --manifest $(FXCONV_OUT)/renders.list > $(FXCONV_OUT)/renders.txt
	@touch $@

fxconv-renders: $(FXCONV_OUT)/renders.stamp

# the renders are removed by name, from the list fxmodel.py wrote
# (build/sound is shared with S1 and the other effect parts)
fxconv-clean:
	if [ -f $(FXCONV_OUT)/renders.list ]; then \
	    xargs rm -f < $(FXCONV_OUT)/renders.list; fi
	rm -f $(FXCONV_OUT)/SFX.1 $(FXCONV_OUT)/SFXAUTO.1 $(FXCONV_OUT)/SFX.lst \
	    $(FXCONV_OUT)/renders.txt $(FXCONV_OUT)/renders.list \
	    $(FXCONV_OUT)/renders.stamp

ifeq ($(words $(MAKEFILE_LIST)),1)
.DEFAULT_GOAL := fxconv
else
.DEFAULT_GOAL := $(FXCONV_SAVED_GOAL)
endif
