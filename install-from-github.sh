#!/usr/bin/env bash
# Install (or update) the `yr` CLI from GitHub master via `uv tool install`.
#
# Builds into an isolated uv tool venv and puts `yr` on PATH (uv's tool bin
# dir, typically ~/.local/bin). Needs no local checkout -- this script works
# standalone. Re-run any time to update to the latest master.
#
# Usage: ./install-from-github.sh [extra `uv tool install` args...]
#   e.g. ./install-from-github.sh --python 3.13
#
# Override the source with YR_GIT_URL, e.g. to install a branch or tag:
#   YR_GIT_URL=git+https://github.com/knowbits/yr-in-the-terminal.git@some-branch ./install-from-github.sh
set -euo pipefail

YR_GIT_URL="${YR_GIT_URL:-git+https://github.com/knowbits/yr-in-the-terminal.git}"

if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv is not on PATH. Install it first:" >&2
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

echo "Installing yr from ${YR_GIT_URL}"
# --force: replace an existing `yr` executable (an older install, or the
#   symlink left by `just yr-deploy-local`).
# --reinstall: rebuild even if uv has this source cached, so a re-run really
#   picks up the latest master.
uv tool install --force --reinstall "$@" "${YR_GIT_URL}"
