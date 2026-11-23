# AI Foundation operations baseline

## Preflight
Load the versioned FoundationConfig and run the read-only preflight before any install/update/recovery mutation. A failed config, unreadable DB, unsupported native secret store, or missing required credential is not ready. Unsupported platforms must not silently downgrade security.

## Backup
Back up every configured Foundation SQLite store through SQLite's backup API,
including custom filenames without `.db`/`.sqlite` suffixes. This captures
committed WAL state without copying an open database's main file alone.
Trace/preferences/configuration retain their existing owner-specific copy path.
Each published generation includes `manifest.json` with schema version and
SHA-256 digests. Capture consistency is **per-file snapshot**, not one global
transaction across all stores.

`verify_backup(path)` is the shared read-only verifier used before backup
publication, restore staging and backup-generation retention. It checks bounded,
duplicate-free manifest/config JSON, the supported v1 schema, confined regular
files, streaming SHA-256, valid FoundationConfig and SQLite `quick_check` for
the configured stores present in the snapshot. SQLite checking uses read-only
immutable mode and creates no journal/WAL sidecars. Legacy v1 generations
without capture metadata remain supported; present capture metadata must
describe a finished per-file snapshot.

Run content verification without restoring or pruning:

```sh
PYTHONPATH=src .venv/bin/python scripts/verify_backup.py /path/to/backup
```

Exit 0 reports `CONTENT_VERIFIED` and file count. Exit 2 reports
`INVALID_BACKUP` with a bounded reason code; no content, credentials or source
paths are printed. Hashes prove self-consistency, not source authenticity or
completeness relative to a running host. Optional stores may be absent on a
fresh host. Application/domain restore readback is still required before a
generation is accepted for actual recovery.

Retention uses the same verifier: unknown-schema, incomplete, corrupt or
unreadable generations never displace the retained verified generations.
Retention counts must be integers of at least one. Planning remains read-only;
deletion still requires the existing explicit BackupMaintenance owner action.

## Restore / disaster recovery
Restore only into an empty/staged destination first. `restore()` applies the
shared verification contract before creating destination state, then checks
copied content again before atomic publication. After restore, run preflight
and domain readback before switching authority to restored state. Never blindly
replay an EXECUTING/UNCERTAIN external effect; use Guard reconciliation semantics.

## Update / migration
Before migration: preflight, backup, restore-test, then stage the new version. Schema versions are explicit and unknown versions fail closed. Do not modify MultiLLM, Automation Hub, AI Home Server, HumanConsole, M1Remote, or Concept OS as part of Foundation update preparation. Cutover requires authoritative comparison and rollback evidence.

## Credentials
Configuration stores binding names only. Raw credentials remain in the OS-native store. On current M1/macOS, Keychain availability is the verified adapter. Credential rotation means provision new native item/binding, preflight it, change metadata binding through an approved configuration change, verify, then retire the old item.

## Incident handling
Stop new effects if durable state, policy revision, credential availability, containment, or evidence is uncertain. Preserve DB/trace evidence. Prefer reconciliation/readback over retry. Treat missing evidence as not verified.

## Continuous health observation

The existing LongTermHealthLoop owns periodic storage/log/WAL observation.
Only one tick runs at a time and repeated start calls reuse its live worker.
Check exceptions produce an unhealthy `health-check` signal; evidence-write
exceptions produce an unhealthy `health-evidence` signal. Exception text,
paths and request contents are not copied into those diagnostics. The loop
keeps its next scheduled observation; normal status returns only after a
new valid check and, when configured, successful evidence persistence.

Live trust requires both a fresh wall-clock timestamp and a fresh monotonic
elapsed interval. Non-finite/invalid clocks, stopped/dead workers and expired
evidence cannot advertise cached success. Stop prevents another scheduled
check; already-running I/O is not forcibly interrupted. If I/O stalls, cached
evidence still ages out through the same freshness check.

The saved single-record history has bounded JSON, finite numeric timestamps,
nonempty unique signals, actual booleans and a consistent aggregate result.
Duplicate fields, malformed/oversized records and truthy strings are rejected.
Writes use a private unique temporary file, fsync, atomic replacement and
readback. A write failure may leave the previous historical file intact;
Operator live status uses the current in-memory failure, not that old record.
A new process must observe again before claiming live health.

Observation and its retries do not restart services, prune state, dispatch
work or grant execution authority. Existing Operator notices/service probes
present unhealthy or stale monitoring through their current paths.
