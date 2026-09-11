set shell := ["bash", "-euo", "pipefail", "-c"]

# List available recipes
default:
    @just --list

# Install/sync the UV-managed virtualenv (incl. dev dependencies)
sync:
    uv sync --all-groups

# Run the ruff linter
lint: sync
    uv run ruff check .

# Auto-format the code
fmt: sync
    uv run ruff format .

# Check formatting without changing files
fmt-check: sync
    uv run ruff format --check .

# Run the pytest suite
test: sync
    uv run pytest

# Run the bats behavioural tests
test-bats: sync
    bats tests/

# Run the full QA suite: lint, format check, unit tests, bats tests
qa: lint fmt-check test test-bats

# Show today's forecast (pass extra args after --, e.g. `just today -- --hours 12`)
today *args: sync
    uv run python yr-today.py {{ args }}

# Show the 7-day forecast (pass extra args after --, e.g. `just forecast -- --days 3`)
forecast *args: sync
    uv run python yr-forecast.py {{ args }}

# Remove the virtualenv and caches
clean:
    rm -rf .venv .pytest_cache .ruff_cache
    find . -type d -name __pycache__ -exec rm -rf {} +
