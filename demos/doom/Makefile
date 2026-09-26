# Doom (Freedoom Phase 1) for the Appletini
#
#   make            the data, DOOM.SYSTEM, RENDER.BIN, LC.BIN, GAME.BIN
#                   and the banked-code preload DOOM.BANKS in $(BUILD)
#   make disk       dist/Appletini-DOOM.hdv (a ProDOS volume sized to the data)
#   make test       the unit tests (py65 and pure Python)
#   make STANDIN=1  the same with the platform's stand-in data set
#                   (tools/make_standin.py) in build/standin
#
# The data: tools/wad2a2.py converts FREEDOOM (default build/freedoom1.wad,
# fetched by tools/fetch_freedoom.py) into build/data. Without the
# converter, or with STANDIN=1, the stand-in data set is used and the
# build goes to build/standin (it has its own doomdata.inc/doomdata.h, so
# its binaries differ). The link (src/doom.cfg) writes all four program
# files at once into $(BUILD). APPLETINI_ROOT points at the appletini-one
# checkout (ProDOS master image, enhanced //e ROM for the test machine).

APPLETINI_ROOT ?= ../../../appletini-one
FREEDOOM ?= build/freedoom1.wad
PYTHON ?= python3
CA65 ?= ca65
CC65 ?= cc65
LD65 ?= ld65

ifeq ($(STANDIN)$(if $(wildcard tools/wad2a2.py),,1),)
BUILD ?= build
# the converted data stays in build/data whatever BUILD is (parallel builds
# such as BUILD=build/rtrack/ share it)
DATA ?= build/data
else
STANDIN := 1
BUILD ?= build/standin
DATA ?= $(BUILD)/data
endif
DIST := dist
DISK ?= $(DIST)/Appletini-DOOM.hdv
PROFILE ?= 0
CONTROL_BANK ?= 0
VIDEO_HZ ?= 60
RENDER_SHADED ?= 0
ifneq ($(VIDEO_HZ),50)
ifneq ($(VIDEO_HZ),60)
$(error VIDEO_HZ must be 50 or 60)
endif
endif
ifneq ($(RENDER_SHADED),0)
ifneq ($(RENDER_SHADED),1)
$(error RENDER_SHADED must be 0 or 1)
endif
endif

KERNEL_S := kstart space far video input frame loader
# the renderer: src/render/*.s against the converted data; the stand-in data
# has no map, texture or flat directory, so that build keeps the platform's
# test pattern (src/render/stub.s) as render_frame
ifeq ($(STANDIN),)
RENDER_S := $(filter-out stub,$(patsubst src/render/%.s,%,$(wildcard src/render/*.s)))
else
RENDER_S := stub
endif
# the GAME space's sources (another directory can stand in, e.g. a snapshot
# of them while they are being worked on)
GAMESRC ?= src/game
GAME_S := $(patsubst $(GAMESRC)/%.s,%,$(wildcard $(GAMESRC)/*.s))
GAME_C := $(patsubst $(GAMESRC)/%.c,%,$(wildcard $(GAMESRC)/*.c))

OBJS := $(addprefix $(BUILD)/kernel/,$(addsuffix .o,$(KERNEL_S))) \
	$(addprefix $(BUILD)/render/,$(addsuffix .o,$(RENDER_S))) \
	$(addprefix $(BUILD)/game/,$(addsuffix .o,$(GAME_S) $(GAME_C)))
PROGRAM := $(BUILD)/DOOM.SYSTEM $(BUILD)/RENDER.BIN $(BUILD)/LC.BIN $(BUILD)/GAME.BIN
ifeq ($(STANDIN),)
BANKED ?= 1
else ifeq ($(BANKED),1)
$(error BANKED=1 needs converted game data; omit BANKED when using STANDIN=1)
endif
ifeq ($(BANKED),1)
PROGRAM += $(BUILD)/DOOM.BANKS
endif

AFLAGS := --cpu 65c02 -g -D VIDEO_HZ=$(VIDEO_HZ) -D RENDER_SHADED=$(RENDER_SHADED) -I src/kernel -I $(DATA)
CFLAGS := -t none --cpu 65c02 --standard c99 -Oirs -g -I $(GAMESRC) -I $(DATA)
DATA_STAMP := $(DATA)/manifest.json

.PHONY: all disk profile test clean

all: $(PROGRAM)

# --- the data -------------------------------------------------------------
ifeq ($(STANDIN),)
$(DATA_STAMP): tools/wad2a2.py $(FREEDOOM)
	$(PYTHON) tools/wad2a2.py --wad $(FREEDOOM) --out $(DATA)

$(FREEDOOM):
	$(PYTHON) tools/fetch_freedoom.py --out $(dir $(FREEDOOM))
else
$(DATA_STAMP): tools/make_standin.py
	$(PYTHON) tools/make_standin.py --out $(DATA) $(if $(wildcard $(FREEDOOM)),--wad $(FREEDOOM))
endif

$(DATA)/doomdata.inc $(DATA)/doomdata.h: $(DATA_STAMP)

# the renderer's generated tables, once tools/gen_tables.py exists
ifneq ($(wildcard tools/gen_tables.py),)
TABLES_STAMP := $(BUILD)/tables.stamp
$(TABLES_STAMP): tools/gen_tables.py | $(BUILD)
	$(PYTHON) tools/gen_tables.py --out $(BUILD)
	touch $@
AFLAGS += -I $(BUILD)
OBJS += $(BUILD)/render/tables.o

$(BUILD)/render/tables.o: $(TABLES_STAMP) | $(BUILD)/render
	$(CA65) $(AFLAGS) -o $@ $(BUILD)/render/tables.s
endif

# --- assemble, compile, link ----------------------------------------------
$(BUILD)/kernel/%.o: src/kernel/%.s src/kernel/kernel.inc $(DATA)/doomdata.inc $(TABLES_STAMP) | $(BUILD)/kernel
	$(CA65) $(AFLAGS) -o $@ $<

$(BUILD)/render/%.o: src/render/%.s $(wildcard src/render/*.inc) src/kernel/kernel.inc $(DATA)/doomdata.inc $(TABLES_STAMP) | $(BUILD)/render
	$(CA65) $(AFLAGS) -o $@ $<

$(BUILD)/game/%.o: $(GAMESRC)/%.s $(wildcard $(GAMESRC)/*.inc) src/kernel/rview.inc | $(BUILD)/game
	$(CA65) $(AFLAGS) -I $(GAMESRC) -o $@ $<

$(BUILD)/game/%.s: $(GAMESRC)/%.c $(wildcard $(GAMESRC)/*.h) $(DATA)/doomdata.h | $(BUILD)/game
	$(CC65) $(CFLAGS) -o $@ $<

$(BUILD)/game/%.o: $(BUILD)/game/%.s
	$(CA65) $(AFLAGS) -o $@ $<

.PRECIOUS: $(BUILD)/game/%.s

ifeq ($(BANKED),1)
BANKED_DEPS := Makefile $(wildcard $(GAMESRC)/* src/kernel/* src/render/*) src/doom.cfg \
	tools/bank_game.py tools/build_banked.py tools/gen_tables.py tools/check_link.py
# A single witness works with macOS make 3.81 as well as GNU make 4.x.
# Rebuild if any output is missing, including metadata used by the runner.
BANKED_OUTPUTS := $(PROGRAM) $(BUILD)/AMEM.BIN $(BUILD)/banked.json $(BUILD)/doom.map $(BUILD)/doom.lbl \
	$(BUILD)/doom.dbg $(BUILD)/doom-banked.cfg $(BUILD)/GAME.TABLES $(BUILD)/GAME.INFO \
	$(BUILD)/banks/banks.json $(BUILD)/link-report.json \
	$(addprefix $(BUILD)/GBANK,$(addsuffix .BIN,96 97 98 99 $(CONTROL_BANK) 101 102))
BANKED_STAMP := $(BUILD)/banked.stamp
BANKED_BUILD_ID := $(abspath $(GAMESRC)) $(abspath $(DATA)) PROFILE=$(PROFILE) CONTROL_BANK=$(CONTROL_BANK) VIDEO_HZ=$(VIDEO_HZ) RENDER_SHADED=$(RENDER_SHADED) $(CA65) $(CC65) $(LD65)
ifeq ($(PROFILE),1)
BANKED_OUTPUTS += $(BUILD)/profile.json
endif
BANKED_MISSING := $(filter-out $(wildcard $(BANKED_OUTPUTS)),$(BANKED_OUTPUTS))
ifneq ($(strip $(shell cat $(BANKED_STAMP) 2>/dev/null)),$(BANKED_BUILD_ID))
BANKED_MISSING += configuration
endif
ifneq ($(BANKED_MISSING),)
.PHONY: banked_missing
$(BANKED_STAMP): banked_missing
endif
$(BANKED_OUTPUTS): $(BANKED_STAMP)
$(BANKED_STAMP): $(BANKED_DEPS) $(DATA_STAMP)
	$(PYTHON) tools/build_banked.py --build $(BUILD) --data $(DATA) --source $(GAMESRC) --python $(PYTHON) \
		--ca65 $(CA65) --cc65 $(CC65) --ld65 $(LD65) --control-bank $(CONTROL_BANK) --video-hz $(VIDEO_HZ) $(if $(filter 1,$(PROFILE)),--profile) $(if $(filter 1,$(RENDER_SHADED)),--render-shaded)
	$(PYTHON) tools/check_link.py --build $(BUILD) --json $(BUILD)/link-report.json
	@printf '%s\n' '$(BANKED_BUILD_ID)' > $@
else
ifneq ($(wildcard $(BUILD)/banked.json),)
$(error This BUILD directory contains a banked game; use a separate BUILD for BANKED=0)
endif
$(PROGRAM) &: $(OBJS) src/doom.cfg
	$(LD65) -C src/doom.cfg -m $(BUILD)/doom.map -Ln $(BUILD)/doom.lbl --dbgfile $(BUILD)/doom.dbg \
		-o $(BUILD)/ $(OBJS) none.lib
	$(PYTHON) tools/check_link.py --build $(BUILD)
endif

# --- the disk -------------------------------------------------------------
disk: $(DISK)

$(DISK): $(PROGRAM) $(BANKED_STAMP) $(DATA_STAMP) tools/build_disk.py | $(DIST)
	$(PYTHON) tools/build_disk.py --build $(BUILD) --data $(DATA) --output $@ \
		--master $(APPLETINI_ROOT)/software/ProDOS_2_4_3.po

# Keep the instrumented hardware image and matching serial metadata together.
profile:
	$(MAKE) PROFILE=1 BUILD=build/profile DISK=$(DIST)/Appletini-DOOM-profile.hdv disk
	cp build/profile/profile.json $(DIST)/Appletini-DOOM-profile.json

# --- tests ----------------------------------------------------------------
# the platform tests build their own stand-in configuration (build/standin)
test:
	@status=0; for t in $(sort $(wildcard tests/test_*.py)); do echo "== $$t"; $(PYTHON) $$t || status=1; done; exit $$status

$(BUILD) $(BUILD)/kernel $(BUILD)/render $(BUILD)/game $(DIST):
	mkdir -p $@

# keeps the converted data and the WAD
clean:
	rm -rf $(BUILD)/kernel $(BUILD)/render $(BUILD)/game $(PROGRAM) $(BUILD)/doom.* \
		$(BUILD)/banks $(BUILD)/banked.json $(BUILD)/banked.stamp $(BUILD)/doom-banked.cfg \
		$(BUILD)/banklayout.inc $(BUILD)/DOOM.BANKS $(BUILD)/GBANK*.BIN \
		$(BUILD)/GAME.TABLES $(BUILD)/GAME.INFO $(BUILD)/AMEM.BIN $(BUILD)/link-report.json \
		$(BUILD)/tables.stamp build/standin $(DIST)
