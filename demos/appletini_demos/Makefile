PYTHON ?= python

.PHONY: disk verify verify-build supersprite
disk:
	$(PYTHON) tools/build_appletini_demo_disk.py

verify:
	$(PYTHON) tools/test_demo_disk.py
	$(PYTHON) tools/test_appletini_webserver.py

verify-build:
	$(PYTHON) tools/test_demo_disk.py --disk build/Appletini_Demos.po
	$(PYTHON) tools/test_appletini_webserver.py

supersprite:
	$(PYTHON) tools/build_supersprite_demo.py
