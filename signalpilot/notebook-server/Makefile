# Makefile for marimo - Development and build tasks
# Prerequisites:
#   - uv: for Python dependency management, testing, and building
#   - pnpm: for package development (packages/ only)
#   - Node.js: for package development (packages/ only)

.PHONY: help
# 📖 Show available commands
help:
	@printf "\nMarimo Development Commands:\n\n"
	@awk '/^#/{c=substr($$0,3);next}c&&/^[[:alpha:]][[:alnum:]_-]+:/{printf "  \033[36m%-20s\033[0m %s\n", substr($$1,1,index($$1,":")-1),c}1{c=0}' $(MAKEFILE_LIST)
	@printf "\nRun 'make check-prereqs' and 'make install-all' to get started!\n\n"

###############
# Setup Tasks #
###############

.PHONY: install-all
# 🚀 First-time setup: Install all dependencies (packages & Python)
install-all: py

.PHONY: check-prereqs
# ✓ Check if all required tools are installed
check-prereqs:
	@command -v uv >/dev/null 2>&1 || { echo "uv is required. See https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
	@echo "✅ All prerequisites are installed!"

.PHONY: py
# 🐍 Install Python dependencies in editable mode
py:
	@command -v uv >/dev/null 2>&1 || { echo "uv is required. See https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
	uv pip install --group=dev -e .

######################
# Development Tasks #
######################

.PHONY: dev
dev:
	@echo "Starting development server..."
	uv run sp edit --no-token --headless /tmp --port 2718

#############
# Testing   #
#############

.PHONY: test
# 🧪 Run all tests (Python)
test: py-test

.PHONY: check
# 🧹 Run all checks
check: py-check

.PHONY: py-check
# 🔍 Typecheck, lint, format python
py-check:
	./scripts/pycheck.sh

.PHONY: typos
# 🔍 Check for typos
typos:
	uv run typos

.PHONY: py-test
# 🧪 Test python
py-test:
	uv run typos
	./scripts/pytest.sh --optional $(ARGS)

.PHONY: py-test-narwhals
# 🧪 Test narwhals-related tests (used externally by narwhals repo)
py-test-narwhals:
	uv run --group test pytest \
		tests/_data/ \
		tests/_plugins/ui/_impl/ \
		tests/_utils/test_narwhals_utils.py

.PHONY: py-snapshots
# 📸 Update snapshots
py-snapshots:
	uv run --group test pytest \
		tests/_server/templates/test_templates.py \
		tests/_server/api/endpoints/test_export.py \
		tests/test_api.py

##############
# Packaging  #
##############

.PHONY: wheel
# 📦 Build wheel
wheel:
	uv build


#################
# Documentation #
#################

.PHONY: docs
# 📚 Build docs
docs:
	uv run --group docs mkdocs build

.PHONY: docs-serve
# 📚 Serve docs
docs-serve:
	uv run --group docs mkdocs serve --clean --livereload
