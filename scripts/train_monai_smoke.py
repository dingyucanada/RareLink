import argparse
import json
from pathlib import Path

from rarelink.imaging.monai_runner import run_monai_smoke

parser = argparse.ArgumentParser(description="Run a single-site MONAI smoke training job")
parser.add_argument("--manifest", type=Path, required=True)
parser.add_argument("--site", default="site-a")
parser.add_argument("--epochs", type=int, default=1)
parser.add_argument("--output", type=Path, default=Path("artifacts/monai-smoke"))
args = parser.parse_args()

result = run_monai_smoke(args.manifest, args.site, args.output, epochs=args.epochs)
print(json.dumps(result, indent=2))
