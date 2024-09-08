lint:
	hatch -e dev run pre-commit run --all-files

version:
	hatch version

docs:
	hatch -e dev run sphinx-build docs/ docs/build/

example:
	hatch run python examples/run.py

build:
	hatch build

clean:
	hatch env prune

publish:
	hatch build
	hatch publish

# Show available make targets
help:
	@echo "Available targets:"
	@echo "  lint         - Lint code with pre-commit hooks on all files"
	@echo "  version      - Display the package version"
	@echo "  example      - Run the example"
	@echo "  build        - Build the package"
	@echo "  clean        - Clean temporary environments"
	@echo "  publish      - Publish the package"

.PHONY: all docs clean
