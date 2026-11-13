PYTHON ?= python3.11
.PHONY: engine-build engine-test engine-bench tla py-test fetch-data experiments all
engine-build engine-test engine-bench tla py-test fetch-data experiments all:
	$(PYTHON) scripts/reproduce.py $@

# Report: generate tables/figures/macros from tracked files, then build the PDF
# (tectonic or latexmk). Without a TeX engine the assets are still generated and
# only the PDF step fails.
.PHONY: report report-assets
report-assets:
	$(PYTHON) scripts/report/build_assets.py --check
report:
	$(PYTHON) scripts/report/build_assets.py --check --pdf
