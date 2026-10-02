# src/native/m11/plclock.mk: part plclock of milestone 11 (docs/SCREENS.md
# 2.2, 2.3, 7.3; docs/m11-parts/plclock.md): the IRQ entry pl_vbl, the
# clock, pl_time, the PAL/NTSC detection (src/native/pl_irq.s), the aux
# card's bridge (pl_bridge.s), with part fxplay's effect player in the card
# (src/sound/fx.s as fx-card.o: fx_step and fx_burst in pl_vbl; until the
# final integration a stand-in pl_fxstub.s did nothing there). Read by
# src/native/m11.mk (make -f m11.mk part P=plclock).
#
#   build/native/m11/plclock/plct.*         the clock's test image in P2DW's
#                                           room under the test driver s2_drv
#                                           with pl_vbl its handler (-D PL_VBL),
#                                           S2's player in the card (pl_ct.s:
#                                           plt_clock, plt_mode)
#   build/native/m11/plclock/music/sound.*  S2's test driver, player and probe
#                                           (build/sound65/*.o, read only)
#                                           with pl_vbl in place of S2's
#                                           snd_vbl, at the game's places
#                                           (sound.main at $0800, sound.lc
#                                           from $E900)
#   build/native/m11/plclock/bridge/plbr.*  the bridge's synthetic machine:
#                                           pl_bt.s at $0800, the main card
#                                           (S2's player, fx.s's card
#                                           part, pl_irq.s, the bridge at
#                                           $FF00),
#                                           the aux card's vectors
#                                           (plbr.auxvec)
#
# The two ld65 maps of music/ and bridge/ come from tools/native/plclock.py
# --cfg (s2layout.py's places). S2's objects are made by src/sound/Makefile
# (make -C src/sound); this file never rebuilds them.

PLCLOCK_DIR := $(M11)/plclock
SOUND65 ?= $(ROOT)/build/sound65
PLCLOCK_TOOL := $(TOOLS)/plclock.py
PLCLOCK_S2 := $(SOUND65)/player.o

$(eval $(call M11_COMMON,$(PLCLOCK_DIR)))

# S2's objects, read only (the same guarded rules in fxplay.mk and
# fxchan.mk)
ifndef M11_SOUND65_RULES
M11_SOUND65_RULES := 1
$(SOUND65)/%.o:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
$(SOUND65)/tables.inc:
	@echo "no $@: run make -C src/sound (S2's player)" >&2
	@exit 1
endif

# the card's interrupt code as the release links it (FXCODE: fx.s's card
# part first, then pl_irq.s: request PLBOOT-4), fx.s assembled with this
# half's test s2.inc (its mailboxes at SC_BASE)
$(PLCLOCK_DIR)/fx-card.o: $(ROOT)/src/sound/fx.s $(M11_INCS) \
                          $(SOUND65)/tables.inc
	@mkdir -p $(PLCLOCK_DIR)
	$(CA65) $(ASFLAGS) -I $(SOUND65) -o $@ -l $(@:.o=.lst) $<
PLCLOCK_IRQ := $(PLCLOCK_DIR)/fx-card.o $(PLCLOCK_DIR)/pl_irq.o

# the clock's test image
PLCLOCK_CT_OBJS := $(PLCLOCK_DIR)/pl_ct.o $(PLCLOCK_DIR)/s2_drv-pl.o \
                   $(PLCLOCK_IRQ) $(PLCLOCK_S2) \
                   $(M11_COMMON_OBJS:%=$(PLCLOCK_DIR)/%)
$(eval $(call M11_IMAGE,$(PLCLOCK_DIR),plct,P2DW,$(PLCLOCK_CT_OBJS)))

# the music's image: S2's driver.o, player.o, probe.o with pl_vbl
PLCLOCK_MUSIC := $(PLCLOCK_DIR)/music
PLCLOCK_MUSIC_OBJS := $(SOUND65)/driver.o $(SOUND65)/player.o \
                      $(SOUND65)/probe.o $(PLCLOCK_IRQ)

$(PLCLOCK_MUSIC)/sound.cfg: $(PLCLOCK_TOOL) $(LAYOUTS)
	@mkdir -p $(PLCLOCK_MUSIC)
	$(PYTHON) $(PLCLOCK_TOOL) --cfg music $@

$(PLCLOCK_MUSIC)/sound.map: $(PLCLOCK_MUSIC_OBJS) $(PLCLOCK_MUSIC)/sound.cfg
	$(LD65) -C $(PLCLOCK_MUSIC)/sound.cfg -o $(PLCLOCK_MUSIC)/sound \
	    -Ln $(PLCLOCK_MUSIC)/sound.lbl -m $@ $(PLCLOCK_MUSIC_OBJS)

# the bridge's synthetic machine
PLCLOCK_BRIDGE := $(PLCLOCK_DIR)/bridge
PLCLOCK_BRIDGE_OBJS := $(PLCLOCK_DIR)/pl_bt.o $(PLCLOCK_DIR)/pl_bridge.o \
                       $(PLCLOCK_IRQ) $(PLCLOCK_S2)

$(PLCLOCK_BRIDGE)/plbr.cfg: $(PLCLOCK_TOOL) $(LAYOUTS)
	@mkdir -p $(PLCLOCK_BRIDGE)
	$(PYTHON) $(PLCLOCK_TOOL) --cfg bridge $@

$(PLCLOCK_BRIDGE)/plbr.map: $(PLCLOCK_BRIDGE_OBJS) $(PLCLOCK_BRIDGE)/plbr.cfg
	$(LD65) -C $(PLCLOCK_BRIDGE)/plbr.cfg -o $(PLCLOCK_BRIDGE)/plbr \
	    -Ln $(PLCLOCK_BRIDGE)/plbr.lbl -m $@ $(PLCLOCK_BRIDGE_OBJS)

.PHONY: plclock_all
plclock_all: gen $(PLCLOCK_DIR)/plct.map $(PLCLOCK_MUSIC)/sound.map \
             $(PLCLOCK_BRIDGE)/plbr.map

PARTS += plclock
