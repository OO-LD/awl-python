.PHONY: install
install: ## Install the virtual environment and the pre-commit hooks
	@echo "🚀 Creating virtual environment using uv"
	@uv sync
	@uv run pre-commit install

.PHONY: check
check: ## Run code quality tools
	@echo "🚀 Checking lock file consistency with 'pyproject.toml'"
	@uv lock --locked
	@echo "🚀 Linting code: Running pre-commit"
	@uv run pre-commit run --files $$(git ls-files --cached --others --exclude-standard)
	@echo "🚀 Static type checking: Running ty"
	@uv run ty check
	@echo "🚀 Checking for obsolete dependencies: Running deptry"
	@uv run deptry src

.PHONY: test
test: ## Test the code with pytest
	@echo "🚀 Testing code: Running pytest"
	@uv run python -m pytest --cov --cov-config=pyproject.toml --cov-report=xml

.PHONY: bench
bench: ## Run the performance benchmarks
	@echo "🚀 Running benchmarks: pytest-benchmark"
	@uv run python -m pytest -c pytest.benchmark.ini \
		--benchmark-autosave --benchmark-json=benchmark_results.json
.PHONY: build
build: clean-build ## Build wheel file
	@echo "🚀 Creating wheel file"
	@uvx --from build pyproject-build --installer uv

.PHONY: clean-build
clean-build: ## Clean build artifacts
	@echo "🚀 Removing build artifacts"
	@uv run python -c "import shutil; import os; shutil.rmtree('dist') if os.path.exists('dist') else None"

.PHONY: publish
publish: ## Publish a release to PyPI (CI does this via trusted publishing)
	@echo "🚀 Publishing."
	@uvx twine upload --repository-url https://upload.pypi.org/legacy/ dist/*

.PHONY: docs-test
docs-test: ## Test if documentation can be built without warnings or errors
	@uv run zensical build -s

.PHONY: docs
docs: ## Build and serve the documentation
	@uv run zensical serve

.PHONY: ci
ci: check test docs-test ## Run everything CI runs, before pushing
	@# Name the branch: `make ci` is the last thing run before pushing, and a
	@# green gate on the wrong branch is an easy mistake to make.
	@branch=$$(git branch --show-current 2>/dev/null); \
		if [ -n "$$branch" ]; then \
			echo "✅ Ready to push on branch '$$branch'"; \
		else \
			echo "✅ Ready to push"; \
		fi

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
