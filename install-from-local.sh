#!/usr/bin/env bash
# Install (or update) the `yr` CLI from this local checkout via `uv tool install`.
#
# Puts `yr` on PATH (uv's tool bin dir, typically ~/.local/bin), backed by an
# isolated uv tool venv. Editable by default: the installed `yr` runs this
# checkout's src/ directly, so source edits are live at once with no re-run.
# Re-run only after a pyproject.toml change (new dependency, entry point);
# moving or deleting the checkout breaks the install.
#
# Usage: ./install-from-local.sh [--snapshot] [extra `uv tool install` args...]
#   --snapshot   install a frozen copy of the working copy instead (uncommitted
#                changes included); independent of the checkout, so later
#                edits need a re-run to take effect.
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

mode=(--editable)
args=()
for arg in "$@"; do
    case "${arg}" in
        --snapshot) mode=() ;;
        # Already the default -- accepted so older invocations keep working.
        --editable | -e) ;;
        *) args+=("${arg}") ;;
    esac
done

if [[ ${#mode[@]} -gt 0 ]]; then
    echo "Installing yr from ${REPO_DIR} (editable: source edits are live)"
else
    echo "Installing yr from ${REPO_DIR} (snapshot: re-run to pick up later edits)"
fi
# --force: replace an existing `yr` executable (an older install, or the
#   symlink left by `just yr-deploy-local`).
# --reinstall: rebuild from the working copy even if uv has a cached build --
#   without it, source-only edits (no pyproject.toml change) can be missed.
uv tool install --force --reinstall "${mode[@]}" "${args[@]}" "${REPO_DIR}"
