# src/native/m11/s2ovl.mk: part s2ovl's builds (docs/SCREENS.md 1.5.4,
# 4.1, 4.5, 7.3; docs/m11-parts/s2ovl.md), read by src/native/m11.mk
# (make -f m11.mk part P=s2ovl):
#
#   build/native/m11/s2ovl/render/*.o   milestone 8's objects of the whole
#                                    frame (render.mk's ftest and fprof,
#                                    built by render.mk itself with OUT
#                                    here: its sources and tables read
#                                    only)
#   build/native/m11/s2ovl/gen/s2amap.inc  part s2amap's generated include
#                                    (tools/native/s2amap.py --inc)
#   build/native/m11/s2ovl/s2_amline-ovl.o  part s2amap's s2_amline.s
#                                    assembled with -D AM_FASTLINE: the
#                                    fast path's hook (request S2OVL-1,
#                                    applied in wave 7)
#   build/native/m11/s2ovl/ovf.*     milestone 8's whole frame (ftest's
#                                    objects, render.cfg) with this
#                                    part's driver s2_ovd.s
#   build/native/m11/s2ovl/ovlw.*    the image OVLW: s2_ovl.s,
#                                    s2_amline.s (the hook), milestone 8's
#                                    rrec.s (-D MREC) and bucket.s, alone
#                                    in MASKW's code room (ovlw.cfg, made
#                                    by s2ovl.py --ovlw-cfg from ovf's
#                                    labels: the far layer, the math, the
#                                    replay and the bucket pass's card part
#                                    at the frame's addresses); ovlw.sizes
#                                    its size table (s2layout --check-map)
#   build/native/m11/s2ovl/ovfp.*, ovlwp.*   the same from fprof's
#                                    objects (the timing builds)
#
# S2OV_R can be set (the planted bugs' scratch builds take milestone 8's
# objects from the tree's build).

S2OV_DIR := $(M11)/s2ovl
S2OV_GEN := $(S2OV_DIR)/gen
S2OV_R ?= $(S2OV_DIR)/render
RENDER_MK := $(ROOT)/src/native/render.mk
S2OV_CFG := $(ROOT)/src/native/render.cfg

# render.mk's MCOMMON / MPCOMMON then the whole frame's objects, in its
# link order (tests/test_m11_s2ovl.py checks them against ftest.map)
S2OV_F8 := rframe rbsp rlight auxlc far wclip wpsp gvalid-r \
           rwall rseg rsky rrec segloops \
           mmain-c mproj-c mfar-c msprite-c mvis-c mwall-c mpsp-c \
           rrec-m wpsp-m math-r rdriver-f bucket replay-r
S2OV_F8P := rframe-p rbsp-p rlight-p auxlc-p far-p wclip-p wpsp-p \
            gvalid-r-p rwall-p rseg-p rsky-p rrec-p segloops-p \
            mmain-p mproj-p mfar-p msprite-p mvis-p mwall-p mpsp-p \
            rrec-mp wpsp-m math-r rdriver-f bucket-p replay-r
S2OV_F8_OBJS := $(S2OV_F8:%=$(S2OV_R)/%.o)
S2OV_F8P_OBJS := $(S2OV_F8P:%=$(S2OV_R)/%.o)

.PHONY: s2ovl_render
s2ovl_render:
	@mkdir -p $(S2OV_R)
	@$(MAKE) -s -f $(RENDER_MK) OUT=$(S2OV_R) ROOT=$(ROOT) \
	    $(sort $(S2OV_F8_OBJS) $(S2OV_F8P_OBJS))
# the objects are render.mk's (s2ovl_render runs its make each time); the
# links below depend on the object files, which make reads again after
# that make, so they rerun only when render.mk rebuilt an object
$(sort $(S2OV_F8_OBJS) $(S2OV_F8P_OBJS)): s2ovl_render ;

$(S2OV_GEN)/s2amap.inc: $(TOOLS)/s2amap.py $(LAYOUTS)
	@mkdir -p $(S2OV_GEN)
	$(PYTHON) $(TOOLS)/s2amap.py --inc $@

# the overlay's places: s2_amline's W variables and its state block (in
# OVLW's run time part of MASKW's code room: s2_ovl.s)
S2OV_PLACES = -D AMW=39424 -D AMST=39680
S2OV_ASFLAGS = $(ASFLAGS) -I $(S2OV_GEN) $(S2OV_PLACES)
S2OV_INCS := $(M11_INCS) $(S2OV_GEN)/s2amap.inc s2_am.inc

$(S2OV_DIR)/s2_ovl.o: s2_ovl.s $(S2OV_INCS)
	@mkdir -p $(S2OV_DIR)
	$(CA65) $(S2OV_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2OV_DIR)/s2_amline-ovl.o: s2_amline.s $(S2OV_INCS)
	@mkdir -p $(S2OV_DIR)
	$(CA65) $(S2OV_ASFLAGS) -D AM_FASTLINE -o $@ -l $(@:.o=.lst) $<
$(S2OV_DIR)/s2_ovd.o: s2_ovd.s $(M11_INCS)
	@mkdir -p $(S2OV_DIR)
	$(CA65) $(ASFLAGS) -o $@ -l $(@:.o=.lst) $<

# the frame images: render.cfg (milestone 8's, read only)
$(S2OV_DIR)/ovf.map: $(S2OV_F8_OBJS) $(S2OV_DIR)/s2_ovd.o $(S2OV_CFG)
	$(LD65) -C $(S2OV_CFG) -o $(S2OV_DIR)/ovf -Ln $(S2OV_DIR)/ovf.lbl \
	    -m $(S2OV_DIR)/ovf.map $(S2OV_F8_OBJS) $(S2OV_DIR)/s2_ovd.o
$(S2OV_DIR)/ovfp.map: $(S2OV_F8P_OBJS) $(S2OV_DIR)/s2_ovd.o $(S2OV_CFG)
	$(LD65) -C $(S2OV_CFG) -o $(S2OV_DIR)/ovfp \
	    -Ln $(S2OV_DIR)/ovfp.lbl -m $(S2OV_DIR)/ovfp.map \
	    $(S2OV_F8P_OBJS) $(S2OV_DIR)/s2_ovd.o

# OVLW: its own link, the frame's symbols from the frame image's labels
S2OV_OVLW = $(S2OV_DIR)/s2_ovl.o $(S2OV_DIR)/s2_amline-ovl.o
# s2ovl.py --ovlw-cfg rewrites the map only when its text changes, so a
# stamp records the run: the map keeps its time (and OVLW is not linked
# again) when the frame was linked again with the same labels
$(S2OV_DIR)/ovlw.cfg.stamp: $(S2OV_DIR)/ovf.map $(TOOLS)/s2ovl.py
	$(PYTHON) $(TOOLS)/s2ovl.py --ovlw-cfg $(S2OV_DIR)/ovf.lbl \
	    $(S2OV_DIR)/ovlw.cfg
	@touch $@
$(S2OV_DIR)/ovlwp.cfg.stamp: $(S2OV_DIR)/ovfp.map $(TOOLS)/s2ovl.py
	$(PYTHON) $(TOOLS)/s2ovl.py --ovlw-cfg $(S2OV_DIR)/ovfp.lbl \
	    $(S2OV_DIR)/ovlwp.cfg
	@touch $@
$(S2OV_DIR)/ovlw.cfg: $(S2OV_DIR)/ovlw.cfg.stamp
	@test -f $@ || $(PYTHON) $(TOOLS)/s2ovl.py --ovlw-cfg \
	    $(S2OV_DIR)/ovf.lbl $@
$(S2OV_DIR)/ovlwp.cfg: $(S2OV_DIR)/ovlwp.cfg.stamp
	@test -f $@ || $(PYTHON) $(TOOLS)/s2ovl.py --ovlw-cfg \
	    $(S2OV_DIR)/ovfp.lbl $@
$(S2OV_DIR)/ovlw.map: $(S2OV_DIR)/ovlw.cfg $(S2OV_OVLW) \
                      $(S2OV_R)/rrec-m.o $(S2OV_R)/bucket.o
	$(LD65) -C $(S2OV_DIR)/ovlw.cfg -o $(S2OV_DIR)/ovlw \
	    -Ln $(S2OV_DIR)/ovlw.lbl -m $(S2OV_DIR)/ovlw.map \
	    $(S2OV_OVLW) $(S2OV_R)/rrec-m.o $(S2OV_R)/bucket.o
	$(PYTHON) $(S2LAYOUT) --check-map OVLW $(S2OV_DIR)/ovlw.map \
	    > $(S2OV_DIR)/ovlw.sizes || { cat $(S2OV_DIR)/ovlw.sizes; \
	    rm -f $(S2OV_DIR)/ovlw.map; exit 1; }
$(S2OV_DIR)/ovlwp.map: $(S2OV_DIR)/ovlwp.cfg $(S2OV_OVLW) \
                       $(S2OV_R)/rrec-mp.o $(S2OV_R)/bucket-p.o
	$(LD65) -C $(S2OV_DIR)/ovlwp.cfg -o $(S2OV_DIR)/ovlwp \
	    -Ln $(S2OV_DIR)/ovlwp.lbl -m $(S2OV_DIR)/ovlwp.map \
	    $(S2OV_OVLW) $(S2OV_R)/rrec-mp.o $(S2OV_R)/bucket-p.o

.PHONY: s2ovl_all
s2ovl_all: gen $(S2OV_DIR)/ovf.map $(S2OV_DIR)/ovlw.map \
           $(S2OV_DIR)/ovfp.map $(S2OV_DIR)/ovlwp.map

IMAGES += $(S2OV_DIR)/ovlw.map $(S2OV_DIR)/ovlwp.map
MAPS += OVLW:$(S2OV_DIR)/ovlw.map
PARTS += s2ovl
