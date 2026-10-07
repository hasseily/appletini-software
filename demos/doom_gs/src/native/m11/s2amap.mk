# src/native/m11/s2amap.mk: part s2amap's builds (docs/SCREENS.md, the
# automap), read by src/native/m11.mk (make -f m11.mk part P=s2amap):
#
#   build/native/m11/s2amap/gen/s2amap.inc   tools/native/s2amap.py --inc:
#                                    the game's places the automap reads
#                                    (the game's, read only), the
#                                    release's keys, arrow and door
#                                    colours
#   build/native/m11/s2amap/amw.*    the image AMAPW as the game links it:
#                                    s2_am.s, s2_amline.s and the publish
#                                    s2_pub.s alone (the size table: no
#                                    pl_poll, no fx_service), with the
#                                    driver s2_drv.s

S2AM_DIR := $(M11)/s2amap
S2AM_GEN := $(S2AM_DIR)/gen
$(eval $(call M11_COMMON,$(S2AM_DIR)))

$(S2AM_GEN)/s2amap.inc: $(TOOLS)/s2amap.py $(LAYOUTS)
	@mkdir -p $(S2AM_GEN)
	$(PYTHON) $(TOOLS)/s2amap.py --inc $@

S2AM_ASFLAGS = $(ASFLAGS) -I $(S2AM_GEN)
S2AM_INCS := $(M11_INCS) $(S2AM_GEN)/s2amap.inc s2_am.inc

$(S2AM_DIR)/s2_am.o: s2_am.s $(S2AM_INCS)
	@mkdir -p $(S2AM_DIR)
	$(CA65) $(S2AM_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2AM_DIR)/s2_amline.o: s2_amline.s $(S2AM_INCS)
	@mkdir -p $(S2AM_DIR)
	$(CA65) $(S2AM_ASFLAGS) -o $@ -l $(@:.o=.lst) $<

S2AM_IMAGE := $(S2AM_DIR)/s2_am.o $(S2AM_DIR)/s2_amline.o \
              $(S2AM_DIR)/s2_pub.o
S2AM_DRV := $(S2AM_DIR)/s2_drv.o $(M11_COMMON_OBJS:%=$(S2AM_DIR)/%)
$(eval $(call M11_IMAGE,$(S2AM_DIR),amw,AMAPW,\
    $(S2AM_IMAGE) $(S2AM_DRV)))

.PHONY: s2amap_all
s2amap_all: gen $(S2AM_DIR)/amw.map

PARTS += s2amap
