# src/native/m11/fxplay.mk: part fxplay of milestone 11 (docs/SCREENS.md
# 2.3, 3, 4.4, 7.3; tools/sound/README.md "Effects (S4)"; docs/m11-parts/
# fxplay.md): the effect player src/sound/fx.s and its test machine. Read
# by src/native/m11.mk (make -f m11.mk part P=fxplay).
#
#   build/native/m11/fxplay/fx-card.o   fx.s's card part (FXCODE: fx_step,
#                                       fx_burst, fx_song, fx_init,
#                                       fx_stopall, fx_isplaying, fx_copy)
#   build/native/m11/fxplay/fx.o        fx.s's frame side (-D FX_SERVICE,
#                                       S2CODE: fx_service; the size
#                                       table's module "fx")
#   build/native/m11/fxplay/fxt.*       the test machine: src/sound/
#                                       fxdrv.s and fx_service in main
#                                       memory at $0800, S2's player
#                                       (build/sound65, read only),
#                                       pl_irq.s and the card part at the
#                                       game's places (fxt.lc from $E900)
#   build/native/m11/fxplay/fxpt.*      fx_service and the card part
#                                       linked in P2DW's room under the
#                                       test driver s2_drv (the size
#                                       table's fx_service row, FXC's room)
#
# fxt.cfg comes from tools/sound/fxrun65.py --cfg (s2layout.py's places).
# S2's objects are made by src/sound/Makefile (make -C src/sound); this
# file never rebuilds them. FXSRC can name a copy of src/sound's fx.s and
# fxdrv.s (the planted bugs of tests/test_m11_fxplay.py).

FXPLAY_DIR := $(M11)/fxplay
SOUND65 ?= $(ROOT)/build/sound65
FXSRC ?= $(ROOT)/src/sound
FXPLAY_TOOL := $(ROOT)/tools/sound/fxrun65.py
FXPLAY_ASFLAGS = $(ASFLAGS) -I $(SOUND65)
FXPLAY_INCS := $(M11_INCS) $(SOUND65)/tables.inc

$(eval $(call M11_COMMON,$(FXPLAY_DIR)))

# S2's objects, read only (the same guarded rules in fxplay.mk and
# fxchan.mk: each part builds alone, and m11.mk's all includes both)
ifndef M11_SOUND65_RULES
M11_SOUND65_RULES := 1
$(SOUND65)/%.o:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
$(SOUND65)/tables.inc:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
endif

$(FXPLAY_DIR)/fx-card.o: $(FXSRC)/fx.s $(FXPLAY_INCS)
	@mkdir -p $(FXPLAY_DIR)
	$(CA65) $(FXPLAY_ASFLAGS) -o $@ -l $(@:.o=.lst) $<

$(FXPLAY_DIR)/fx.o: $(FXSRC)/fx.s $(FXPLAY_INCS)
	@mkdir -p $(FXPLAY_DIR)
	$(CA65) $(FXPLAY_ASFLAGS) -D FX_SERVICE -o $@ -l $(@:.o=.lst) $<

$(FXPLAY_DIR)/fxdrv.o: $(FXSRC)/fxdrv.s $(M11_INCS)
	@mkdir -p $(FXPLAY_DIR)
	$(CA65) $(FXPLAY_ASFLAGS) -o $@ -l $(@:.o=.lst) $<

FXPLAY_FX := $(FXPLAY_DIR)/fx-card.o $(FXPLAY_DIR)/fx.o

# the test machine: S2's player and probe, pl_vbl, the effects, the driver
FXPLAY_T_OBJS := $(FXPLAY_DIR)/fxdrv.o $(FXPLAY_FX) $(FXPLAY_DIR)/pl_irq.o \
                 $(SOUND65)/player.o $(SOUND65)/probe.o

$(FXPLAY_DIR)/fxt.cfg: $(FXPLAY_TOOL) $(LAYOUTS)
	@mkdir -p $(FXPLAY_DIR)
	$(PYTHON) $(FXPLAY_TOOL) --cfg $@

$(FXPLAY_DIR)/fxt.map: $(FXPLAY_T_OBJS) $(FXPLAY_DIR)/fxt.cfg
	$(LD65) -C $(FXPLAY_DIR)/fxt.cfg -o $(FXPLAY_DIR)/fxt \
	    -Ln $(FXPLAY_DIR)/fxt.lbl -m $@ $(FXPLAY_T_OBJS)

# fx_service in a frame image's room (P2DW), the card part in FXC
FXPLAY_PT_OBJS := $(FXPLAY_DIR)/s2_drv-pl.o $(FXPLAY_DIR)/pl_irq.o \
                  $(FXPLAY_FX) $(SOUND65)/player.o \
                  $(M11_COMMON_OBJS:%=$(FXPLAY_DIR)/%)
$(eval $(call M11_IMAGE,$(FXPLAY_DIR),fxpt,P2DW,$(FXPLAY_PT_OBJS)))

.PHONY: fxplay_all
fxplay_all: gen $(FXPLAY_DIR)/fxt.map $(FXPLAY_DIR)/fxpt.map

PARTS += fxplay
