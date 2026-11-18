.PHONY: validate-contracts demo test tiles-candidate tiles-quality serve-tiles

PYTHON ?= python
CITY ?= delhi
PACK_DIR ?= out/delhi/pack-build-candidate-0.0.1
TILE_VERSION ?= candidate-0.0.3
TILE_DIR ?= out/$(CITY)/tiles-candidate/pmtiles-wards-cells-$(TILE_VERSION)
C5_LAYER_ARGS ?= --skip-points --skip-buildings
C5_METRIC_ARGS ?=

validate-contracts:
	$(PYTHON) -m contracts.validate

demo: validate-contracts
	@echo "Starter fixtures validate. Package demos are ready to be implemented by each owner."

test: validate-contracts
	$(PYTHON) -m pytest

# Internal reduced-scope C5 build. Use a new TILE_VERSION for every rebuild.
tiles-candidate:
	$(PYTHON) -m pipeline.tiles --pack-dir "$(PACK_DIR)" --pmtiles-output-dir "$(TILE_DIR)" --city "$(CITY)" --version "$(TILE_VERSION)" $(C5_LAYER_ARGS) $(C5_METRIC_ARGS)

tiles-quality:
	$(PYTHON) -m pipeline.tile_quality "$(TILE_DIR)" --report tiles_quality.json

serve-tiles:
	$(PYTHON) -m pipeline.serve_tiles --candidate-dir "$(TILE_DIR)" --host 127.0.0.1 --port 8765
