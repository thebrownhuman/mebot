# Thin wrapper: every target runs scripts/dev.sh (usable without make, e.g. in Git Bash).
.PHONY: install dev test lint fmt build docker docs docs-check
install dev test lint fmt build docker docs docs-check:
	@bash scripts/dev.sh $@
