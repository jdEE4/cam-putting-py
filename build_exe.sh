#!/usr/bin/env bash
# Build the one-click Putt Quest binary (macOS / Linux).
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Creating virtual environment in $VENV_DIR ..."
  python3 -m venv "$VENV_DIR"
fi

"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r "$ROOT_DIR/requirements.txt"
"$PYTHON_BIN" -m pip install -r "$ROOT_DIR/requirements-game.txt"
"$PYTHON_BIN" -m pip install -r "$ROOT_DIR/requirements-build.txt"

rm -rf "$ROOT_DIR/build/PuttQuest" "$ROOT_DIR/dist/PuttQuest"
cd "$ROOT_DIR"
"$PYTHON_BIN" -m PyInstaller PuttQuest.spec --noconfirm

echo
echo "Done: dist/PuttQuest  — share that single file, no Python needed."
