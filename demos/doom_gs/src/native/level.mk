# src/native/level.mk: the level load (docs/LEVELS.md),
# assembled with ca65 and linked with ld65 (cc65 2.18) into
# build/native/levels/obj:
#
#   gen/rlayout.inc, gen/llayout.inc
#                                from tools/native/rlayout.py and
#                                llayout.py
#   gen/lgame.inc                from tools/native/llayout.py --game
#                                (the game state's layout and the
#                                facts of upstream the game core takes)
#   gen/ggame.inc                from tools/native/glayout.py --ggame
#                                (the object API's places,
#                                which the game core uses here as in the
#                                tic images; the game core and gobj.s are
#                                assembled with -D LOADIMG: the planes far)
#   lcard.*                      the load phase's image (LCODE on the
#                                disk; playdisk.py): the load program's
#                                runner and transport (lload.s), the
#                                static steps (lgeom.s), P_SetupLevel
#                                (lsetup.s) and the game core (gthink.s,
#                                gvalid.s, gpos.s, gspawn.s, gweap.s,
#                                gspec.s), the far layer and the phase
#                                loader (far.s), the math (math.s's render
#                                subset, auxlc.s: MATHW and AUXW at W
#                                $6000, as the render images) and lboot.s,
#                                with level.cfg
#   *.lbl, *.map, *.lst          symbols (VICE labels), maps, listings
#
#   make -f level.mk             the build (play.mk runs it)
#   make -f level.mk clean       removes build/native/levels/obj only
#
# ROOT and OUT can be set. The math's tables
# (math.s includes them) are tools/native/rtables.py's, in
# build/native/render/tables.

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT ?= $(abspath $(HERE)../..)
OUT ?= $(ROOT)/build/native/levels/obj
TABLES ?= $(ROOT)/build/native/render/tables
GEN := $(OUT)/gen

CA65 = ca65
LD65 = ld65
PYTHON = python3
ASFLAGS = --cpu 65C02 -g -I $(HERE) -I $(GEN) --bin-include-dir $(TABLES) \
          --bin-include-dir $(TABLES)/math -D LOADIMG

# a build from a copy of some of these sources takes the others from
# the tree
vpath %.s $(HERE) $(ROOT)/src/native
vpath %.inc $(HERE) $(ROOT)/src/native

LOAD := lload lgeom lsetup gthink gpos gspawn gweap gspec gobj
COMMON := $(OUT)/far.o $(OUT)/math-r.o $(OUT)/auxlc.o
CARD_OBJS := $(LOAD:%=$(OUT)/%.o) $(OUT)/gvalid.o $(COMMON) $(OUT)/lboot.o
INCS := $(GEN)/rlayout.inc $(GEN)/llayout.inc $(GEN)/lgame.inc \
        $(GEN)/ggame.inc $(HERE)math.inc

.PHONY: all clean

all: $(OUT)/lcard.lw

$(TABLES)/math/squares.bin:
	@echo "no tables in $(TABLES): run python3 tools/native/rtables.py" >&2
	@exit 1

$(GEN)/rlayout.inc: $(ROOT)/tools/native/rlayout.py $(ROOT)/tools/native/layout.py
	@mkdir -p $(GEN)
	$(PYTHON) $(ROOT)/tools/native/rlayout.py $@

$(GEN)/llayout.inc: $(ROOT)/tools/native/llayout.py $(ROOT)/tools/native/rlayout.py
	@mkdir -p $(GEN)
	$(PYTHON) $(ROOT)/tools/native/llayout.py $@

$(GEN)/lgame.inc: $(ROOT)/tools/native/llayout.py $(ROOT)/tools/native/rlayout.py
	@mkdir -p $(GEN)
	$(PYTHON) $(ROOT)/tools/native/llayout.py --game $@

$(GEN)/ggame.inc: $(ROOT)/tools/native/glayout.py \
                  $(ROOT)/tools/native/llayout.py $(ROOT)/tools/native/rlayout.py
	@mkdir -p $(GEN)
	$(PYTHON) $(ROOT)/tools/native/glayout.py --ggame $@

$(OUT)/%.o: %.s $(INCS) $(TABLES)/math/squares.bin
	$(CA65) $(ASFLAGS) -o $@ -l $(OUT)/$*.lst $<

$(OUT)/math-r.o: math.s $(HERE)math.inc $(TABLES)/math/squares.bin
	@mkdir -p $(OUT)
	$(CA65) $(ASFLAGS) -D RENDER -o $@ -l $(OUT)/math-r.lst $<

$(OUT)/lcard.lw: $(CARD_OBJS) $(HERE)level.cfg
	$(LD65) -C $(HERE)level.cfg -o $(OUT)/lcard -Ln $(OUT)/lcard.lbl \
	    -m $(OUT)/lcard.map $(CARD_OBJS)

clean:
	rm -rf $(OUT)
