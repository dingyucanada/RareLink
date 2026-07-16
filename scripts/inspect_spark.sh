#!/usr/bin/env bash
set -euo pipefail

echo "rarelink_runtime_inventory_v1"
uname -a
uname -m
python3 --version
nvidia-smi
free -h
df -h .

if command -v docker >/dev/null 2>&1; then
  docker version
  docker info --format '{{json .Runtimes}}'
else
  echo "docker=not-installed"
fi

