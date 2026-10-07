# src/native/render.mk: the native renderer (docs/RENDER.md), assembled
# with ca65 and linked with ld65 (cc65 2.18) into build/native/render/obj:
#
#   gen/rlayout.inc              from tools/native/rlayout.py (every
#                                address, record and zero-page byte)
#   *.o                          the frame's objects
#                                (docs/RENDER-MASKED.md): the front end
#                                (rframe.s, rbsp.s, rlight.s, wclip.s,
#                                wpsp.s), the walls (rwall.s, rseg.s,
#                                rsky.s, rrec.s, segloops), the masked
#                                phase (mmain.s, mproj.s, msprite.s,
#                                mvis.s, mwall.s, mfar.s, mpsp.s; -c with
#                                the clip log, -D CLIPLOG), the bucket pass
#                                (bucket.s), the replay
#                                (replay.s with the generated rows.s and
#                                layout.inc) and the driver's drv_fframe
#                                (rdriver-f.o): m11/s2ovl.mk links the
#                                frame image ovf from them (OVLW's places)
#   *-p.o                        the same, marking their phases (-D RPROF)
#   rcard.*                      RENDER.SYSTEM (docs/RENDER-MASKED.md):
#                                the -p objects (their phase marks are
#                                in the game's code too; the marks'
#                                stores go to $0300, which the frame block's page
#                                holds) with the card runner rrunner.s in
#                                place of the driver: rcard.boot at $2000
#                                under ProDOS, the card image from
#                                rcard.lc1/.far/.lc2/.lce/.rc/.vec; for
#                                playdisk.py (WCODE_BANK, MCODE_BANK)
#   gen/layout.inc, gen/rows.s   from tools/native/rowgen.py (the
#                                replay's)
#   gen/llayout.inc, gen/lgame.inc  from tools/native/llayout.py
#                                (gvalid.s's clear: the lines' bank and
#                                records, the level's counts, G_VALID)
#   gen/segloops.s               the 13 seg loops (tools/native/seggen.py)
#   *.lbl, *.map, *.lst          symbols (VICE labels), maps, listings
#
# The tables it includes (smap.bin, the light and box tables) are the
# reference's: tools/native/rtables.py writes them into
# build/native/render/tables.
#
#   make -f render.mk            rcard, the release build (= release)
#   make -f render.mk stops      the same image without -D RELEASE, in
#                                build/native/render/stops (rcard.*)
#   make -f render.mk clean      removes build/native/render/obj and stops
#
# The release build (RELEASE = 1, the default) assembles rrec.s, bucket.s
# and replay.s with -D RELEASE (docs/RENDER-MASKED.md 10): a frame whose
# records pass a limit (the staging full, a column past a batch's 8,192
# bytes, a column past the replay's stage) is cut, STATUS = ST_RECORDS,
# and completes; the game goes on. With RELEASE empty (the stops target)
# each limit stops the frame (STATUS, BRK), as the host tests may want.
# Every object of a build takes the same RELEASE: rcard (the disk's
# renderer, playdisk.py), and m11/s2ovl.mk's ovf and OVLW, which build
# render.mk's objects with their own OUT and the default, so OVLW's places
# are rcard's (s2ovl.py --check-frame checks it).
#
# ROOT and OUT can be set (m11/s2ovl.mk builds the frame's objects with
# its own OUT); SEGGEN and RELEASE too.

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
RELEASE ?= 1
REL := $(if $(RELEASE),-D RELEASE)

SOURCES := rframe rbsp rlight auxlc far wclip wpsp gvalid-r
WALL := rwall rseg rsky rrec segloops
MASK := mmain mproj mfar msprite mvis mwall mpsp
RCARD_OBJS := $(SOURCES:%=$(OUT)/%-p.o) $(WALL:%=$(OUT)/%-p.o) \
             $(MASK:%=$(OUT)/%-p.o) $(OUT)/rrec-mp.o $(OUT)/wpsp-m.o \
             $(OUT)/math-r.o $(OUT)/rrunner.o $(OUT)/bucket.o \
             $(OUT)/replay-r.o

.PHONY: all release stops clean

all release: $(OUT)/rcard.w

# the same image without -D RELEASE: every limit stops the frame
stops:
	@$(MAKE) -f $(HERE)render.mk RELEASE= OUT=$(RENDER)/stops \
	    $(RENDER)/stops/rcard.w

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

$(GEN)/llayout.inc: $(ROOT)/tools/native/llayout.py \
            $(ROOT)/tools/native/rlayout.py
	@mkdir -p $(GEN)
	$(PYTHON) $(ROOT)/tools/native/llayout.py $@

$(GEN)/lgame.inc: $(ROOT)/tools/native/llayout.py \
            $(ROOT)/tools/native/rlayout.py
	@mkdir -p $(GEN)
	$(PYTHON) $(ROOT)/tools/native/llayout.py --game $@

$(GEN)/segloops.s: $(SEGGEN)
	@mkdir -p $(GEN)
	$(PYTHON) $(SEGGEN) $@

# a build from a copy of these sources takes the others (gvalid.s, the
# game's validcount) from the tree
vpath %.s $(HERE) $(ROOT)/src/native

# gvalid.s: validcount, one count with the game's (docs/GAME.md); a wrap
# clears every stamp with the renderer's own clear (-D GV_RENDER)
$(OUT)/gvalid-r.o: gvalid.s $(GEN)/rlayout.inc $(GEN)/llayout.inc \
            $(GEN)/lgame.inc
	$(CA65) $(ASFLAGS) -D GV_RENDER -o $@ -l $(OUT)/gvalid-r.lst $<

$(OUT)/gvalid-r-p.o: gvalid.s $(GEN)/rlayout.inc $(GEN)/llayout.inc \
            $(GEN)/lgame.inc
	$(CA65) $(ASFLAGS) -D GV_RENDER -D RPROF -o $@ \
	    -l $(OUT)/gvalid-r-p.lst $<

# rrec.s, bucket.s and replay.s: $(REL), the release build's cuts (an
# edit of this file makes them again)
RELDEP := $(HERE)render.mk
$(OUT)/rrec.o: $(HERE)rrec.s $(GEN)/rlayout.inc $(HERE)math.inc \
            $(RELDEP)
	$(CA65) $(ASFLAGS) $(REL) -o $@ -l $(OUT)/rrec.lst $<

$(OUT)/rrec-p.o: $(HERE)rrec.s $(GEN)/rlayout.inc $(HERE)math.inc \
            $(RELDEP)
	$(CA65) $(ASFLAGS) $(REL) -D RPROF -o $@ -l $(OUT)/rrec-p.lst $<

$(OUT)/bucket.o: $(HERE)bucket.s $(GEN)/rlayout.inc $(HERE)math.inc \
            $(RELDEP)
	$(CA65) $(ASFLAGS) $(REL) -o $@ -l $(OUT)/bucket.lst $<

$(OUT)/%.o: $(HERE)%.s $(GEN)/rlayout.inc $(HERE)math.inc $(HERE)rseg.inc \
            $(TABLES)/smap.bin
	$(CA65) $(ASFLAGS) -o $@ -l $(OUT)/$*.lst $<

$(OUT)/%-p.o: $(HERE)%.s $(GEN)/rlayout.inc $(HERE)math.inc \
              $(HERE)rseg.inc $(TABLES)/smap.bin
	$(CA65) $(ASFLAGS) -D RPROF -o $@ -l $(OUT)/$*-p.lst $<

$(OUT)/%-c.o: $(HERE)%.s $(GEN)/rlayout.inc $(HERE)math.inc \
              $(TABLES)/smap.bin
	$(CA65) $(ASFLAGS) -D CLIPLOG -o $@ -l $(OUT)/$*-c.lst $<

$(OUT)/rrec-m.o: $(HERE)rrec.s $(GEN)/rlayout.inc $(HERE)math.inc \
            $(RELDEP)
	$(CA65) $(ASFLAGS) $(REL) -D MREC -o $@ -l $(OUT)/rrec-m.lst $<

$(OUT)/rrec-mp.o: $(HERE)rrec.s $(GEN)/rlayout.inc $(HERE)math.inc \
            $(RELDEP)
	$(CA65) $(ASFLAGS) $(REL) -D MREC -D RPROF -o $@ \
	    -l $(OUT)/rrec-mp.lst $<

$(OUT)/segloops.o: $(GEN)/segloops.s $(GEN)/rlayout.inc $(HERE)rseg.inc
	$(CA65) $(ASFLAGS) -o $@ -l $(OUT)/segloops.lst $<

$(OUT)/segloops-p.o: $(GEN)/segloops.s $(GEN)/rlayout.inc $(HERE)rseg.inc
	$(CA65) $(ASFLAGS) -D RPROF -o $@ -l $(OUT)/segloops-p.lst $<

$(OUT)/rdriver-f.o: $(HERE)rdriver.s $(GEN)/rlayout.inc $(HERE)math.inc
	$(CA65) $(ASFLAGS) -D MASKED -D FRAME8 -o $@ -l $(OUT)/rdriver-f.lst $<

$(OUT)/wpsp-m.o: $(HERE)wpsp.s $(GEN)/rlayout.inc $(HERE)math.inc
	$(CA65) $(ASFLAGS) -D MPSP -o $@ -l $(OUT)/wpsp-m.lst $<

$(OUT)/bucket-p.o: $(HERE)bucket.s $(GEN)/rlayout.inc $(HERE)math.inc \
            $(RELDEP)
	$(CA65) $(ASFLAGS) $(REL) -D RPROF -o $@ -l $(OUT)/bucket-p.lst $<

$(OUT)/replay-r.o: $(HERE)replay.s $(GEN)/layout.inc $(GEN)/rows.s \
            $(RELDEP)
	$(CA65) $(ASFLAGS) $(REL) -o $@ -l $(OUT)/replay-r.lst $<

$(OUT)/math-r.o: $(HERE)math.s $(HERE)math.inc
	@mkdir -p $(OUT)
	$(CA65) $(ASFLAGS) -D RENDER -o $@ -l $(OUT)/math-r.lst $<

$(OUT)/rcard.w: $(RCARD_OBJS) $(HERE)render.cfg
	$(LD65) -C $(HERE)render.cfg -o $(OUT)/rcard -Ln $(OUT)/rcard.lbl \
	    -m $(OUT)/rcard.map $(RCARD_OBJS)

clean:
	rm -rf $(OUT) $(RENDER)/stops
