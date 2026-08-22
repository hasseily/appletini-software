CC65_PREFIX ?=
CL65 := $(CC65_PREFIX)cl65
PYTHON ?= python3

BUILD := build
DIST := dist
PROGRAM := $(BUILD)/INVASION
DISK := $(DIST)/Appletini-Invasion.hdv
OBJECTS := $(BUILD)/main.o $(BUILD)/ramworks_probe.o

.PHONY: all clean disk smoke

all: $(PROGRAM)

$(BUILD) $(DIST):
	mkdir -p $@

$(BUILD)/main.o: main.c | $(BUILD)
	$(CL65) -t none --cpu 65c02 --standard c99 -Oirs -c -o $@ $<

$(BUILD)/ramworks_probe.o: ramworks_probe.s | $(BUILD)
	$(CL65) -t none --cpu 65c02 -c -o $@ $<

$(PROGRAM): $(OBJECTS) appletini_invasion.cfg | $(BUILD)
	$(CL65) -t none --cpu 65c02 \
		-C appletini_invasion.cfg -m $(BUILD)/INVASION.map \
		-Ln $(BUILD)/INVASION.lbl -o $@ $(OBJECTS)

disk: $(DISK)

$(DISK): $(PROGRAM) tools/build_disk.py | $(DIST)
	$(PYTHON) tools/build_disk.py --program $(PROGRAM) --output $@

smoke: $(DISK)
	$(PYTHON) tools/smoke_test.py --disk $(DISK)

clean:
	rm -rf $(BUILD) $(DIST)
