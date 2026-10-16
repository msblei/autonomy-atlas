.PHONY: setup download build export all test verify release serve clean

PY ?= python3
VENV := .venv
ATLAS := $(VENV)/bin/atlas

setup:
	$(PY) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e ".[dev]"
	cd web && npm install

download:
	$(ATLAS) download

build:
	$(ATLAS) build

export:
	$(ATLAS) export

all: download build export

test:
	$(VENV)/bin/pytest -q

# Every check, in order; any failure stops (docs/methodology.md, "Checks"):
# unit + real-data + FAOSTAT-golden tests, invariants on the published data, the independent
# recomputation (verify/), what the browser actually shows, then the audit page for a human.
verify:
	$(VENV)/bin/pytest -q
	$(ATLAS) validate
	$(VENV)/bin/python -I verify/recompute.py
	cd web && npx playwright test
	$(ATLAS) report
	@echo "Review data/processed/audit.html before publishing."

# Rebuild from the sources, check everything, then build the site (web/scripts/check-data.mjs
# refuses to build data that did not pass). After publishing: `atlas release-snapshot`.
release: all verify
	cd web && npm run build

serve:
	cd web && npm run dev

clean:
	rm -rf data/interim/* data/processed/* web/public/data/*
	touch data/interim/.gitkeep data/processed/.gitkeep web/public/data/.gitkeep
