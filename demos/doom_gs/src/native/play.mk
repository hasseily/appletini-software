# src/native/play.mk: the playable game's links (docs/PLAY.md), assembled
# with ca65 and linked with ld65 (cc65 2.18): the glue's images and the
# tic image with every built part, from the sources; the other images read
# from their own builds (render.mk's rcard, m11.mk's 2D images: read
# only). The load image (level.mk's lcard, LCODE on the disk) links the runtime's state, so a layout change moves it: every run of
# this makefile first runs level.mk on LEVELS (build/native/levels/obj,
# where playlink.py and playdisk.py read it), which rebuilds it when it is
# out of date and writes nothing when it is not.
#
#   make -f play.mk ROOT=$PWD             every link (all)
#   make -f play.mk ROOT=$PWD PLAY=DIR    the same into another directory
#   make -f play.mk sizes                 each link's segments against room
#   make -f play.mk lcode                 the load image alone (level.mk)
#   make -f play.mk clean                 PLAY's directory
#
# Into PLAY (build/native/play):
#   gen/     play.inc (playlayout.py), s2.inc (s2layout's release),
#            rlayout.inc, llayout.inc, lgame.inc, the 2D modules' includes
#            (their tools' --inc), fxchan.inc; playsym.inc, playsym2.inc,
#            playimg.inc, playk.inc (playlink.py, from the links)
#   tic/     glayout.py's gen and game.cfg; play.cfg (game.cfg with the
#            glue's groups: playlink.py --tic-cfg); the tic image tic.*
#   p2dw/    P2DW with the frame glue dl_p2d.s (p2dw.*)
#   init/    DLINIT (init.*)
#   card/    DOOM.SYSTEM and the card's code with the kernel at $FF00 in
#            pl_ready's place, its menu loop at main $0880 and $0B94
#            (plboot.*: .boot, .snd, .fxc, .plat, .vec, .k08, .k0b)
#
# The parts of the tic image are the integrated waves'
# (src/native/game/integrated.txt), as glayout.py's built set: a part a
# builder is working on is never linked half-built. tools/native/
# playdisk.py makes build/native/DOOM.hdv from these links.

HERE := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
ROOT ?= $(abspath $(HERE)../..)
PLAY ?= $(ROOT)/build/native/play
GEN := $(PLAY)/gen
TIC := $(PLAY)/tic
P2D := $(PLAY)/p2dw
INIT := $(PLAY)/init
CARD := $(PLAY)/card
M11 ?= $(ROOT)/build/native/m11
# level.mk's build (playlink.py and playdisk.py read lrun.OBJ, this
# directory)
LEVELS := $(ROOT)/build/native/levels/obj
TABLES ?= $(ROOT)/build/native/render/tables
SOUND65 ?= $(ROOT)/build/sound65
TOOLS := $(ROOT)/tools/native
LINK := $(TOOLS)/playlink.py
PYTHON = python3
CA65 = ca65
LD65 = ld65

vpath %.s $(HERE) $(ROOT)/src/native
vpath %.inc $(HERE) $(ROOT)/src/native

ASFLAGS = --cpu 65C02 -g -I $(GEN) -I $(HERE) -I $(ROOT)/src/native \
          --bin-include-dir $(TABLES) --bin-include-dir $(TABLES)/math
TICFLAGS = $(ASFLAGS) -I $(TIC)/gen -D PLAY_TIC
S2FLAGS = $(ASFLAGS) -I $(M11)/s2data -I $(SOUND65)

.PHONY: all gen p2dw init tic card lcode sizes clean FORCE
all: card

# ---------------------------------------------------------------------------
# The load image: level.mk's own rules decide whether it is out of date,
# and the links that read its symbols follow lcard.lw's time
# ---------------------------------------------------------------------------
$(LEVELS)/lcard.lw: FORCE
	$(MAKE) -s -C $(HERE) -f level.mk ROOT=$(ROOT) OUT=$(LEVELS)
lcode: $(LEVELS)/lcard.lw
FORCE:

# ---------------------------------------------------------------------------
# The includes
# ---------------------------------------------------------------------------
LAYOUTS := $(TOOLS)/playlayout.py $(TOOLS)/s2layout.py $(TOOLS)/rlayout.py \
           $(TOOLS)/llayout.py $(TOOLS)/glayout.py $(TOOLS)/layout.py
INCS := $(GEN)/play.inc $(GEN)/s2.inc $(GEN)/rlayout.inc $(GEN)/llayout.inc \
        $(GEN)/lgame.inc $(HERE)math.inc
S2INCS := $(GEN)/s2stbar.inc $(GEN)/s2hud.inc $(GEN)/s2msgs.inc \
          $(GEN)/s2pal.inc $(GEN)/fxchan.inc $(GEN)/s2fin.inc

$(GEN)/play.inc: $(TOOLS)/playlayout.py
	@mkdir -p $(GEN)
	$(PYTHON) $(TOOLS)/playlayout.py --inc $@
$(GEN)/s2.inc: $(LAYOUTS)
	@mkdir -p $(GEN)
	$(PYTHON) $(TOOLS)/s2layout.py --inc --build release $@
$(GEN)/rlayout.inc: $(TOOLS)/rlayout.py
	@mkdir -p $(GEN)
	$(PYTHON) $(TOOLS)/rlayout.py $@
$(GEN)/llayout.inc: $(TOOLS)/llayout.py
	@mkdir -p $(GEN)
	$(PYTHON) $(TOOLS)/llayout.py $@
$(GEN)/lgame.inc: $(TOOLS)/llayout.py
	@mkdir -p $(GEN)
	$(PYTHON) $(TOOLS)/llayout.py --game $@
$(GEN)/s2stbar.inc: $(TOOLS)/s2stbar.py $(LAYOUTS) $(M11)/s2data/s2data.json
	@mkdir -p $(GEN)
	$(PYTHON) $(TOOLS)/s2stbar.py --inc $@
$(GEN)/s2hud.inc: $(TOOLS)/s2msgs.py $(LAYOUTS)
	@mkdir -p $(GEN)
	$(PYTHON) $(TOOLS)/s2msgs.py --hud-inc $@
$(GEN)/s2msgs.inc: $(TOOLS)/s2msgs.py $(LAYOUTS) $(M11)/s2data/s2data.json
	@mkdir -p $(GEN)
	$(PYTHON) $(TOOLS)/s2msgs.py --inc $@
$(GEN)/s2pal.inc: $(TOOLS)/s2pal.py $(LAYOUTS)
	@mkdir -p $(GEN)
	$(PYTHON) $(TOOLS)/s2pal.py --inc $@
$(GEN)/fxchan.inc: $(ROOT)/tools/sound/fxchan.py $(LAYOUTS)
	@mkdir -p $(GEN)
	$(PYTHON) $(ROOT)/tools/sound/fxchan.py --inc $@
$(GEN)/s2fin.inc: $(TOOLS)/s2fin.py $(M11)/s2data/s2data.json
	@mkdir -p $(GEN)
	$(PYTHON) $(TOOLS)/s2fin.py --inc $@
# the other makefiles' links' entries (rcard, lcard, the 2D images, the
# card's player and platform): read only
$(GEN)/playsym.inc: $(LINK) $(INCS) $(LEVELS)/lcard.lw
	$(PYTHON) $(LINK) --symbols $@
gen: $(INCS) $(S2INCS) $(GEN)/playsym.inc

# ---------------------------------------------------------------------------
# P2DW with the frame glue dl_p2d.s and the 2D modules' objects
# ---------------------------------------------------------------------------
P2D_OBJS := $(addprefix $(P2D)/,dl_p2d.o s2_st.o s2_hu.o s2_draw.o \
            s2_pub.o s2_pal.o pl_input.o fx.o fx-card.o pl_irq.o far.o \
            math-r.o auxlc.o) $(SOUND65)/player.o
$(P2D)/fx.o: $(ROOT)/src/sound/fx.s $(INCS) $(SOUND65)/tables.inc
	@mkdir -p $(P2D)
	$(CA65) $(S2FLAGS) -D FX_SERVICE -o $@ -l $(@:.o=.lst) $<
$(P2D)/fx-card.o: $(ROOT)/src/sound/fx.s $(INCS) $(SOUND65)/tables.inc
	@mkdir -p $(P2D)
	$(CA65) $(S2FLAGS) -o $@ -l $(@:.o=.lst) $<
$(P2D)/math-r.o: math.s $(INCS)
	@mkdir -p $(P2D)
	$(CA65) $(ASFLAGS) -D RENDER -o $@ -l $(@:.o=.lst) $<
$(P2D)/%.o: %.s $(INCS) $(S2INCS)
	@mkdir -p $(P2D)
	$(CA65) $(S2FLAGS) -o $@ -l $(@:.o=.lst) $<
$(P2D)/p2dw.cfg: $(LINK) $(LAYOUTS)
	@mkdir -p $(P2D)
	$(PYTHON) $(LINK) --image-cfg P2DW $@
$(P2D)/p2dw.map: $(P2D_OBJS) $(P2D)/p2dw.cfg
	$(LD65) -C $(P2D)/p2dw.cfg -o $(P2D)/p2dw -Ln $(P2D)/p2dw.lbl -m $@ \
	    $(P2D_OBJS)
	$(PYTHON) $(TOOLS)/s2layout.py --check-map P2DW $@ > $(P2D)/p2dw.sizes \
	    || { cat $(P2D)/p2dw.sizes; rm -f $@; exit 1; }
p2dw: $(P2D)/p2dw.map

# ---------------------------------------------------------------------------
# DLINIT
# ---------------------------------------------------------------------------
$(INIT)/dl_init.o: dl_init.s $(INCS) $(GEN)/playsym.inc
	@mkdir -p $(INIT)
	$(CA65) $(ASFLAGS) -o $@ -l $(@:.o=.lst) $<
$(INIT)/init.cfg: $(LINK) $(TOOLS)/playlayout.py
	@mkdir -p $(INIT)
	$(PYTHON) $(LINK) --init-cfg $@
$(INIT)/init.map: $(INIT)/dl_init.o $(INIT)/init.cfg
	$(LD65) -C $(INIT)/init.cfg -o $(INIT)/init -Ln $(INIT)/init.lbl -m $@ \
	    $(INIT)/dl_init.o
init: $(INIT)/init.map

# the glue's images' entries and the images' page runs, for the tic image
$(GEN)/playsym2.inc $(GEN)/playimg.inc: $(LINK) $(P2D)/p2dw.map \
        $(INIT)/init.map $(GEN)/playsym.inc
	$(PYTHON) $(LINK) --symbols2 $(GEN)/playsym2.inc \
	    --images $(GEN)/playimg.inc --play $(PLAY)

# ---------------------------------------------------------------------------
# The tic image: the game's runtime and core (with the hooks of
# dl_hook.s), every built part, the glue's groups, the 2D screens' tic-side
# modules (the status bar's, the HUD's, the finale's tickers, the sound
# channels)
# ---------------------------------------------------------------------------
PARTS :=
define add_part
PARTS += $(PART)
WAVE_$(PART) := $(WAVE)
endef
FRAGMENTS := $(sort $(wildcard $(HERE)game/*/part.mk))
$(foreach f,$(FRAGMENTS),$(eval include $(f))$(eval $(call add_part)))
INTEGRATED := $(firstword $(shell cat $(HERE)game/integrated.txt 2>/dev/null) 0)
IWAVES := $(if $(filter-out 0,$(INTEGRATED)),$(shell seq 1 $(INTEGRATED)))
BUILT := $(foreach q,$(PARTS),$(if $(filter $(WAVE_$(q)),$(IWAVES)),$(q)))
PART_SRC := $(foreach q,$(BUILT),$($(q)_SRC))
GLUE := dl_brain dl_cmd dl_disp dl_hook dl_snd dl_sym
M11T := s2t_st s2t_hu s2t_fin fx_chan
# (gspec.s, the load's SPECIALS step, is the load image's alone: nothing in
# the tic image calls it; docs/SPEED.md)
TIC_OBJS := $(addprefix $(TIC)/,gobj.o gcall.o gthink.o gpos.o gspawn.o \
            gweap.o gvalid.o far.o math-r.o math-g.o auxlc.o \
            $(GLUE:%=%.o) $(M11T:%=%.o) $(PART_SRC:%.s=%.o))
TIC_INCS := $(TIC)/gen/ggame.inc $(TIC)/gen/gplace.inc $(TIC)/gen/gdisp.inc

$(TIC)/gen/stamp: $(LAYOUTS) $(TOOLS)/gcallgraph.py $(HERE)game/integrated.txt \
        $(wildcard $(ROOT)/build/native/game/shared/placement.json)
	@mkdir -p $(TIC)/gen
	$(PYTHON) $(TOOLS)/glayout.py --out $(TIC) --no-manifests > /dev/null
	@touch $@
$(TIC_INCS) $(TIC)/game.cfg: $(TIC)/gen/stamp
	@test -f $@
$(TIC)/play.cfg: $(TIC)/game.cfg $(LINK) $(TOOLS)/playlayout.py
	$(PYTHON) $(LINK) --tic-cfg $< $(TIC)/gen/gplace.inc $@
$(TIC)/math-r.o: math.s $(INCS)
	@mkdir -p $(TIC)
	$(CA65) $(TICFLAGS) -D RENDER -o $@ -l $(@:.o=.lst) $<
$(TIC)/math-g.o: math.s $(INCS) mathgame.inc
	@mkdir -p $(TIC)
	$(CA65) $(TICFLAGS) -D GAMEMATH -o $@ -l $(@:.o=.lst) $<
$(TIC)/dl_disp.o: dl_disp.s $(INCS) $(TIC_INCS) $(GEN)/playsym.inc \
        $(GEN)/playsym2.inc $(GEN)/playimg.inc dl.inc
	@mkdir -p $(TIC)
	$(CA65) $(TICFLAGS) -o $@ -l $(@:.o=.lst) $<
$(TIC)/s2t_%.o: s2t_%.s $(INCS) $(S2INCS)
	@mkdir -p $(TIC)
	$(CA65) $(TICFLAGS) -I $(M11)/s2data -o $@ -l $(@:.o=.lst) $<
$(TIC)/%.o: %.s $(INCS) $(TIC_INCS) $(S2INCS) $(GEN)/playsym.inc dl.inc
	@mkdir -p $(dir $@)
	$(CA65) $(TICFLAGS) -o $@ -l $(@:.o=.lst) $<
# (tic.dbg, ld65's debug file: each source line's bytes, for playdisk.py's
# check of the frame slots' stores)
$(TIC)/tic.map: $(TIC_OBJS) $(TIC)/play.cfg
	$(LD65) -C $(TIC)/play.cfg -o $(TIC)/tic -Ln $(TIC)/tic.lbl -m $@ \
	    --dbgfile $(TIC)/tic.dbg $(TIC_OBJS)
tic: $(TIC)/tic.map

$(GEN)/playk.inc: $(LINK) $(TIC)/tic.map
	$(PYTHON) $(LINK) --kernel $@ --play $(PLAY)

# ---------------------------------------------------------------------------
# DOOM.SYSTEM and the card (src/native/m11/plboot.mk's objects, read only
# but pl_ready's place, which the kernel takes: playlink.py --card-cfg)
# ---------------------------------------------------------------------------
CARD_OBJS := $(addprefix $(CARD)/,pl_boot.o fx-card.o pl_irq.o pl_input.o \
             pl_keys.o dl_kern.o) $(SOUND65)/player.o $(SOUND65)/probe.o
$(CARD)/fx-card.o: $(ROOT)/src/sound/fx.s $(INCS) $(SOUND65)/tables.inc
	@mkdir -p $(CARD)
	$(CA65) $(S2FLAGS) -o $@ -l $(@:.o=.lst) $<
$(CARD)/dl_kern.o: dl_kern.s $(INCS) $(GEN)/playsym.inc $(GEN)/playk.inc
	@mkdir -p $(CARD)
	$(CA65) $(ASFLAGS) -I $(TIC)/gen -o $@ -l $(@:.o=.lst) $<
$(CARD)/%.o: %.s $(INCS)
	@mkdir -p $(CARD)
	$(CA65) $(S2FLAGS) -o $@ -l $(@:.o=.lst) $<
$(CARD)/card.cfg: $(LINK) $(LAYOUTS) $(TOOLS)/pldisk.py
	@mkdir -p $(CARD)
	$(PYTHON) $(LINK) --card-cfg $@
# (named plboot, as m11's link: tools/native/pldisk.py's functions read it)
$(CARD)/plboot.map: $(CARD_OBJS) $(CARD)/card.cfg
	$(LD65) -C $(CARD)/card.cfg -o $(CARD)/plboot -Ln $(CARD)/plboot.lbl \
	    -m $@ $(CARD_OBJS)
card: $(CARD)/plboot.map

sizes: card
	$(PYTHON) $(LINK) --sizes --play $(PLAY)

clean:
	rm -rf $(PLAY)
