# src/native/m11/s2pal.mk: part s2pal's builds (docs/SCREENS.md), read
# by src/native/m11.mk:
#
#   build/native/m11/s2pal/gen/s2pal.inc   tools/native/s2pal.py --inc: the
#                                    places s2_pal.s, s2_nib.s and s2_palw.s
#                                    need beyond s2.inc (the player's fields,
#                                    LVC's GSVIEWn; S2PAL's places, PS_TXTINV
#                                    and the zero page as stand-ins)
#   build/native/m11/s2pal/palw.*    the image PALW: s2_palw.s and s2_nib.s,
#                                    with MATHW, the far layer and the
#                                    driver s2_drv.s

S2PAL_DIR := $(M11)/s2pal
S2PAL_GEN := $(S2PAL_DIR)/gen
$(eval $(call M11_COMMON,$(S2PAL_DIR)))

$(S2PAL_GEN)/s2pal.inc: $(TOOLS)/s2pal.py $(LAYOUTS)
	@mkdir -p $(S2PAL_GEN)
	$(PYTHON) $(TOOLS)/s2pal.py --inc $@

S2PAL_ASFLAGS = $(ASFLAGS) -I $(S2PAL_GEN)
S2PAL_INCS := $(M11_INCS) $(S2PAL_GEN)/s2pal.inc

$(S2PAL_DIR)/s2_nib.o: s2_nib.s $(S2PAL_INCS)
	$(CA65) $(S2PAL_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2PAL_DIR)/s2_palw.o: s2_palw.s $(S2PAL_INCS)
	$(CA65) $(S2PAL_ASFLAGS) -o $@ -l $(@:.o=.lst) $<

S2PAL_COMMON := $(S2PAL_DIR)/s2_drv.o $(M11_COMMON_OBJS:%=$(S2PAL_DIR)/%)
$(eval $(call M11_IMAGE,$(S2PAL_DIR),palw,PALW,\
    $(S2PAL_DIR)/s2_palw.o $(S2PAL_DIR)/s2_nib.o $(S2PAL_COMMON)))

.PHONY: s2pal_all
s2pal_all: gen $(S2PAL_DIR)/palw.map

PARTS += s2pal
