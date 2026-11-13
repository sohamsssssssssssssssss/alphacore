PYTHON ?= python3.11
.PHONY: engine-build engine-test engine-bench tla py-test fetch-data experiments all
engine-build engine-test engine-bench tla py-test fetch-data experiments all:
	$(PYTHON) scripts/reproduce.py $@
