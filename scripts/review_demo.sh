#!/usr/bin/env bash
set -euo pipefail

if [[ -x .venv/bin/python ]]; then
  python_bin=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  python_bin=python3
else
  echo "Python 3 is required. Run the Spark compose command or create .venv first." >&2
  exit 1
fi

"$python_bin" scripts/seed_competition_evidence.py --target artifacts
"$python_bin" scripts/verify_demo_evidence.py --artifact-root artifacts --write
