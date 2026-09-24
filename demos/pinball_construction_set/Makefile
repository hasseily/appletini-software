# Pinball Construction Set for the Appletini
#
#   make            build/PCS.SYSTEM and build/PCS.SPR
#   make disk       dist/Appletini-PCS.hdv (800 KB ProDOS image)
#   make test       unit tests (py65)
#   make baseline   convert and assemble the unmodified upstream (checksums)
#
# UPSTREAM is a local clone of https://github.com/billbudge/PCS_AppleII
# (MIT licence). APPLETINI_ROOT points at the appletini-one checkout for
# the ProDOS master image; ROM at the enhanced //e ROM for the test machine.

UPSTREAM ?= $(firstword $(wildcard upstream /home/user/billbudge/pcs_appleii))
APPLETINI_ROOT ?= ../../../appletini-one
ROM ?= $(APPLETINI_ROOT)/docs/Apple2e_Enhanced.rom
PYTHON ?= python3
CA65 ?= ca65
LD65 ?= ld65

BUILD := build
DIST := dist
SRC := src
TOOLS := tools

MODULES := CDRAW EDIT PPAK RUN RUN2 WIRE
GEN_S := $(addprefix $(BUILD)/port/,$(addsuffix .s,$(MODULES)))
GEN_O := $(GEN_S:.s=.o)

PORT_SRC := crt0 loader tables main video cdraw render input play sound files magnify wire kinds
PORT_O := $(addprefix $(BUILD)/,$(addsuffix .o,$(PORT_SRC)))
ASSETS_O := $(BUILD)/assets.o $(BUILD)/layout_data.o $(BUILD)/default_table.o

AFLAGS := --cpu 65c02 -I $(SRC) -I $(BUILD) -g

PATCHES := $(SRC)/patches.json $(BUILD)/layout_patches.json $(BUILD)/kind_patches.json

.PHONY: all disk test baseline clean

all: $(BUILD)/PCS.SYSTEM $(BUILD)/PCS.SPR

$(BUILD)/parts.json: $(TOOLS)/parts.py | $(BUILD)
	$(PYTHON) $(TOOLS)/parts.py $(UPSTREAM) --json $@

# assets: text art -> sprite tables, PCS.SPR, preview
$(BUILD)/assets.s $(BUILD)/assets.inc $(BUILD)/PCS.SPR: $(TOOLS)/gen_assets.py $(wildcard assets/*.txt) $(BUILD)/parts.json | $(BUILD)
	$(PYTHON) $(TOOLS)/gen_assets.py --assets assets --parts $(BUILD)/parts.json --build $(BUILD) --quiet

# layout: kit rectangles and icon records -> patches for EDIT/WIRE + data
$(BUILD)/layout_patches.json $(BUILD)/layout_data.s: $(TOOLS)/layout.py $(BUILD)/assets.inc | $(BUILD)
	$(PYTHON) $(TOOLS)/layout.py $(UPSTREAM) --assets $(BUILD)/assets.inc --patches $(BUILD)/layout_patches.json --data $(BUILD)/layout_data.s

# kinds: part templates -> kind table + patches of the RUN.S template records
$(BUILD)/kind_patches.json $(BUILD)/kinds.s: $(TOOLS)/kinds.py $(BUILD)/parts.json $(BUILD)/assets.inc | $(BUILD)
	$(PYTHON) $(TOOLS)/kinds.py $(UPSTREAM) --parts $(BUILD)/parts.json --assets $(BUILD)/assets.inc --patches $(BUILD)/kind_patches.json --out $(BUILD)/kinds.s

# upstream conversion
$(GEN_S): $(TOOLS)/merlin2ca65.py $(SRC)/drops.json $(PATCHES) $(SRC)/exports.json | $(BUILD)/port
	$(PYTHON) $(TOOLS)/merlin2ca65.py $(UPSTREAM) --layout port --drops $(SRC)/drops.json \
		$(foreach p,$(PATCHES),--patches $(p)) --exports $(SRC)/exports.json --output $(BUILD)/port

$(BUILD)/port/%.o: $(BUILD)/port/%.s $(SRC)/pcs.inc
	$(CA65) $(AFLAGS) -o $@ $<

$(BUILD)/%.o: $(SRC)/%.s $(SRC)/pcs.inc $(BUILD)/assets.inc
	$(CA65) $(AFLAGS) -o $@ $<

$(BUILD)/%.o: $(BUILD)/%.s $(SRC)/pcs.inc
	$(CA65) $(AFLAGS) -o $@ $<

$(BUILD)/kinds.o: $(BUILD)/kinds.s $(BUILD)/assets.inc
	$(CA65) $(AFLAGS) -o $@ $<

$(BUILD)/PCS: $(PORT_O) $(GEN_O) $(ASSETS_O) $(SRC)/pcs.cfg
	$(LD65) -C $(SRC)/pcs.cfg -m $(BUILD)/PCS.map -Ln $(BUILD)/PCS.lbl -o $@ $(PORT_O) $(GEN_O) $(ASSETS_O)

$(BUILD)/PCS.SYSTEM: $(BUILD)/PCS $(TOOLS)/build_system.py
	$(PYTHON) $(TOOLS)/build_system.py --program $(BUILD)/PCS --output $@ --limit 0x9C00

disk: $(BUILD)/PCS.SYSTEM $(BUILD)/PCS.SPR $(BUILD)/PCS.TITLE $(BUILD)/tables
	$(PYTHON) $(TOOLS)/build_disk.py --system $(BUILD)/PCS.SYSTEM --sprites $(BUILD)/PCS.SPR \
		--title $(BUILD)/PCS.TITLE --tables $(BUILD)/tables --output $(DIST)/Appletini-PCS.hdv

$(BUILD)/default_table.s $(BUILD)/tables: $(TOOLS)/make_tables.py $(BUILD)/parts.json | $(BUILD)
	$(PYTHON) $(TOOLS)/make_tables.py --parts $(BUILD)/parts.json --out $(BUILD)/tables --default $(BUILD)/default_table.s

$(BUILD)/PCS.TITLE: $(TOOLS)/title.py $(BUILD)/assets.inc | $(BUILD)
	$(PYTHON) $(TOOLS)/title.py --assets assets --out $(BUILD)/PCS.TITLE

baseline: | $(BUILD)/baseline
	$(PYTHON) $(TOOLS)/merlin2ca65.py $(UPSTREAM) --layout baseline --output $(BUILD)/baseline

test:
	@status=0; for t in $(sort $(wildcard tests/test_*.py)); do echo "== $$t"; $(PYTHON) $$t || status=1; done; exit $$status

$(BUILD) $(BUILD)/port $(BUILD)/baseline $(DIST):
	mkdir -p $@

clean:
	rm -rf $(BUILD) $(DIST)
