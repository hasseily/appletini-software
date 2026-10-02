# src/native/m11/s2int.mk: the integration's builds of milestone 11's
# first half (docs/SCREENS.md 4.1, 8.13), read by src/native/m11.mk:
#
#   build/native/m11/s2int/p2dwl.*   P2DW linked from every object of 4.1's
#                                    P2DW column (s2_st, s2_hu, s2_draw,
#                                    s2_pub, s2_pal, pl_poll, fx_service)
#                                    and the link's glue s2_p2dwl.s (P2DW's
#                                    places, the frame's entries; the frame
#                                    glue s2_frame is the second half's,
#                                    design.md R7), so p2dwl.sizes is 4.1's
#                                    P2DW row as the release will link it.
#                                    A link only: each object's checkpoint
#                                    is its part's.
#
# Every object is assembled here from the parts' sources with this half's
# test s2.inc, the parts' generators writing their includes into gen/;
# part s2data's s2data.inc and s2data.json and S2's build/sound65 must
# exist (make -f m11.mk part P=s2data; make -C src/sound).

S2INT_DIR := $(M11)/s2int
S2INT_GEN := $(S2INT_DIR)/gen
S2INT_DATA := $(M11)/s2data
SOUND65 ?= $(ROOT)/build/sound65
$(eval $(call M11_COMMON,$(S2INT_DIR)))

ifndef M11_SOUND65_RULES
M11_SOUND65_RULES := 1
$(SOUND65)/%.o:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
$(SOUND65)/tables.inc:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
endif

$(S2INT_GEN)/s2stbar.inc: $(TOOLS)/s2stbar.py $(TOOLS)/s2stmodel.py \
                          $(LAYOUTS) $(S2INT_DATA)/s2data.json
	@mkdir -p $(S2INT_GEN)
	$(PYTHON) $(TOOLS)/s2stbar.py --inc $@
$(S2INT_GEN)/s2hud.inc: $(TOOLS)/s2msgs.py $(LAYOUTS)
	@mkdir -p $(S2INT_GEN)
	$(PYTHON) $(TOOLS)/s2msgs.py --hud-inc $@
$(S2INT_GEN)/s2msgs.inc: $(TOOLS)/s2msgs.py $(LAYOUTS) \
                         $(S2INT_DATA)/s2data.json
	@mkdir -p $(S2INT_GEN)
	$(PYTHON) $(TOOLS)/s2msgs.py --inc $@
$(S2INT_GEN)/s2pal.inc: $(TOOLS)/s2pal.py $(TOOLS)/s2palmodel.py $(LAYOUTS)
	@mkdir -p $(S2INT_GEN)
	$(PYTHON) $(TOOLS)/s2pal.py --inc $@

S2INT_ASFLAGS = $(ASFLAGS) -I $(S2INT_GEN) -I $(S2INT_DATA)

$(S2INT_DIR)/s2_st.o: s2_st.s $(M11_INCS) $(S2INT_GEN)/s2stbar.inc \
                      $(S2INT_DATA)/s2data.inc
	$(CA65) $(S2INT_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2INT_DIR)/s2_hu.o: s2_hu.s $(M11_INCS) $(S2INT_GEN)/s2hud.inc \
                      $(S2INT_GEN)/s2msgs.inc
	$(CA65) $(S2INT_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2INT_DIR)/s2_pal.o: s2_pal.s $(M11_INCS) $(S2INT_GEN)/s2pal.inc
	$(CA65) $(S2INT_ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(S2INT_DIR)/pl_input.o: pl_input.inc
$(S2INT_DIR)/fx.o: $(ROOT)/src/sound/fx.s $(M11_INCS) $(SOUND65)/tables.inc
	$(CA65) $(ASFLAGS) -I $(SOUND65) -D FX_SERVICE -o $@ -l $(@:.o=.lst) $<
$(S2INT_DIR)/fx-card.o: $(ROOT)/src/sound/fx.s $(M11_INCS) \
                        $(SOUND65)/tables.inc
	$(CA65) $(ASFLAGS) -I $(SOUND65) -o $@ -l $(@:.o=.lst) $<

# (the card's FXCODE as the release links it: fx.s's card part first,
# then pl_irq.s; request PLBOOT-4)
S2INT_P2DW_OBJS := $(S2INT_DIR)/s2_p2dwl.o $(S2INT_DIR)/s2_st.o \
                   $(S2INT_DIR)/s2_hu.o $(S2INT_DIR)/s2_draw.o \
                   $(S2INT_DIR)/s2_pub.o $(S2INT_DIR)/s2_pal.o \
                   $(S2INT_DIR)/pl_input.o $(S2INT_DIR)/fx.o \
                   $(S2INT_DIR)/s2_drv-pl.o $(S2INT_DIR)/fx-card.o \
                   $(S2INT_DIR)/pl_irq.o $(SOUND65)/player.o \
                   $(M11_COMMON_OBJS:%=$(S2INT_DIR)/%)
$(eval $(call M11_IMAGE,$(S2INT_DIR),p2dwl,P2DW,$(S2INT_P2DW_OBJS)))

.PHONY: s2int_all
s2int_all: gen $(S2INT_DIR)/p2dwl.map

PARTS += s2int
