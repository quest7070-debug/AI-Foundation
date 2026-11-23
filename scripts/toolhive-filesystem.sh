#!/bin/sh
set -eu
ROOT="${AI_FOUNDATION_TOOLHIVE_ROOT:-/tmp/ai-foundation-toolhive}"
NAME="${AI_FOUNDATION_TOOLHIVE_NAME:-ai-foundation-fs}"
EXPECTED_DIGEST="${AI_FOUNDATION_TOOLHIVE_DIGEST:-sha256:720393842ef8b0f33713a42e2eebda51ff600756c19d53e1244645ec59496fef}"
THV="${AI_FOUNDATION_THV:-$(cd "$(dirname "$0")/.." && pwd)/.tools/toolhive/thv}"
mkdir -p "$ROOT"
case "${1:-ensure}" in
  ensure)
    if "$THV" status "$NAME" 2>/dev/null | grep -q 'Status: *running'; then exit 0; fi
    "$THV" rm "$NAME" >/dev/null 2>&1 || true
    actual="$(docker image inspect docker.io/mcp/filesystem:1.0.2 --format '{{.Id}}' 2>/dev/null || true)"
    [ "$actual" = "$EXPECTED_DIGEST" ] || { echo "filesystem image digest mismatch" >&2; exit 1; }
    "$THV" run io.github.stacklok/filesystem --name "$NAME" --isolate-network --image-verification warn --enable-audit -v "$ROOT:/projects" >/tmp/ai-foundation-toolhive-run.log 2>&1 &
    i=0
    while [ "$i" -lt 30 ]; do
      "$THV" status "$NAME" 2>/dev/null | grep -q 'Status: *running' && exit 0
      i=$((i+1)); sleep 1
    done
    echo "ToolHive workload did not become running" >&2; exit 1 ;;
  stop)
    if ! "$THV" status "$NAME" 2>/dev/null | grep -q 'Status: *running'; then exit 0; fi
    "$THV" stop "$NAME" >/tmp/ai-foundation-toolhive-stop.log 2>&1 & pid=$!
    i=0; while [ "$i" -lt 15 ]; do
      "$THV" status "$NAME" 2>/dev/null | grep -q 'Status: *running' || exit 0
      i=$((i+1)); sleep 1
    done
    kill "$pid" 2>/dev/null || true
    echo "ToolHive workload did not stop in time" >&2; exit 1 ;;
  remove) "$THV" rm "$NAME" ;;
  status) "$THV" status "$NAME" ;;
  *) echo "usage: $0 {ensure|stop|remove|status}" >&2; exit 2 ;;
esac
