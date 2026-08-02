#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is not installed or not on PATH." >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Creating virtual environment in $VENV_DIR ..."
  python3 -m venv "$VENV_DIR"
  "$PYTHON_BIN" -m pip install --upgrade pip
fi

if ! "$PYTHON_BIN" -c "import pygame, numpy" >/dev/null 2>&1; then
  echo "Installing game dependencies from requirements-game.txt ..."
  "$PYTHON_BIN" -m pip install -r "$ROOT_DIR/requirements-game.txt"
fi

exec "$PYTHON_BIN" -m putt_quest "$@"
