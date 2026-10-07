# src/native/m11/s2stbar.mk: part s2stbar's builds (docs/SCREENS.md),
# read by src/native/m11.mk:
#
#   build/native/m11/s2stbar/gen/s2stbar.inc  tools/native/s2stbar.py
#                                    --inc: the player's fields, the menu,
#                                    weaponinfo's ammo types, and the
#                                    stand-ins the part needs
#   build/native/m11/s2stbar/s2sb.*  the drawer's image in P2DW's room:
#                                    s2_st.s (st_drawer, s2_rows), the
#                                    drawers s2_draw.s and s2_pub.s, part
#                                    s2pal's s2_pal.s (s2_begin: the
#                                    palettes and SCBs are s2pal's region),
#                                    the glue s2_stt.s, with MATHW, the far
#                                    layer and the driver s2_drv.s
#
# The 2D store's include (part s2data's build/native/m11/s2data/
# s2data.inc: the glyphs' handles, GFXDIR) must exist: make -f m11.mk part
# P=s2data, or python3 tools/native/s2data.py.

S2STBAR_DIR := $(M11)/s2stbar
S2STBAR_GEN := $(S2STBAR_DIR)/gen
S2STBAR_DATA := $(M11)/s2data
$(eval $(call M11_COMMON,$(S2STBAR_DIR)))

$(S2STBAR_GEN)/s2stbar.inc: $(TOOLS)/s2stbar.py $(TOOLS)/s2stmodel.py \
                            $(LAYOUTS) $(S2STBAR_DATA)/s2data.json
	@mkdir -p $(S2STBAR_GEN)
	$(PYTHON) $(TOOLS)/s2stbar.py --inc $@

S2STBAR_ASFLAGS = $(ASFLAGS) -I $(S2STBAR_GEN) -I $(S2STBAR_DATA)
S2STBAR_INCS := $(M11_INCS) $(S2STBAR_GEN)/s2stbar.inc \
                $(S2STBAR_DATA)/s2data.inc

$(S2STBAR_DIR)/s2_st.o: s2_st.s $(S2STBAR_INCS)
	$(CA65) $(S2STBAR_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2STBAR_DIR)/s2_stt.o: s2_stt.s $(S2STBAR_INCS)
	$(CA65) $(S2STBAR_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2STBAR_GEN)/s2pal.inc: $(TOOLS)/s2pal.py $(LAYOUTS)
	@mkdir -p $(S2STBAR_GEN)
	$(PYTHON) $(TOOLS)/s2pal.py --inc $@
$(S2STBAR_DIR)/s2_pal.o: s2_pal.s $(M11_INCS) $(S2STBAR_GEN)/s2pal.inc
	$(CA65) $(S2STBAR_ASFLAGS) -o $@ -l $(@:.o=.lst) $<

S2STBAR_COMMON := $(S2STBAR_DIR)/s2_drv.o \
                  $(M11_COMMON_OBJS:%=$(S2STBAR_DIR)/%)
$(eval $(call M11_IMAGE,$(S2STBAR_DIR),s2sb,P2DW,\
    $(S2STBAR_DIR)/s2_stt.o $(S2STBAR_DIR)/s2_st.o \
    $(S2STBAR_DIR)/s2_draw.o $(S2STBAR_DIR)/s2_pub.o \
    $(S2STBAR_DIR)/s2_pal.o $(S2STBAR_COMMON)))

.PHONY: s2stbar_all
s2stbar_all: gen $(S2STBAR_DIR)/s2sb.map

PARTS += s2stbar
