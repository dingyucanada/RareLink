import argparse
from pathlib import Path

from rarelink.imaging.synthetic import generate_synthetic_dataset

parser = argparse.ArgumentParser(description="Generate a non-clinical RareLink NIfTI demo cohort")
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--cases-per-site", type=int, default=4)
parser.add_argument("--shape", type=int, nargs=3, default=(32, 32, 32))
args = parser.parse_args()

manifest = generate_synthetic_dataset(
    args.output,
    cases_per_site=args.cases_per_site,
    shape=tuple(args.shape),
)
print(f"generated_cases={len(manifest['cases'])}")
print(f"manifest={args.output / 'manifest.json'}")
