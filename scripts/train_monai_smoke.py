import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rarelink.imaging.monai_runner import run_monai_smoke  # noqa: E402

parser = argparse.ArgumentParser(description="Run a single-site MONAI smoke training job")
parser.add_argument("--manifest", type=Path, required=True)
parser.add_argument("--site", default="site-a")
parser.add_argument("--epochs", type=int, default=1)
parser.add_argument("--output", type=Path, default=Path("artifacts/monai-smoke"))
args = parser.parse_args()

result = run_monai_smoke(args.manifest, args.site, args.output, epochs=args.epochs)
print(json.dumps(result, indent=2))
