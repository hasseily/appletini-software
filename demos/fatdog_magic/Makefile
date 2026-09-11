PYTHON ?= python

.PHONY: disk verify smoke
disk:
	$(PYTHON) tools/build_fatdog_magic_disk.py

verify:
	$(PYTHON) tools/verify_disk.py

smoke:
	$(PYTHON) tools/smoke_test.py
