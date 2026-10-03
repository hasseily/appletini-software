# src/native/game.mk: the tic phase's images (milestone 10, docs/GAME.md
# 3.3), assembled with ca65 and linked with ld65 (cc65 2.18).
#
#   make -f game.mk shared         the shared outputs (the integrator's):
#                                  build/native/game/shared/gen/ggame.inc,
#                                  gplace.inc, gdisp.inc (the integrated
#                                  waves' parts built:
#                                  src/native/game/integrated.txt),
#                                  game.cfg, native-game-1.json and its
#                                  manifests (tools/native/glayout.py),
#                                  callgraph.json (gcallgraph.py)
#   make -f game.mk part P=look    the part's test image: milestone 9's game
#                                  core, the skeleton's runtime, every part
#                                  of an earlier wave or of an integrated
#                                  wave (integrated.txt), and the part; into
#                                  build/native/game/look/ (its own OUT and
#                                  GEN: its gplace.inc and gdisp.inc count
#                                  the earlier waves and the part as built)
#   make -f game.mk wave W=3       every part of waves 1-3 (the integrator)
#   make -f game.mk game           the lockstep build: every part,
#                                  LOCKSTEP, VCWRAP_UPSTREAM, TESTBUILD,
#                                  TICLEVEL (the tic-level driver)
#   make -f game.mk gprof          the same with the cost phases (GPROF)
#   make -f game.mk release        no LOCKSTEP, no TESTBUILD, the wrap fix
#   make -f game.mk skel           the skeleton's own test image: no part,
#                                  its test routines (game/gtest.s) in the
#                                  test placement (glayout.TEST_GROUPS)
#   make -f game.mk place          the placement (gplace.py --write:
#                                  shared/placement.json, from the heat,
#                                  the survey and the sizes; the
#                                  integrator's, then make shared)
#   make -f game.mk sizes          each part's bytes against its budget,
#                                  each image's and slot's fill
#   make -f game.mk clean          build/native/game/* but shared/
#
# Each image is IMAGE.w (W $6000-$65FF: MATHW, AUXW), IMAGE.core (the core,
# $6600-$97FF), IMAGE.gN (group N at its slot's address), IMAGE.lc1,
# .far, .lce (the card: the products, the far layer and the phase loader,
# the test driver gdriver.s), .lbl, .map, .lst. The parts' fragments are
# src/native/game/*/part.mk:
#
#   PART := look
#   WAVE := 3
#   look_SRC := game/look/look.s game/look/range.s
#   look_ENTRIES := A_Look lookForPlayers P_CheckMeleeRange
#
# A part's sources assemble with ggame.inc, gplace.inc, gdisp.inc,
# math.inc, rlayout.inc, llayout.inc, lgame.inc (-I its GEN first).
# ROOT can be set, so a copy of these sources builds elsewhere (the tests'
# planted bugs); a source the copy lacks comes from the tree (vpath).

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT ?= $(abspath $(HERE)../..)
GAME ?= $(ROOT)/build/native/game
SHARED ?= $(GAME)/shared
TABLES ?= $(ROOT)/build/native/render/tables
LAYOUT := $(ROOT)/tools/native/glayout.py
PYTHON = python3
CA65 = ca65
LD65 = ld65

vpath %.s $(HERE) $(ROOT)/src/native
vpath %.inc $(HERE) $(ROOT)/src/native

# the parts' fragments: each appends its PART to PARTS
PARTS :=
define add_part
PARTS += $(PART)
WAVE_$(PART) := $(WAVE)
endef
FRAGMENTS := $(sort $(wildcard $(HERE)game/*/part.mk))
$(foreach f,$(FRAGMENTS),$(eval include $(f))$(eval $(call add_part)))

# the runtime and milestone 9's game core, in every tic image; the math:
# the render build (math-r: MATHW's subset, the card's products) and the
# game's (math-g: R_PointToAngle3, finesine, finecosine in the core; wave 2
# as integrated, docs/game-parts/damage.md R1). Not gspec.s: the load's
# SPECIALS step runs in the load image (level.mk's LCODE, which the
# drivers' load protocol runs); no tic image calls it (docs/SPEED.md 9)
RUNTIME := gobj gcall ghook gthink gpos gspawn gweap
COMMON := far math-r math-g auxlc

.PHONY: all shared place part wave game gprof release skel sizes clean

all: skel

# ---------------------------------------------------------------------------
# an image: $(call image,NAME,OUT,SOURCES,FLAGS,GLAYOUT-ARGS)
# ---------------------------------------------------------------------------
INC_ALL = $(1)/rlayout.inc $(1)/llayout.inc $(1)/lgame.inc \
          $(1)/ggame.inc $(1)/gplace.inc $(1)/gdisp.inc

define image
$(2)/gen/rlayout.inc: $(ROOT)/tools/native/rlayout.py
	@mkdir -p $(2)/gen
	$(PYTHON) $(ROOT)/tools/native/rlayout.py $$@
$(2)/gen/llayout.inc: $(ROOT)/tools/native/llayout.py
	@mkdir -p $(2)/gen
	$(PYTHON) $(ROOT)/tools/native/llayout.py $$@
$(2)/gen/lgame.inc: $(ROOT)/tools/native/llayout.py
	@mkdir -p $(2)/gen
	$(PYTHON) $(ROOT)/tools/native/llayout.py --game $$@
$(2)/gen/stamp: $(LAYOUT) $(ROOT)/tools/native/llayout.py \
        $(ROOT)/tools/native/gcallgraph.py $(HERE)game/integrated.txt \
        $(wildcard $(SHARED)/placement.json)
	@mkdir -p $(2)/gen
	$(PYTHON) $(LAYOUT) --out $(2) --no-manifests $(5) > /dev/null
	@touch $$@
$(2)/gen/ggame.inc $(2)/gen/gplace.inc $(2)/gen/gdisp.inc $(2)/game.cfg: \
        $(2)/gen/stamp
	@test -f $$@
$(2)/%.o: %.s $(call INC_ALL,$(2)/gen) $(HERE)math.inc
	@mkdir -p $$(dir $$@)
	$(CA65) --cpu 65C02 -g -I $(2)/gen -I $(HERE) -I $(ROOT)/src/native \
	    --bin-include-dir $(TABLES) --bin-include-dir $(TABLES)/math \
	    $(4) -o $$@ -l $$(@:.o=.lst) $$<
$(2)/math-r.o: math.s mathgame.inc $(HERE)math.inc
	@mkdir -p $(2)
	$(CA65) --cpu 65C02 -g -I $(2)/gen -I $(HERE) \
	    --bin-include-dir $(TABLES) --bin-include-dir $(TABLES)/math \
	    -D RENDER -o $$@ -l $(2)/math-r.lst $$<
$(2)/math-g.o: math.s mathgame.inc $(HERE)math.inc
	@mkdir -p $(2)
	$(CA65) --cpu 65C02 -g -I $(2)/gen -I $(HERE) \
	    --bin-include-dir $(TABLES) --bin-include-dir $(TABLES)/math \
	    -D GAMEMATH -o $$@ -l $(2)/math-g.lst $$<
$(2)/gvalid-u.o: gvalid.s $(call INC_ALL,$(2)/gen)
	$(CA65) --cpu 65C02 -g -I $(2)/gen -I $(HERE) $(4) -D VCWRAP_UPSTREAM \
	    -o $$@ -l $(2)/gvalid-u.lst $$<
$(2)/$(1).core: $(addprefix $(2)/,$(3:%=%.o)) $(2)/game.cfg
	$(LD65) -C $(2)/game.cfg -o $(2)/$(1) -Ln $(2)/$(1).lbl \
	    -m $(2)/$(1).map $(addprefix $(2)/,$(3:%=%.o))
endef

TEST_FLAGS := -D TESTBUILD -D LOCKSTEP
OBJS_TEST := $(RUNTIME) gvalid-u gdriver $(COMMON)
PLUS = $(subst $(space),+,$(strip $(1)))
space := $(subst ,, )

# the skeleton's own test image (S5): no part; gtest.s's routines in the
# test placement
SKEL := $(GAME)/skel
$(eval $(call image,skel,$(SKEL),$(OBJS_TEST) game/gtest game/grec,$(TEST_FLAGS),--built none --test-place))
skel: $(SKEL)/skel.core

# a part's test image
ifneq ($(P),)
PDIR := $(GAME)/$(P)
PWAVES := $(shell seq 1 $(WAVE_$(P)))
# the earlier waves' parts, and every part of an integrated wave (a part of
# an integrated wave is rerun with its wave's other parts: GAME.md "Wave 1
# as integrated"); src/native/game/integrated.txt
INTEGRATED := $(firstword $(shell cat $(HERE)game/integrated.txt 2>/dev/null) 0)
IWAVES := $(if $(filter-out 0,$(INTEGRATED)),$(shell seq 1 $(INTEGRATED)))
PEARLY := $(foreach q,$(filter-out $(P),$(PARTS)),$(if $(or $(filter-out $(WAVE_$(P)),$(filter $(WAVE_$(q)),$(PWAVES))),$(filter $(WAVE_$(q)),$(IWAVES))),$(q)))
PSRC := $(foreach q,$(PEARLY) $(P),$($(q)_SRC))
$(eval $(call image,ptest,$(PDIR),$(OBJS_TEST) game/grec $(PSRC:%.s=%),$(TEST_FLAGS),--part $(P) --test-place))
part: $(PDIR)/ptest.core
else
part:
	@echo "make -f game.mk part P=NAME (one of: $(PARTS))" >&2; exit 2
endif

# every part of waves 1 to W
ifneq ($(W),)
WDIR := $(GAME)/wave$(W)
WPARTS := $(foreach q,$(PARTS),$(if $(filter $(WAVE_$(q)),$(shell seq 1 $(W))),$(q)))
WSRC := $(foreach q,$(WPARTS),$($(q)_SRC))
$(eval $(call image,wtest,$(WDIR),$(OBJS_TEST) game/grec $(WSRC:%.s=%),$(TEST_FLAGS),--built $(if $(WPARTS),$(call PLUS,$(WPARTS)),none) --test-place))
wave: $(WDIR)/wtest.core
else
wave:
	@echo "make -f game.mk wave W=N" >&2; exit 2
endif

# the lockstep build, its profile, the release
ALLSRC := $(foreach q,$(PARTS),$($(q)_SRC))
ALLBUILT := $(if $(PARTS),$(call PLUS,$(PARTS)),none)
# (TICLEVEL: the driver's tic-level runs, the stream and the frames'
# renderer: the lockstep builds only, as the parts' images keep their room
# in the driver's area; docs/GAME.md "Acceptance")
$(eval $(call image,game,$(GAME)/game,$(OBJS_TEST) game/grec $(ALLSRC:%.s=%),$(TEST_FLAGS) -D TICLEVEL,--built $(ALLBUILT) --test-place))
$(eval $(call image,gprof,$(GAME)/gprof,$(OBJS_TEST) game/grec $(ALLSRC:%.s=%),$(TEST_FLAGS) -D TICLEVEL -D GPROF,--built $(ALLBUILT) --test-place))
$(eval $(call image,grel,$(GAME)/release,$(RUNTIME) gvalid gdriver $(COMMON) $(ALLSRC:%.s=%),,--built $(ALLBUILT)))
game: $(GAME)/game/game.core
gprof: $(GAME)/gprof/gprof.core
release: $(GAME)/release/grel.core

shared:
	$(PYTHON) $(ROOT)/tools/native/gcallgraph.py --check
	$(PYTHON) $(LAYOUT) --out $(SHARED)

place:
	$(PYTHON) $(ROOT)/tools/native/gplace.py --write

sizes: skel
	$(PYTHON) $(ROOT)/tools/native/grun.py --sizes

clean:
	rm -rf $(SKEL) $(GAME)/game $(GAME)/gprof $(GAME)/release \
	    $(foreach q,$(PARTS),$(GAME)/$(q)) $(wildcard $(GAME)/wave*)
