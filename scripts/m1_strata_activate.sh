#!/bin/bash
# Owner-local activation from a detached copy of the fetched canonical release.
set -euo pipefail
KEY_MODE="${1:-prompt}"
case "$KEY_MODE" in prompt|--key-stdin|--finish-keychain) ;; *) echo UNSUPPORTED_KEY_MODE >&2; exit 2;; esac
[[ $# -le 1 ]] || { echo UNSUPPORTED_ARGUMENTS >&2; exit 2; }
REPO="$HOME/Develop/AI-Foundation"
cd "$REPO"
PY="$REPO/.venv/bin/python"
[[ -x "$PY" ]] || { echo FOUNDATION_VENV_MISSING >&2; exit 2; }
REV="$(git rev-parse --verify refs/remotes/origin/main^{commit})"
WT="$(mktemp -d "${TMPDIR:-/tmp/}foundation-strata-XXXXXX")"
WT="$(cd "$WT" && pwd -P)"
cleanup() {
  if git worktree list --porcelain | /usr/bin/grep -Fxq "worktree $WT"; then
    git worktree remove "$WT" || echo WORKTREE_CLEANUP_REVIEW_REQUIRED >&2
  else
    rmdir "$WT" 2>/dev/null || true
  fi
}
trap cleanup EXIT
git worktree add --detach "$WT" "$REV"
CONFIG="$("$PY" - <<'PY'
import plistlib
from pathlib import Path
p = Path.home() / 'Library/LaunchAgents/dev.quest7070.ai-foundation.operator.plist'
d = plistlib.loads(p.read_bytes())
a = d['ProgramArguments']
c = Path(a[a.index('--config') + 1])
if not c.is_absolute():
    c = Path(d.get('WorkingDirectory', '/')) / c
print(c.resolve(strict=True))
PY
)"
ARGS=(--config "$CONFIG" --port 18080 --register-api-key)
if [[ "$KEY_MODE" == --finish-keychain ]]; then
  exec_args=("$PY" -B "$WT/scripts/m1_strata_finish_keychain.py" --config "$CONFIG")
  "${exec_args[@]}"
  exit $?
fi
if [[ "$KEY_MODE" == --key-stdin ]]; then ARGS+=(--key-stdin); fi
"$PY" -B "$WT/scripts/m1_strata_local_first_setup.py" "${ARGS[@]}"
