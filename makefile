lint:
	uv run pre-commit run --all-files

docs:
	rm -r docs/build || true
	uv run sphinx-build docs/ docs/build/

example:
	uv run examples/run.py

build:
	rm -r dist || true
	uv build

clean:
	uv clean

# Show available make targets
help:
	@echo "Available targets:"
	@echo "  lint         - Lint code with pre-commit hooks on all files"
	@echo "  docs         - Build the docs"
	@echo "  example      - Run the example"
	@echo "  build        - Build the package"
	@echo "  clean        - Clean temporary environments"

.PHONY: all docs clean
