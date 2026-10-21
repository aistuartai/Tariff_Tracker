#!/usr/bin/env bash
# Build the venv scripts/release_check.py runs the Home Assistant tests in.
# Run inside WSL (Ubuntu). Home Assistant doesn't install on Windows, and
# needs a newer Python than Ubuntu 24.04 ships, so uv supplies Python 3.13.
# Nothing here needs sudo or touches the system Python.
#
# Re-run after bumping the pins in requirements_test_ha.txt.
set -euo pipefail

UV_VERSION=0.9.5
UV_DIR="$HOME/.local/uv"
VENV="$HOME/.venvs/tariff_tracker"
REPO="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -x "$UV_DIR/uv" ]; then
    mkdir -p "$UV_DIR"
    curl -fsSL -o "$UV_DIR/uv.tgz" \
        "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-x86_64-unknown-linux-gnu.tar.gz"
    tar xzf "$UV_DIR/uv.tgz" -C "$UV_DIR" --strip-components=1
fi

"$UV_DIR/uv" python install 3.13
[ -d "$VENV" ] || "$UV_DIR/uv" venv --python 3.13 "$VENV"
VIRTUAL_ENV="$VENV" "$UV_DIR/uv" pip install -r "$REPO/requirements_test_ha.txt"

echo "Ready: $VENV"
