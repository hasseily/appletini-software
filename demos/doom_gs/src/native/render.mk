# src/native/render.mk: the native renderer's front end (milestone 7,
# docs/RENDER.md), assembled with ca65 and linked with ld65 (cc65 2.18)
# into build/native/render/obj:
#
#   gen/rlayout.inc              from tools/native/rlayout.py (every
#                                address, record and zero-page byte)
#   rtest.w, .lc1, .far, .lce    checkpoint A's build: the walk with the
#                                a2vm test driver and its lockstep stub for
#                                R_StoreWallRange (render.cfg), for
#                                render_check.py
#   rprof.*                      the same, marking its phases (-D RPROF)
#   rwall.*                      the whole front end (stages A, B, C: the
#                                plane stamps, the weapon skip, the walk,
#                                the wall setup, the seg loops, the sky
#                                and the patchless columns, the records,
#                                the phase loader), with the driver's
#                                frame mode (drv_wframe) and routine mode;
#                                its W segments are the render window's
#                                code image (rwall.w, the `rcode` of
#                                RENDER.md 3.1)
#   rwprof.*                     the same, marking its phases
#   gen/segloops.s               the 13 seg loops (tools/native/seggen.py)
#   *.lbl, *.map, *.lst          symbols (VICE labels), maps, listings
#
# The tables it includes (smap.bin, the light and box tables) are the
# reference's: tools/native/rtables.py writes them into
# build/native/render/tables.
#
#   make -f render.mk            both builds
#   make -f render.mk sizes      the bytes of each area
#   make -f render.mk clean      removes build/native/render/obj only
#
# ROOT and OUT can be set, so a copy of these sources builds elsewhere
# (tests/test_native_render*.py plant bugs in one); SEGGEN too (a copy of
# the loops' generator).

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT ?= $(abspath $(HERE)../..)
RENDER ?= $(ROOT)/build/native/render
OUT ?= $(RENDER)/obj
TABLES ?= $(RENDER)/tables
GEN := $(OUT)/gen

CA65 = ca65
LD65 = ld65
PYTHON = python3
SEGGEN ?= $(ROOT)/tools/native/seggen.py
ASFLAGS = --cpu 65C02 -g -I $(HERE) -I $(GEN) --bin-include-dir $(TABLES)

SOURCES := rframe rbsp rlight auxlc far
WALL := rwall rseg rsky rrec segloops
TEST_OBJS := $(SOURCES:%=$(OUT)/%.o) $(OUT)/math-r.o $(OUT)/rdriver-l.o
PROF_OBJS := $(SOURCES:%=$(OUT)/%-p.o) $(OUT)/math-r.o $(OUT)/rdriver-l.o
WALL_OBJS := $(SOURCES:%=$(OUT)/%.o) $(WALL:%=$(OUT)/%.o) $(OUT)/math-r.o \
             $(OUT)/rdriver.o
WPROF_OBJS := $(SOURCES:%=$(OUT)/%-p.o) $(WALL:%=$(OUT)/%-p.o) \
             $(OUT)/math-r.o $(OUT)/rdriver.o

.PHONY: all sizes clean

all: $(OUT)/rtest.w $(OUT)/rprof.w $(OUT)/rwall.w $(OUT)/rwprof.w

$(TABLES)/smap.bin:
	@echo "no tables in $(TABLES): run python3 tools/native/rtables.py" >&2
	@exit 1

$(GEN)/rlayout.inc: $(ROOT)/tools/native/rlayout.py $(ROOT)/tools/native/layout.py
	@mkdir -p $(GEN)
	$(PYTHON) $(ROOT)/tools/native/rlayout.py $@

$(GEN)/segloops.s: $(SEGGEN)
	@mkdir -p $(GEN)
	$(PYTHON) $(SEGGEN) $@

$(OUT)/%.o: $(HERE)%.s $(GEN)/rlayout.inc $(HERE)math.inc $(HERE)rseg.inc \
            $(TABLES)/smap.bin
	$(CA65) $(ASFLAGS) -o $@ -l $(OUT)/$*.lst $<

$(OUT)/%-p.o: $(HERE)%.s $(GEN)/rlayout.inc $(HERE)math.inc \
              $(HERE)rseg.inc $(TABLES)/smap.bin
	$(CA65) $(ASFLAGS) -D RPROF -o $@ -l $(OUT)/$*-p.lst $<

$(OUT)/segloops.o: $(GEN)/segloops.s $(GEN)/rlayout.inc $(HERE)rseg.inc
	$(CA65) $(ASFLAGS) -o $@ -l $(OUT)/segloops.lst $<

$(OUT)/segloops-p.o: $(GEN)/segloops.s $(GEN)/rlayout.inc $(HERE)rseg.inc
	$(CA65) $(ASFLAGS) -D RPROF -o $@ -l $(OUT)/segloops-p.lst $<

$(OUT)/rdriver-l.o: $(HERE)rdriver.s $(GEN)/rlayout.inc $(HERE)math.inc
	$(CA65) $(ASFLAGS) -D LOCKSTEP -o $@ -l $(OUT)/rdriver-l.lst $<

$(OUT)/math-r.o: $(HERE)math.s $(HERE)math.inc
	@mkdir -p $(OUT)
	$(CA65) $(ASFLAGS) -D RENDER -o $@ -l $(OUT)/math-r.lst $<

$(OUT)/rtest.w: $(TEST_OBJS) $(HERE)render.cfg
	$(LD65) -C $(HERE)render.cfg -o $(OUT)/rtest -Ln $(OUT)/rtest.lbl \
	    -m $(OUT)/rtest.map $(TEST_OBJS)

$(OUT)/rprof.w: $(PROF_OBJS) $(HERE)render.cfg
	$(LD65) -C $(HERE)render.cfg -o $(OUT)/rprof -Ln $(OUT)/rprof.lbl \
	    -m $(OUT)/rprof.map $(PROF_OBJS)

$(OUT)/rwall.w: $(WALL_OBJS) $(HERE)render.cfg
	$(LD65) -C $(HERE)render.cfg -o $(OUT)/rwall -Ln $(OUT)/rwall.lbl \
	    -m $(OUT)/rwall.map $(WALL_OBJS)

$(OUT)/rwprof.w: $(WPROF_OBJS) $(HERE)render.cfg
	$(LD65) -C $(HERE)render.cfg -o $(OUT)/rwprof -Ln $(OUT)/rwprof.lbl \
	    -m $(OUT)/rwprof.map $(WPROF_OBJS)

sizes: all
	$(PYTHON) $(ROOT)/tools/native/render_check.py --sizes

clean:
	rm -rf $(OUT)
