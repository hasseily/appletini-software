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
#   mtest.*                      milestone 8 (docs/RENDER-MASKED.md): the
#                                front end and the masked phase's image
#                                (mtest.wm: mmain.s, mproj.s, msprite.s,
#                                mvis.s, mwall.s and rrec.s again with
#                                -D MREC from MCODE; mfar.s in the card),
#                                with the driver's drv_mframe (-D MASKED);
#                                the masked sources with the clip log
#                                (-D CLIPLOG, RENDER-MASKED.md 4.2)
#   mprof.*                      the same without the clip log, marking
#                                its phases
#   btest.*                      the bucket pass alone (bucket.s, bdriver.s
#                                with its stand-in for the replay;
#                                bucket.cfg: BKNEAR in the card's $F900
#                                part, BKFAR in main $0C00-$0EFF, BKFAR2
#                                in $0200-$02FF), for bucketcheck.py
#   ftest.*                      milestone 8, stage C: the whole frame
#                                (docs/RENDER-MASKED.md 3.2): mtest's
#                                objects with the weapon (wclip.s, wpsp.s
#                                in the front end; mpsp.s, wpsp.s again
#                                with -D MPSP in the masked image), the
#                                bucket pass (bucket.s: BKFAR, BKFAR2 in
#                                the masked image, BKNEAR in the card),
#                                milestone 5's replay (replay.s with the
#                                generated rows.s and layout.inc: the card
#                                bank 2 part ftest.lc2, $F900 ftest.rc,
#                                main $0800 ftest.m08, aux 0 ftest.a02 and
#                                ftest.a08) and the driver's drv_fframe
#                                (-D MASKED -D FRAME8); with the clip log
#   fprof.*                      the same without the clip log, marking
#                                its phases (the replay's own marks off:
#                                the driver and nb_frame mark phase 12)
#   rcard.*                      RENDER.SYSTEM (docs/RENDER-MASKED.md 4.6):
#                                fprof's objects (its phase marks: the
#                                timing builds' code; the marks' stores go
#                                to $0300, which the frame block's page
#                                holds) with the card runner rrunner.s in
#                                place of the driver: rcard.boot at $2000
#                                under ProDOS, the card image from
#                                rcard.lc1/.far/.lc2/.lce/.rc/.vec; for
#                                tools/native/rdisk.py
#   gen/layout.inc, gen/rows.s   from tools/native/rowgen.py (milestone 5's
#                                replay, for ftest and fprof)
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

SOURCES := rframe rbsp rlight auxlc far wclip wpsp gvalid-r
WALL := rwall rseg rsky rrec segloops
MASK := mmain mproj mfar msprite mvis mwall mpsp
TEST_OBJS := $(SOURCES:%=$(OUT)/%.o) $(OUT)/math-r.o $(OUT)/rdriver-l.o
PROF_OBJS := $(SOURCES:%=$(OUT)/%-p.o) $(OUT)/math-r.o $(OUT)/rdriver-l.o
WALL_OBJS := $(SOURCES:%=$(OUT)/%.o) $(WALL:%=$(OUT)/%.o) $(OUT)/math-r.o \
             $(OUT)/rdriver.o
WPROF_OBJS := $(SOURCES:%=$(OUT)/%-p.o) $(WALL:%=$(OUT)/%-p.o) \
             $(OUT)/math-r.o $(OUT)/rdriver.o
MCOMMON := $(SOURCES:%=$(OUT)/%.o) $(WALL:%=$(OUT)/%.o) \
             $(MASK:%=$(OUT)/%-c.o) $(OUT)/rrec-m.o $(OUT)/wpsp-m.o \
             $(OUT)/math-r.o
MPCOMMON := $(SOURCES:%=$(OUT)/%-p.o) $(WALL:%=$(OUT)/%-p.o) \
             $(MASK:%=$(OUT)/%-p.o) $(OUT)/rrec-mp.o $(OUT)/wpsp-m.o \
             $(OUT)/math-r.o
MTEST_OBJS := $(MCOMMON) $(OUT)/rdriver-m.o
MPROF_OBJS := $(MPCOMMON) $(OUT)/rdriver-m.o
FTEST_OBJS := $(MCOMMON) $(OUT)/rdriver-f.o $(OUT)/bucket.o \
             $(OUT)/replay-r.o
FPROF_OBJS := $(MPCOMMON) $(OUT)/rdriver-f.o $(OUT)/bucket-p.o \
             $(OUT)/replay-r.o
RCARD_OBJS := $(SOURCES:%=$(OUT)/%-p.o) $(WALL:%=$(OUT)/%-p.o) \
             $(MASK:%=$(OUT)/%-p.o) $(OUT)/rrec-mp.o $(OUT)/wpsp-m.o \
             $(OUT)/math-r.o $(OUT)/rrunner.o $(OUT)/bucket.o \
             $(OUT)/replay-r.o

.PHONY: all sizes clean

all: $(OUT)/rtest.w $(OUT)/rprof.w $(OUT)/rwall.w $(OUT)/rwprof.w \
     $(OUT)/mtest.w $(OUT)/mprof.w $(OUT)/btest.near $(OUT)/ftest.w \
     $(OUT)/fprof.w $(OUT)/rcard.w

$(TABLES)/smap.bin:
	@echo "no tables in $(TABLES): run python3 tools/native/rtables.py" >&2
	@exit 1

$(GEN)/rlayout.inc: $(ROOT)/tools/native/rlayout.py $(ROOT)/tools/native/layout.py
	@mkdir -p $(GEN)
	$(PYTHON) $(ROOT)/tools/native/rlayout.py $@

$(GEN)/layout.inc $(GEN)/rows.s: $(ROOT)/tools/native/rowgen.py \
            $(ROOT)/tools/native/layout.py
	@mkdir -p $(GEN)
	$(PYTHON) $(ROOT)/tools/native/rowgen.py $(GEN)

$(GEN)/segloops.s: $(SEGGEN)
	@mkdir -p $(GEN)
	$(PYTHON) $(SEGGEN) $@

# a copy of some of these sources (the tests' planted bugs) takes the
# others from the tree (milestone 10: gvalid.s, the game's validcount)
vpath %.s $(HERE) $(ROOT)/src/native

# gvalid.s: validcount, one count with the game's (docs/GAME.md 1.7): the
# render images' test builds increment as upstream (VCWRAP_UPSTREAM)
$(OUT)/gvalid-r.o: gvalid.s $(GEN)/rlayout.inc
	$(CA65) $(ASFLAGS) -D GV_RENDER -D VCWRAP_UPSTREAM -o $@ \
	    -l $(OUT)/gvalid-r.lst $<

$(OUT)/gvalid-r-p.o: gvalid.s $(GEN)/rlayout.inc
	$(CA65) $(ASFLAGS) -D GV_RENDER -D VCWRAP_UPSTREAM -D RPROF -o $@ \
	    -l $(OUT)/gvalid-r-p.lst $<

$(OUT)/%.o: $(HERE)%.s $(GEN)/rlayout.inc $(HERE)math.inc $(HERE)rseg.inc \
            $(TABLES)/smap.bin
	$(CA65) $(ASFLAGS) -o $@ -l $(OUT)/$*.lst $<

$(OUT)/%-p.o: $(HERE)%.s $(GEN)/rlayout.inc $(HERE)math.inc \
              $(HERE)rseg.inc $(TABLES)/smap.bin
	$(CA65) $(ASFLAGS) -D RPROF -o $@ -l $(OUT)/$*-p.lst $<

$(OUT)/%-c.o: $(HERE)%.s $(GEN)/rlayout.inc $(HERE)math.inc \
              $(TABLES)/smap.bin
	$(CA65) $(ASFLAGS) -D CLIPLOG -o $@ -l $(OUT)/$*-c.lst $<

$(OUT)/rrec-m.o: $(HERE)rrec.s $(GEN)/rlayout.inc $(HERE)math.inc
	$(CA65) $(ASFLAGS) -D MREC -o $@ -l $(OUT)/rrec-m.lst $<

$(OUT)/rrec-mp.o: $(HERE)rrec.s $(GEN)/rlayout.inc $(HERE)math.inc
	$(CA65) $(ASFLAGS) -D MREC -D RPROF -o $@ -l $(OUT)/rrec-mp.lst $<

$(OUT)/segloops.o: $(GEN)/segloops.s $(GEN)/rlayout.inc $(HERE)rseg.inc
	$(CA65) $(ASFLAGS) -o $@ -l $(OUT)/segloops.lst $<

$(OUT)/segloops-p.o: $(GEN)/segloops.s $(GEN)/rlayout.inc $(HERE)rseg.inc
	$(CA65) $(ASFLAGS) -D RPROF -o $@ -l $(OUT)/segloops-p.lst $<

$(OUT)/rdriver-l.o: $(HERE)rdriver.s $(GEN)/rlayout.inc $(HERE)math.inc
	$(CA65) $(ASFLAGS) -D LOCKSTEP -o $@ -l $(OUT)/rdriver-l.lst $<

$(OUT)/rdriver-m.o: $(HERE)rdriver.s $(GEN)/rlayout.inc $(HERE)math.inc
	$(CA65) $(ASFLAGS) -D MASKED -o $@ -l $(OUT)/rdriver-m.lst $<

$(OUT)/rdriver-f.o: $(HERE)rdriver.s $(GEN)/rlayout.inc $(HERE)math.inc
	$(CA65) $(ASFLAGS) -D MASKED -D FRAME8 -o $@ -l $(OUT)/rdriver-f.lst $<

$(OUT)/wpsp-m.o: $(HERE)wpsp.s $(GEN)/rlayout.inc $(HERE)math.inc
	$(CA65) $(ASFLAGS) -D MPSP -o $@ -l $(OUT)/wpsp-m.lst $<

$(OUT)/bucket-p.o: $(HERE)bucket.s $(GEN)/rlayout.inc $(HERE)math.inc
	$(CA65) $(ASFLAGS) -D RPROF -o $@ -l $(OUT)/bucket-p.lst $<

$(OUT)/replay-r.o: $(HERE)replay.s $(GEN)/layout.inc $(GEN)/rows.s
	$(CA65) $(ASFLAGS) -o $@ -l $(OUT)/replay-r.lst $<

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

$(OUT)/mtest.w: $(MTEST_OBJS) $(HERE)render.cfg
	$(LD65) -C $(HERE)render.cfg -o $(OUT)/mtest -Ln $(OUT)/mtest.lbl \
	    -m $(OUT)/mtest.map $(MTEST_OBJS)

$(OUT)/btest.near: $(OUT)/bucket.o $(OUT)/bdriver.o $(HERE)bucket.cfg
	$(LD65) -C $(HERE)bucket.cfg -o $(OUT)/btest -Ln $(OUT)/btest.lbl \
	    -m $(OUT)/btest.map $(OUT)/bucket.o $(OUT)/bdriver.o

$(OUT)/mprof.w: $(MPROF_OBJS) $(HERE)render.cfg
	$(LD65) -C $(HERE)render.cfg -o $(OUT)/mprof -Ln $(OUT)/mprof.lbl \
	    -m $(OUT)/mprof.map $(MPROF_OBJS)

$(OUT)/ftest.w: $(FTEST_OBJS) $(HERE)render.cfg
	$(LD65) -C $(HERE)render.cfg -o $(OUT)/ftest -Ln $(OUT)/ftest.lbl \
	    -m $(OUT)/ftest.map $(FTEST_OBJS)

$(OUT)/rcard.w: $(RCARD_OBJS) $(HERE)render.cfg
	$(LD65) -C $(HERE)render.cfg -o $(OUT)/rcard -Ln $(OUT)/rcard.lbl \
	    -m $(OUT)/rcard.map $(RCARD_OBJS)

$(OUT)/fprof.w: $(FPROF_OBJS) $(HERE)render.cfg
	$(LD65) -C $(HERE)render.cfg -o $(OUT)/fprof -Ln $(OUT)/fprof.lbl \
	    -m $(OUT)/fprof.map $(FPROF_OBJS)

sizes: all
	$(PYTHON) $(ROOT)/tools/native/render_check.py --sizes

clean:
	rm -rf $(OUT)
