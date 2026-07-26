# RareLink Physical Site Agent reliability contract

This document describes the hospital-local reliability and fail-closed boundary.
The Site Agent does not open, copy, upload, or summarize medical images. It
reads an already approved dataset receipt through the separate site-data
validator and returns only allow-listed aggregate evidence.

## Mandatory preflight

`start` and `recover` are rejected with HTTP 503 unless all seven checks pass:

1. at least one NVIDIA GPU is visible and has the configured free-memory floor;
2. free system memory meets the configured percentage;
3. free artifact-volume space meets the configured percentage;
4. the reviewed Python dependencies are installed;
5. the public client certificate is currently valid, remains valid for the
   configured minimum number of days, is not a symlink, is below the approved
   startup-kit root, and neither it nor its directory chain is group/world
   writable;
6. the local dataset receipt verifies against the local manifest;
7. the provisioned NVFLARE startup directory exists.

The certificate check reads the public certificate only. It does not locate,
open, hash, log, or export a private key. Responses never contain local paths,
certificate subjects, patient identifiers, or secret material.

Relevant environment settings:

- `RARELINK_SITE_AGENT_CERTIFICATE_MIN_VALID_DAYS` — default `14`;
- `RARELINK_SITE_AGENT_REQUIRE_CERTIFICATE_UNDER_STARTUP_KIT` — default `true`;
- `RARELINK_SITE_AGENT_REQUIRED_GPU_FREE_MEMORY_MIB` — default `1024`;
- `RARELINK_SITE_AGENT_REQUIRED_FREE_MEMORY_PERCENT` — default `15`;
- `RARELINK_SITE_AGENT_REQUIRED_FREE_DISK_PERCENT` — default `10`.

## Task recovery and idempotency

The SQLite task store uses `(task_id, round_id)` as its unique key and is mode
`0600`. Repeating an accepted action returns the existing record and does not
run the executor twice. A reused key with another contract hash or total-round
count is rejected.

After an Agent process restart:

- unfinished `STARTING`, `STOPPING`, or `RECOVERING` transitions become
  `FAILED` and require an explicit recovery decision;
- a `RUNNING` systemd task is retained only when `systemctl is-active` confirms
  that the reviewed NVFLARE unit is still active;
- an unconfirmed task becomes `FAILED`; recovery uses `systemctl restart` and
  never constructs a shell command from API input.

Stopping remains available when resource preflight fails so an operator can
always halt a task safely.

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
  tests/test_site_agent.py tests/test_site_agent_reliability.py
.venv/bin/python -m pytest -q tests/test_site_agent.py \
  tests/test_site_agent_reliability.py tests/test_site_executor.py \
  tests/test_site_heartbeat_forwarder.py
```

Negative tests cover expired, future, near-expiry, symlinked, out-of-root and
writable certificates; low GPU memory; failed GPU/memory/disk/certificate
preflight; duplicate task actions; missing executor state after restart;
disconnected forwarding; backoff persistence; stale heartbeat replacement; and
rejection of unreviewed payload fields.
