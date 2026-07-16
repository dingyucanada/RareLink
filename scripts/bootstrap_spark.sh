#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "warning: expected DGX Spark ARM64/aarch64, got $(uname -m)" >&2
fi

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev,spark]'
npm --prefix apps/web install
npm --prefix apps/web run build
.venv/bin/python scripts/smoke_runtime.py

