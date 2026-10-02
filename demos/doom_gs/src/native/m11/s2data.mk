# src/native/m11/s2data.mk: part s2data of milestone 11 (docs/SCREENS.md
# 4.5, 7.3; docs/m11-parts/s2data.md): the 2D store, host only.
#
#   build/native/m11/s2data/GFX.1        the bank file(s) of the 2D store
#                                        (loader.s's format), with the
#                                        handles table at GFX0's $0200
#   build/native/m11/s2data/s2data.inc   the handles (H_*), each lump's
#                                        place (HBANK_*, HADDR_*), the
#                                        table's and the pictures' offsets
#   build/native/m11/s2data/s2data.json  the manifest: each lump's handle,
#                                        number, kind, source, place, hash
#   build/native/m11/s2data/s2data.lst   the bytes a bank against 4.5
#   build/native/m11/s2data/s2data.log   the last build's report and checks
#
#   make -f src/native/m11/s2data.mk               the store, checked
#   make -f src/native/m11/s2data.mk s2data-check  the files checked again
#   make -f src/native/m11/s2data.mk s2data-clean  removes what it made
#
# src/native/m11.mk (part s2lay) includes this file; its variables and
# targets all start with S2DATA_ or s2data, and it leaves the including
# makefile's default goal alone. ROOT can be set, so a copy of the tools
# builds elsewhere (S2DATA_OUT with it).

S2DATA_HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
S2DATA_SAVED_GOAL := $(.DEFAULT_GOAL)
ROOT ?= $(abspath $(S2DATA_HERE)../../..)
# (under m11.mk, M11's s2data: the directory the other parts read)
S2DATA_OUT ?= $(if $(M11),$(M11)/s2data,$(ROOT)/build/native/m11/s2data)
S2DATA_PYTHON ?= python3
S2DATA_INPUTS := $(ROOT)/build/upstream/data/DOOM1.WAD \
                 $(ROOT)/build/release/doom-hd.hdv
S2DATA_TOOLS := $(ROOT)/tools/native/s2data.py \
                $(ROOT)/tools/native/s2layout.py \
                $(ROOT)/tools/native/llayout.py \
                $(ROOT)/tools/native/rlayout.py \
                $(ROOT)/tools/native/lstore.py \
                $(ROOT)/tools/native/umodel.py

.PHONY: s2data s2data-check s2data-clean s2data_all

# (read by src/native/m11.mk: the part's name, and the store in its `all`)
PARTS += s2data
M11_HOST += s2data

s2data: $(S2DATA_OUT)/GFX.1
s2data_all: s2data

# the tool builds into the directory, then checks the files it wrote
# (the sources, the places, the read-back); a failed check removes GFX.1
# so the next make runs it again
$(S2DATA_OUT)/GFX.1: $(S2DATA_TOOLS) $(S2DATA_INPUTS)
	@mkdir -p $(S2DATA_OUT)
	$(S2DATA_PYTHON) $(ROOT)/tools/native/s2data.py --out $(S2DATA_OUT) \
	    > $(S2DATA_OUT)/s2data.log 2>&1 || { cat $(S2DATA_OUT)/s2data.log; \
	    rm -f $(S2DATA_OUT)/GFX.1; exit 1; }
	@tail -n 5 $(S2DATA_OUT)/s2data.log

# the include and the manifest, which the other parts' builds name, come
# from the same run, written after the bank files (so never older than
# GFX.1). This rule replaces the stand-in that s2fin's, s2hud's,
# s2menu1's and s2menu2's fragments give the manifest when this file is
# not read (make -f m11.mk part P=NAME): m11.mk reads the fragments in
# sorted order, so this file comes before theirs.
M11_S2DATA_JSON_RULE := 1
$(S2DATA_OUT)/s2data.json $(S2DATA_OUT)/s2data.inc: $(S2DATA_OUT)/GFX.1 ;

s2data-check: $(S2DATA_OUT)/GFX.1
	$(S2DATA_PYTHON) $(ROOT)/tools/native/s2data.py --check --report \
	    --out $(S2DATA_OUT)

# the files are removed by name (build/native/m11 is shared)
s2data-clean:
	rm -f $(S2DATA_OUT)/GFX.1 $(S2DATA_OUT)/GFX.2 $(S2DATA_OUT)/s2data.inc \
	    $(S2DATA_OUT)/s2data.json $(S2DATA_OUT)/s2data.lst \
	    $(S2DATA_OUT)/s2data.log

ifeq ($(words $(MAKEFILE_LIST)),1)
.DEFAULT_GOAL := s2data
else
.DEFAULT_GOAL := $(S2DATA_SAVED_GOAL)
endif
