CC65_PREFIX ?=
CL65 := $(CC65_PREFIX)cl65
PYTHON ?= python3

BUILD := build
DIST := dist
PROGRAM := $(BUILD)/INVASION
SYSTEM := $(BUILD)/INVASION.SYSTEM
SHIP := $(BUILD)/SHIP
PARALLAX := $(BUILD)/PARALLAX
DISK := $(DIST)/Appletini-Invasion.hdv
OBJECTS := $(BUILD)/main.o $(BUILD)/ramworks_probe.o \
	$(BUILD)/parallax_runtime.o
PARALLAX_SOURCES := \
	assets/layer1_deep_space.png \
	assets/layer2_nebula.png \
	assets/layer3_asteroids.png
SHIP_SOURCES := \
	assets/ship.json \
	assets/ship_f0.png \
	assets/ship_f1.png \
	assets/ship_f2.png \
	assets/ship_f3.png \
	assets/ship_f4.png \
	assets/ship_f5.png \
	assets/ship_f6.png \
	assets/ship_f7.png

.PHONY: all clean disk smoke

all: $(SYSTEM) $(PARALLAX)

$(BUILD) $(DIST):
	mkdir -p $@

$(BUILD)/main.o: main.c | $(BUILD)
	$(CL65) -t none --cpu 65c02 --standard c99 -Oirs -c -o $@ $<

$(BUILD)/ramworks_probe.o: ramworks_probe.s | $(BUILD)
	$(CL65) -t none --cpu 65c02 -c -o $@ $<

$(BUILD)/parallax_runtime.o: parallax_runtime.s | $(BUILD)
	$(CL65) -t none --cpu 65c02 -c -o $@ $<

$(SHIP): tools/convert_ship.py tools/convert_parallax.py $(SHIP_SOURCES) | $(BUILD)
	$(PYTHON) tools/convert_ship.py --assets assets --output $@

$(PARALLAX): tools/convert_parallax.py $(PARALLAX_SOURCES) $(SHIP) | $(BUILD)
	$(PYTHON) tools/convert_parallax.py --assets assets --ship $(SHIP) --output $@

$(PROGRAM): $(OBJECTS) appletini_invasion.cfg | $(BUILD)
	$(CL65) -t none --cpu 65c02 \
		-C appletini_invasion.cfg -m $(BUILD)/INVASION.map \
		-Ln $(BUILD)/INVASION.lbl -o $@ $(OBJECTS)

$(SYSTEM): $(PROGRAM) tools/build_system.py | $(BUILD)
	$(PYTHON) tools/build_system.py --program $(PROGRAM) --output $@

disk: $(DISK)

$(DISK): $(SYSTEM) $(PARALLAX) tools/build_disk.py | $(DIST)
	$(PYTHON) tools/build_disk.py --system $(SYSTEM) --parallax $(PARALLAX) --output $@

smoke: $(DISK)
	$(PYTHON) tools/smoke_test.py --disk $(DISK)

clean:
	rm -rf $(BUILD) $(DIST)
