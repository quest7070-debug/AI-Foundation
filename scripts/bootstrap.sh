#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
UV=${UV:-$(command -v uv || true)}
VENV=${AI_FOUNDATION_VENV:-$ROOT/.venv}

if [ -z "$UV" ]; then
  echo "error: uv is required for frozen GitHub reconstruction" >&2
  exit 2
fi

if [ "${AI_FOUNDATION_PREFLIGHT_ONLY:-0}" = "1" ]; then
  "$UV" python find 3.12 >/dev/null
  printf 'preflight-ok root=%s venv=%s uv=%s python=3.12\n' "$ROOT" "$VENV" "$UV"
  exit 0
fi

cd "$ROOT"
"$ROOT/scripts/bootstrap-cedar.sh"
UV_PROJECT_ENVIRONMENT="$VENV" "$UV" sync --frozen --python 3.12 --extra dev --extra remote
"$VENV/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 12); import ai_foundation; print("install-readback-ok python=%d.%d" % sys.version_info[:2])'
