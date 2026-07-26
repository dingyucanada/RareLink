# RareLink Physical Site Agent reliability contract

This document describes the hospital-local reliability and fail-closed boundary.
The Site Agent does not open, copy, upload, or summarize medical images. It
reads an already approved dataset receipt through the separate site-data
validator and returns only allow-listed aggregate evidence.

## Mandatory preflight

`start` and `recover` are rejected with HTTP 503 unless all eight check
categories pass:

1. at least one NVIDIA GPU is visible, has the configured free-memory floor,
   and, when reported by the driver, remains below the configured temperature
   limit;
2. normalized one-minute CPU load is below the configured limit;
3. free system memory meets the configured percentage;
4. free artifact-volume space meets the configured percentage;
5. the reviewed Python dependencies are installed and summarized by a stable
   version-contract SHA-256;
6. the public client certificate is currently valid, remains valid for the
   configured minimum number of days, is not a symlink, is below the approved
   startup-kit root, and neither it nor its directory chain is group/world
   writable;
7. the local dataset receipt verifies against the local manifest;
8. the provisioned NVFLARE startup directory exists.

The certificate check reads the public certificate only. It does not locate,
open, hash, log, or export a private key. Responses never contain local paths,
certificate subjects, patient identifiers, or secret material.

Relevant environment settings:

- `RARELINK_SITE_AGENT_CERTIFICATE_MIN_VALID_DAYS` — default `14`;
- `RARELINK_SITE_AGENT_REQUIRE_CERTIFICATE_UNDER_STARTUP_KIT` — default `true`;
- `RARELINK_SITE_AGENT_REQUIRED_GPU_FREE_MEMORY_MIB` — default `1024`;
- `RARELINK_SITE_AGENT_MAXIMUM_GPU_TEMPERATURE_C` — default `85`;
- `RARELINK_SITE_AGENT_MAXIMUM_CPU_LOAD_PERCENT` — default `90`;
- `RARELINK_SITE_AGENT_REQUIRED_FREE_MEMORY_PERCENT` — default `15`;
- `RARELINK_SITE_AGENT_REQUIRED_FREE_DISK_PERCENT` — default `10`.

GPU evidence contains the allow-listed device name, driver version, supported
CUDA version, total/free memory, and temperature. It excludes GPU UUIDs,
serials, hostnames, processes, command output, and account data.

## Offline certificate trust

The following optional local policy turns a leaf validity check into a complete
offline trust decision:

- `RARELINK_SITE_AGENT_CERTIFICATE_CA_BUNDLE`;
- `RARELINK_SITE_AGENT_REQUIRE_CERTIFICATE_CHAIN=true`;
- `RARELINK_SITE_AGENT_CERTIFICATE_EXPECTED_IDENTITY`;
- `RARELINK_SITE_AGENT_CERTIFICATE_CRL_FILE`;
- `RARELINK_SITE_AGENT_REQUIRE_CERTIFICATE_CRL=true`.

The Agent verifies every public-certificate signature to a CA certificate in
the pinned bundle, CA validity and Basic Constraints, exact SAN/CN site
identity, CRL issuer/signature/freshness, and the leaf serial against the CRL.
The CA bundle and CRL are local, read-only public material. Online OCSP fetching
is deliberately outside the Site Agent: hospital PKI operations must obtain and
refresh approved revocation material without giving this service unrestricted
network access.

## Task recovery and idempotency

The SQLite task store uses `(task_id, round_id)` as its unique key and is mode
`0600`. Repeating an accepted action returns the existing record and does not
run the executor twice. A reused key with another contract hash or total-round
count is rejected.

After an Agent process restart:

- unfinished `STARTING`, `PAUSING`, `STOPPING`, or `RECOVERING` transitions become
  `FAILED` and require an explicit recovery decision;
- a `RUNNING` systemd task is retained only when `systemctl is-active` confirms
  that the reviewed NVFLARE unit is still active;
- an unconfirmed task becomes `FAILED`; stopped/failed recovery uses
  `systemctl restart`, paused recovery uses fixed-unit `SIGCONT`, and neither
  path constructs a shell command from API input.

Stopping remains available when resource preflight fails so an operator can
always halt a task safely.

## Pause and checkpoint recovery

`POST /v1/tasks/pause` is a distinct, idempotent state transition. The approved
systemd executor sends `SIGSTOP` using a fixed service unit and resumes a paused
unit with `SIGCONT`; task IDs never enter a shell command. A repeated pause of
an already paused task returns the existing receipt.

For recoverable production jobs configure:

- `RARELINK_SITE_AGENT_CHECKPOINT_ROOT`;
- `RARELINK_SITE_AGENT_CHECKPOINT_RECEIPT`;
- `RARELINK_SITE_AGENT_REQUIRE_CHECKPOINT_FOR_PAUSE=true`;
- `RARELINK_SITE_AGENT_REQUIRE_CHECKPOINT_FOR_RECOVER=true`.

Before pause or recovery, the Agent validates an allow-listed local checkpoint
receipt, task/round/contract binding, relative path containment, file
permissions, size, and SHA-256. Only checkpoint ID, hashes, size, timestamps and
verification flags enter the task record. The local checkpoint path and model
content are not exported. A missing, stale, mismatched, symlinked, moved or
modified checkpoint prevents the signal/recovery action.

Task responses now include `training_stage`, active runtime seconds, current
resource check statuses and verified checkpoint metadata. Transition receipts
bind the checkpoint SHA-256 so later record tampering is detectable.

## Heartbeat delivery

The forwarder persists one allow-listed, signed heartbeat envelope in a
mode-`0600` SQLite outbox. It does not persist the Site Agent bearer token,
HMAC key, demo token, arbitrary response fields, or patient data.

On a network failure it:

1. retains the same heartbeat ID;
2. retries with bounded exponential backoff;
3. preserves pending state across process restarts;
4. treats the coordinator's duplicate-heartbeat response as accepted;
5. discards an envelope before it exceeds the configured replay window, then
   obtains a newly signed heartbeat.

Forwarder options:

- `--state-database` — defaults to
  `/var/lib/rarelink/site-agent/heartbeat-forwarder.sqlite3`;
- `--maximum-backoff` — defaults to 300 seconds;
- `--maximum-envelope-age` — defaults to 240 seconds and must remain below the
  coordinator heartbeat replay window.

## Automated acceptance

Run:

```bash
.venv/bin/ruff check rarelink/site_agent scripts/push_site_heartbeat.py \
  tests/test_site_agent.py tests/test_site_agent_reliability.py \
  tests/test_site_agent_advanced.py
.venv/bin/python -m pytest -q tests/test_site_agent.py \
  tests/test_site_agent_reliability.py tests/test_site_executor.py \
  tests/test_site_heartbeat_forwarder.py tests/test_site_agent_advanced.py
```

Negative tests cover expired, future, near-expiry, symlinked, out-of-root and
writable certificates; low GPU memory; failed GPU/memory/disk/certificate
preflight; duplicate task actions; missing executor state after restart;
disconnected forwarding; backoff persistence; stale heartbeat replacement; and
rejection of unreviewed payload fields. Advanced negative tests add excessive
GPU temperature and CPU load, untrusted/revoked certificates, missing CRLs,
missing or tampered checkpoints, repeated pause, and executor pause failure.
