import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rarelink.imaging.public_benchmark import MSD_TASK01_URL, prepare_msd_task01  # noqa: E402

parser = argparse.ArgumentParser(
    description="Directly download and create a three-site MSD Task01 benchmark on this node"
)
parser.add_argument("--data-root", type=Path, default=Path("data/raw/msd-task01"))
parser.add_argument(
    "--output", type=Path, default=Path("data/runtime/msd-brain-tumour-v1")
)
parser.add_argument("--cases-per-site", type=int, default=8)
parser.add_argument("--seed", type=int, default=2026)
parser.add_argument("--url", default=MSD_TASK01_URL)
parser.add_argument("--skip-hashes", action="store_true")
args = parser.parse_args()

manifest = prepare_msd_task01(
    data_root=args.data_root,
    manifest_root=args.output,
    cases_per_site=args.cases_per_site,
    seed=args.seed,
    url=args.url,
    skip_hashes=args.skip_hashes,
)
print(
    json.dumps(
        {
            "manifest": str(args.output / "manifest.json"),
            "dataset_id": manifest["dataset_id"],
            "sites": manifest["sites"],
            "cases": len(manifest["cases"]),
            "partition": manifest["partition"],
        },
        ensure_ascii=False,
        indent=2,
    )
)
