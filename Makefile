.PHONY: setup download build export all test serve clean

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

serve:
	cd web && npm run dev

clean:
	rm -rf data/interim/* data/processed/* web/public/data/*
	touch data/interim/.gitkeep data/processed/.gitkeep web/public/data/.gitkeep
