# src/native/m11/s2stbar.mk: part s2stbar's builds (docs/SCREENS.md 7.3,
# docs/m11-parts/s2stbar.md), read by src/native/m11.mk:
#
#   build/native/m11/s2stbar/gen/s2stbar.inc  tools/native/s2stbar.py
#                                    --inc: the player's fields, the menu,
#                                    weaponinfo's ammo types, and the
#                                    stand-ins of the part's requests
#   build/native/m11/s2stbar/s2sb.*  the drawer's test image in P2DW's
#                                    room: s2_st.s (st_drawer, s2_rows),
#                                    part s2draw's s2_draw.s and s2_pub.s,
#                                    part s2pal's s2_pal.s (s2_begin: the
#                                    palettes and SCBs are s2pal's region;
#                                    until the final integration the
#                                    stand-in s2_beginstub.s), the glue
#                                    s2_stt.s,
#                                    with MATHW, the far layer and the test
#                                    driver
#   build/native/m11/s2stbar/s2st.*  the tic side's test image: s2t_st.s
#                                    (st_ticker, st_start, st_init), the
#                                    glue s2t_stt.s, the game's math (pta3:
#                                    math.s without RENDER, as the math
#                                    test builds it), linked with the map
#                                    s2stbar.py --cfg-tic writes (W
#                                    $6000-$6FFF for that math, the module
#                                    from $7000); s2st.sizes its module's
#                                    bytes against the 900 B budget
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
$(S2STBAR_GEN)/s2pal.inc: $(TOOLS)/s2pal.py $(TOOLS)/s2palmodel.py $(LAYOUTS)
	@mkdir -p $(S2STBAR_GEN)
	$(PYTHON) $(TOOLS)/s2pal.py --inc $@
$(S2STBAR_DIR)/s2_pal.o: s2_pal.s $(M11_INCS) $(S2STBAR_GEN)/s2pal.inc
	$(CA65) $(S2STBAR_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2STBAR_DIR)/s2t_st.o: s2t_st.s $(S2STBAR_INCS)
	$(CA65) $(S2STBAR_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2STBAR_DIR)/s2t_stt.o: s2t_stt.s $(S2STBAR_INCS)
	$(CA65) $(S2STBAR_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2STBAR_DIR)/math-g.o: math.s $(ROOT)/src/native/math.inc \
                         $(TABLES)/math/squares.bin
	@mkdir -p $(S2STBAR_DIR)
	$(CA65) $(ASFLAGS) -o $@ -l $(@:.o=.lst) $<

S2STBAR_COMMON := $(S2STBAR_DIR)/s2_drv.o \
                  $(M11_COMMON_OBJS:%=$(S2STBAR_DIR)/%)
$(eval $(call M11_IMAGE,$(S2STBAR_DIR),s2sb,P2DW,\
    $(S2STBAR_DIR)/s2_stt.o $(S2STBAR_DIR)/s2_st.o \
    $(S2STBAR_DIR)/s2_draw.o $(S2STBAR_DIR)/s2_pub.o \
    $(S2STBAR_DIR)/s2_pal.o $(S2STBAR_COMMON)))

S2STBAR_TIC := $(S2STBAR_DIR)/s2t_stt.o $(S2STBAR_DIR)/s2t_st.o \
               $(S2STBAR_DIR)/math-g.o $(S2STBAR_DIR)/auxlc.o \
               $(S2STBAR_DIR)/far.o $(S2STBAR_DIR)/s2_drv.o
$(S2STBAR_DIR)/s2st.cfg: $(TOOLS)/s2stbar.py $(LAYOUTS)
	@mkdir -p $(S2STBAR_DIR)
	$(PYTHON) $(TOOLS)/s2stbar.py --cfg-tic $@
$(S2STBAR_DIR)/s2st.map: $(S2STBAR_TIC) $(S2STBAR_DIR)/s2st.cfg
	$(LD65) -C $(S2STBAR_DIR)/s2st.cfg -o $(S2STBAR_DIR)/s2st \
	    -Ln $(S2STBAR_DIR)/s2st.lbl -m $(S2STBAR_DIR)/s2st.map $(S2STBAR_TIC)
	$(PYTHON) $(TOOLS)/s2stbar.py --check-tic-map $(S2STBAR_DIR)/s2st.map \
	    > $(S2STBAR_DIR)/s2st.sizes \
	    || { cat $(S2STBAR_DIR)/s2st.sizes; rm -f $(S2STBAR_DIR)/s2st.map; \
	         exit 1; }

.PHONY: s2stbar_all
s2stbar_all: gen $(S2STBAR_DIR)/s2sb.map $(S2STBAR_DIR)/s2st.map

PARTS += s2stbar
