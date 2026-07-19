# Spark MSD engineering evidence

This directory contains aggregate-only evidence copied from the 2026-07-20 DGX Spark run:

- `fedavg-summary.json`: one-round, three-logical-site NVIDIA FLARE summary;
- `metrics/site-*-round-001.json`: per-site aggregate metrics emitted by the client contract.

It intentionally excludes raw images, labels, case identifiers, case-level data paths, credentials,
certificates and model weights. The summary retains non-sensitive container artifact paths for auditability.
The 24-case MSD Task01 run is an engineering smoke test, not a clinical-performance,
pediatric-cohort or real cross-hospital claim. See
[`outputs/RareLink-2026-07-20-MSD真实影像Spark联邦运行报告.md`](../../outputs/RareLink-2026-07-20-MSD真实影像Spark联邦运行报告.md).
