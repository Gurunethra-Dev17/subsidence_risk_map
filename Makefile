.PHONY: validate-contracts demo test

PYTHON ?= python

validate-contracts:
	$(PYTHON) -m contracts.validate

demo: validate-contracts
	@echo "Starter fixtures validate. Package demos are ready to be implemented by each owner."

test: validate-contracts
	$(PYTHON) -m pytest
