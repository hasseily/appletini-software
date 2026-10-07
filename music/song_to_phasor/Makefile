PYTHON ?= python3
APPLETINI_ROOT ?= ../../../appletini-one

.PHONY: test example fixture firmware rtl-test fit-test player clean
test:
	$(PYTHON) -m unittest discover -s tests -v

example:
	$(PYTHON) -m phasor compile examples/phrase.json --out build/phrase

fixture:
	$(PYTHON) examples/make_fixture.py build/fixture

firmware:
	$(PYTHON) -m phasor check-firmware $(APPLETINI_ROOT)

rtl-test:
	PHASOR_FIRMWARE_ROOT=$(APPLETINI_ROOT) $(PYTHON) -m unittest discover -s tests -p 'test_rtl.py' -v

fit-test:
	PHASOR_FIT_RTL=1 PHASOR_FIRMWARE_ROOT=$(APPLETINI_ROOT) $(PYTHON) -m unittest discover -s tests -p 'test_fit_rtl.py' -v

player:
	$(MAKE) -C player

clean:
	rm -rf build
