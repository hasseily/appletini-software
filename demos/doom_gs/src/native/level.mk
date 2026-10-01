# src/native/level.mk: the level load (milestone 9, docs/LEVELS.md 4.1),
# assembled with ca65 and linked with ld65 (cc65 2.18) into
# build/native/levels/obj:
#
#   gen/rlayout.inc, gen/llayout.inc
#                                from tools/native/rlayout.py and
#                                llayout.py
#   gen/lgame.inc                from tools/native/llayout.py --game
#                                (stage C: the game state's layout and the
#                                facts of upstream the game core takes)
#   ltest.w, .lw, .lc1, .far, .lce
#                                the test build: the load program's
#                                runner and transport (lload.s), the
#                                static steps (lgeom.s), stage C's
#                                P_SetupLevel (lsetup.s) and game core
#                                (gthink.s, gvalid.s, gpos.s, gspawn.s,
#                                gweap.s, gspec.s; validcount's wrap as
#                                upstream's: -D VCWRAP_UPSTREAM), the far
#                                layer and the phase loader (far.s), the
#                                math (math.s's render subset, auxlc.s:
#                                MATHW and AUXW at W $6000, as the render
#                                images) and the a2vm test driver
#                                (ldriver.s) with level.cfg; its W
#                                segments are the load phase's image
#                                (LCODE)
#   lprof.*                      the same, marking the cost phases
#                                (-D LPROF)
#   lfix.*                       ltest with the release's validcount (the
#                                wrap fix of docs/LEVELS.md 3.4), for its
#                                unit test
#   lcard.*                      LEVELS.SYSTEM (lboot.s in place of the
#                                driver: the boot from ProDOS, the store's
#                                bank files, the card, the loads and the
#                                setups), the release's validcount (the
#                                design's lgame), for tools/native/ldisk.py
#   *.lbl, *.map, *.lst          symbols (VICE labels), maps, listings
#
#   make -f level.mk             the builds
#   make -f level.mk sizes       each module's bytes against its budget
#   make -f level.mk clean       removes build/native/levels/obj only
#
# ROOT and OUT can be set, so a copy of these sources builds elsewhere
# (tests/test_native_level_load.py plants bugs in one). The math's tables
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
          --bin-include-dir $(TABLES)/math

LOAD := lload lgeom lsetup gthink gpos gspawn gweap gspec
COMMON := $(OUT)/far.o $(OUT)/math-r.o $(OUT)/auxlc.o
TEST_OBJS := $(LOAD:%=$(OUT)/%.o) $(OUT)/gvalid-u.o $(COMMON) \
             $(OUT)/ldriver.o
PROF_OBJS := $(LOAD:%=$(OUT)/%-p.o) $(OUT)/gvalid-u.o $(COMMON) \
             $(OUT)/ldriver.o
FIX_OBJS := $(LOAD:%=$(OUT)/%.o) $(OUT)/gvalid.o $(COMMON) $(OUT)/ldriver.o
CARD_OBJS := $(LOAD:%=$(OUT)/%.o) $(OUT)/gvalid.o $(COMMON) $(OUT)/lboot.o
INCS := $(GEN)/rlayout.inc $(GEN)/llayout.inc $(GEN)/lgame.inc \
        $(HERE)math.inc

.PHONY: all sizes clean

all: $(OUT)/ltest.lw $(OUT)/lprof.lw $(OUT)/lfix.lw $(OUT)/lcard.lw

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

$(OUT)/%.o: $(HERE)%.s $(INCS) $(TABLES)/math/squares.bin
	$(CA65) $(ASFLAGS) -o $@ -l $(OUT)/$*.lst $<

$(OUT)/%-p.o: $(HERE)%.s $(INCS)
	$(CA65) $(ASFLAGS) -D LPROF -o $@ -l $(OUT)/$*-p.lst $<

$(OUT)/gvalid-u.o: $(HERE)gvalid.s $(INCS)
	$(CA65) $(ASFLAGS) -D VCWRAP_UPSTREAM -o $@ -l $(OUT)/gvalid-u.lst $<

$(OUT)/math-r.o: $(HERE)math.s $(HERE)math.inc $(TABLES)/math/squares.bin
	@mkdir -p $(OUT)
	$(CA65) $(ASFLAGS) -D RENDER -o $@ -l $(OUT)/math-r.lst $<

$(OUT)/ltest.lw: $(TEST_OBJS) $(HERE)level.cfg
	$(LD65) -C $(HERE)level.cfg -o $(OUT)/ltest -Ln $(OUT)/ltest.lbl \
	    -m $(OUT)/ltest.map $(TEST_OBJS)

$(OUT)/lprof.lw: $(PROF_OBJS) $(HERE)level.cfg
	$(LD65) -C $(HERE)level.cfg -o $(OUT)/lprof -Ln $(OUT)/lprof.lbl \
	    -m $(OUT)/lprof.map $(PROF_OBJS)

$(OUT)/lfix.lw: $(FIX_OBJS) $(HERE)level.cfg
	$(LD65) -C $(HERE)level.cfg -o $(OUT)/lfix -Ln $(OUT)/lfix.lbl \
	    -m $(OUT)/lfix.map $(FIX_OBJS)

$(OUT)/lcard.lw: $(CARD_OBJS) $(HERE)level.cfg
	$(LD65) -C $(HERE)level.cfg -o $(OUT)/lcard -Ln $(OUT)/lcard.lbl \
	    -m $(OUT)/lcard.map $(CARD_OBJS)

sizes: all
	$(PYTHON) $(ROOT)/tools/native/lrun.py --sizes

clean:
	rm -rf $(OUT)
