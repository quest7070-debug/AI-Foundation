# Disaster reconstruction runbook — Darwin/arm64

This runbook is the supported-host reconstruction sequence. It composes existing Foundation/OSS boundaries; it does not grant new authority.

## 1. Source and dependency reconstruction
1. Clone the canonical GitHub repository into a clean checkout.
2. Run `scripts/bootstrap.sh`. It requires `uv`, resolves Python 3.12, uses the committed lockfile with `--frozen`, installs declared dev/remote extras, and acquires the pinned official Cedar CLI with SHA-256 verification.
3. Run `scripts/bootstrap-toolhive.sh` for the pinned ToolHive boundary. Unsupported platform/version fails closed.
4. Run the deterministic test suite before any runtime activation.

## 2. Durable Foundation state
Use the existing `ai_foundation.productization.backup()` / `restore(..., relocate_config=True)` boundary. SQLite is captured through the SQLite backup API and every restored artifact is manifest/hash verified. `scripts/dr_readonly_probe.py` proves the currently readable canonical state can be snapshotted and restored into a disposable root without mutating the source.

Raw credentials are deliberately not part of Foundation backup generations. Restored provider metadata does not restore authority.

## 3. Credentials
On a rebuilt macOS host, re-provision required credentials through the native macOS Keychain-backed onboarding/credential paths. Never copy raw credentials into Git, config, backup manifests, command arguments, logs, or this runbook. Credential presence must be re-read through the native credential boundary before provider execution is considered ready. Revoked/missing credentials remain unavailable; recovery must not invent them.

## 4. Host runtime materialization
Tracked launchd files are host-neutral templates. Render them with `scripts/render_launchd_plist.py` using explicit checkout, config and log paths; do not hand-edit owner-specific absolute paths into Git. Materialization and launchctl activation are host operations and must be followed by readback.

Externally owned services remain externally owned: LibreChat/Mongo/Meili, Hatchet/Postgres, llama-swap and ToolHive are not reconstructed by copying their live internals into Foundation. Restore/provision them through their documented owner/runtime boundary, then verify Foundation integration.

## 5. Acceptance order
1. `scripts/runtime_drift_audit.py` must pass on the reconstructed canonical runtime.
2. Operator/config/database/native-secret presence and service-health readback must pass without exposing raw secrets.
3. Full deterministic regression must pass.
4. Representative physical path must pass: LibreChat -> foundation-auto -> Agent-selected bounded capability -> execution -> independent readback/evidence -> final response.
5. A restored VERIFIED effect must remain VERIFIED and must not be blindly replayed.

Do not call the ultimate disaster-reconstruction gate complete until a genuinely rebuilt supported host has passed steps 1–5. A disposable clone/restore probe proves deterministic reconstruction and durable-state readability, not external credential/service reconstruction by itself.
