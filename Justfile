set shell := ["bash", "-euo", "pipefail", "-c"]

# List available recipes
default:
    @just --list

# Install/sync the UV-managed virtualenv (incl. dev dependencies)
sync:
    uv sync --all-groups

# Run the ruff linter
lint: sync
    uv run ruff check src tests

# Auto-format the code
fmt: sync
    uv run ruff format src tests

# Check formatting without changing files
fmt-check: sync
    uv run ruff format --check src tests

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
    uv run yr today {{ args }}

# Show the 7-day forecast (pass extra args after --, e.g. `just forecast -- --days 3`)
forecast *args: sync
    uv run yr forecast {{ args }}

# Symlink the project's own yr entrypoint into ~/.local/bin (idempotent).
# Shares that path with `uv tool install`/`uvx --from` (see README) -- running
# either after this one overwrites the symlink to point at an isolated tool
# venv instead of this checkout; re-run this recipe to point `yr` back here.
deploy-local: sync
    mkdir -p ~/.local/bin
    ln -sf "$(pwd)/.venv/bin/yr" ~/.local/bin/yr

# Remove the virtualenv and caches
clean:
    rm -rf .venv .pytest_cache .ruff_cache
    find . -type d -name __pycache__ -exec rm -rf {} +

# ============================================================================
# 1-Extract Deterministic Context-Optimization Recipes
# ============================================================================

# Single-file AST structural skeleton (<150 tokens)
dev-code-outline FILE *FLAGS: # Run AST structural skeleton outliner on a source file
    @ai-outline "{{FILE}}" {{FLAGS}}

# Multi-language structural AST search & pattern query
dev-ast-grep PATTERN *FLAGS: # Run structural AST search across repository
    @ast-grep -p '{{PATTERN}}' {{FLAGS}}

# Slices linter / compiler log into a prioritized <500-byte digest
dev-qa-digest LOG="tmp-build-output/qa.log": # Emit grouped linter/compiler digest
    @ai-slicer --tool auto "{{LOG}}"

# Slices test failure log into a <1KB Markdown packet
dev-test-digest LOG="tmp-build-output/test.log": # Emit test failure digest
    @ai-slicer --runner auto "{{LOG}}"

# ============================================================================
# Native ai-tools Recipes (ai-runner / ai-patch / ai-pack / ai-daemon / ai-doctor)
# ============================================================================

# Run a polyglot command through the execution proxy (auto-slices failures)
dev-run *CMD: # ai-runner -- <cmd>
    @ai-runner {{CMD}}

# Re-run the active failing test from the D.2 runtime-dir active incident
dev-retest: # ai-runner --retest
    @ai-runner --retest

# Self-verifying AST symbol replacement (validates before writing; real compiler check where available)
dev-patch TARGET *FLAGS: # ai-patch <file>:<symbol>
    @ai-patch "{{TARGET}}" {{FLAGS}}

# Auto-target and fix the active ai-runner incident
dev-fix-incident: # ai-patch --fix-incident
    @ai-patch --fix-incident

# Assemble multi-symbol context with 1-hop call-tree windowing
dev-pack *TARGETS: # ai-pack <file:symbol> ...
    @ai-pack {{TARGETS}}

# Manage the resident ai-daemon cache accelerator
dev-daemon ACTION="status": # ai-daemon {start|stop|status|restart} --workspace <repo>
    @ai-daemon {{ACTION}} --workspace .

# Native sub-millisecond workspace health gate
dev-doctor: # ai-doctor (falls back to scripts-AI/ai-workflow-doctor.sh)
    @bash scripts-AI/ai-workflow-doctor.sh

# Structural invariant scan (ast-grep) — no-op if repo has no catalog yet
dev-verify:
    @test -f sgconfig.yml && ast-grep scan . || echo "dev-verify: no ast-grep catalog configured yet"
