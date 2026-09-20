# Root Makefile — runs the test suite and provides dev helpers.

.PHONY: test test-unit test-integration clean install mcp serve

# Run all tests.
test: test-unit test-integration

test-unit:
	python -m pytest tests/ -v

test-integration:
	@bash tests/run.sh

# Install dev dependencies.
install:
	pip install -e ".[dev]"
	cd mcp && npm install

# Serve the dashboards + logs on :8765.
serve:
	python -m http.server 8765 -d .

# Build the MCP server.
mcp:
	cd mcp && npm run build

clean:
	rm -rf __pycache__ .pytest_cache *.egg-info
	rm -rf mcp/dist mcp/node_modules
