# src/native/m11/fxconv.mk: part fxconv (docs/SCREENS.md;
# tools/sound/README.md "Effects (S4)"): the effect scripts, host only.
#
#   build/native/m11/fxconv/SFX.1      the bank file of bank 103 (SFX):
#                                      directory, VATT, the 52 scripts,
#                                      the ten of fxtune.txt tuned
#   build/native/m11/fxconv/SFX.lst    the listing
#
#   make -f src/native/m11/fxconv.mk               SFX.1 and the listing
#   make -f src/native/m11/fxconv.mk fxconv-clean  removes what it made
#
# src/native/m11.mk includes this file; its variables and targets all
# start with FXCONV_ or fxconv, and it leaves the including makefile's
# default goal alone. ROOT and FXCONV_OUT can be set.

FXCONV_HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
FXCONV_SAVED_GOAL := $(.DEFAULT_GOAL)
ROOT ?= $(abspath $(FXCONV_HERE)../../..)
FXCONV_OUT ?= $(ROOT)/build/native/m11/fxconv
FXCONV_PYTHON ?= python3
FXCONV_WAD := $(ROOT)/build/upstream/data/DOOM1.WAD
FXCONV_TOOLS := $(ROOT)/tools/sound/fxconv.py $(ROOT)/tools/sound/mus.py \
                $(ROOT)/tools/sound/tables.py $(ROOT)/tools/sound/fxtune.txt

.PHONY: fxconv fxconv-clean

# (read by src/native/m11.mk: the part's name, and SFX.1 in its `all`)
PARTS += fxconv
M11_HOST += $(FXCONV_OUT)/SFX.1

fxconv: $(FXCONV_OUT)/SFX.1

$(FXCONV_OUT)/SFX.1: $(FXCONV_TOOLS) $(FXCONV_WAD)
	$(FXCONV_PYTHON) $(ROOT)/tools/sound/fxconv.py --out $(FXCONV_OUT)

fxconv-clean:
	rm -f $(FXCONV_OUT)/SFX.1 $(FXCONV_OUT)/SFX.lst

ifeq ($(words $(MAKEFILE_LIST)),1)
.DEFAULT_GOAL := fxconv
else
.DEFAULT_GOAL := $(FXCONV_SAVED_GOAL)
endif
