#!/usr/bin/env bash
# Install (or update) the `yr` CLI from this local checkout via `uv tool install`.
#
# Builds a snapshot of the working copy (uncommitted changes included) into an
# isolated uv tool venv and puts `yr` on PATH (uv's tool bin dir, typically
# ~/.local/bin). The installed copy is independent of the checkout: later
# source edits need a re-run to take effect, and `just clean` doesn't break it.
#
# Usage: ./install-from-local.sh [extra `uv tool install` args...]
#   e.g. ./install-from-local.sh --editable   # track source edits live instead of a snapshot
#
# Can be run from any directory; it always installs the repo it lives in.
set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv is not on PATH. Install it first:" >&2
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

if [[ ! -f "${REPO_DIR}/pyproject.toml" ]]; then
    echo "error: no pyproject.toml in ${REPO_DIR} -- this script must live in the repo root." >&2
    exit 1
fi

echo "Installing yr from ${REPO_DIR}"
# --force: replace an existing `yr` executable (an older install, or the
#   symlink left by `just yr-deploy-local`).
# --reinstall: rebuild from the working copy even if uv has a cached build --
#   without it, source-only edits (no pyproject.toml change) can be missed.
uv tool install --force --reinstall "$@" "${REPO_DIR}"
