#!/bin/sh
set -eu

VERSION="${AI_FOUNDATION_TOOLHIVE_VERSION:-0.49.0}"
EXPECTED_VERSION="0.49.0"
EXPECTED_SHA256="b78d8991cb6f3df35a543dd2456c8885ef7e34885517c62051c20443a7a711a0"
ROOT="${AI_FOUNDATION_TOOLHIVE_DIR:-$(cd "$(dirname "$0")/.." && pwd)/.tools/toolhive}"
ARCHIVE="toolhive_${VERSION}_darwin_arm64.tar.gz"
URL="https://github.com/stacklok/toolhive/releases/download/v${VERSION}/${ARCHIVE}"

[ "$VERSION" = "$EXPECTED_VERSION" ] || { echo "unsupported ToolHive version: $VERSION" >&2; exit 1; }
[ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ] || {
  echo "canonical ToolHive bootstrap currently supports darwin/arm64 only" >&2
  exit 1
}

umask 077
mkdir -p "$ROOT"
[ ! -L "$ROOT" ] || { echo "ToolHive owner directory must not be a symlink" >&2; exit 1; }
[ "$(stat -f %u "$ROOT")" = "$(id -u)" ] || { echo "ToolHive owner directory mismatch" >&2; exit 1; }
chmod 700 "$ROOT"
TARGET="$ROOT/thv"
[ ! -L "$TARGET" ] || { echo "ToolHive executable symlink denied" >&2; exit 1; }
if [ -e "$TARGET" ]; then
  if [ -n "${AI_FOUNDATION_TOOLHIVE_DIR:-}" ]; then
    [ -f "$TARGET" ] && [ -x "$TARGET" ] &&
    [ -f "$ROOT/archive.sha256" ] && [ ! -L "$ROOT/archive.sha256" ] &&
    [ -f "$ROOT/executable.sha256" ] && [ ! -L "$ROOT/executable.sha256" ] &&
    [ "$(cat "$ROOT/archive.sha256")" = "$EXPECTED_SHA256" ] &&
    [ "$(shasum -a 256 "$TARGET" | awk '{print $1}')" = "$(cat "$ROOT/executable.sha256")" ] || {
      echo "existing ToolHive executable has no verified pinned archive provenance" >&2
      exit 21
    }
  fi
  current="$("$TARGET" version 2>/dev/null || true)"
  case "$current" in
    *"$VERSION"*) printf '%s\n' "$TARGET"; exit 0 ;;
  esac
  echo "existing ToolHive binary is not pinned version $VERSION" >&2
  exit 22
fi

# No pinned receipt may redirect a write through a stale symlink.
[ ! -L "$ROOT/archive.sha256" ] && [ ! -L "$ROOT/executable.sha256" ] || exit 21
tmp="$(mktemp -d "$ROOT/.bootstrap.XXXXXXXX")"
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
# Retry transient GitHub asset failures, but never download a different
# version, use a mirror, or continue past the exact pinned archive digest.
curl --fail --location --silent --show-error --retry 3 --retry-all-errors \
  --retry-delay 2 --connect-timeout 8 --max-time 90 "$URL" -o "$tmp/$ARCHIVE" || exit 31
actual="$(shasum -a 256 "$tmp/$ARCHIVE" | awk '{print $1}')"
[ "$actual" = "$EXPECTED_SHA256" ] || exit 32

tar -xzf "$tmp/$ARCHIVE" -C "$tmp" || exit 33
# Some signed macOS archives preserve a restrictive source mode; the pinned
# SHA256 (not archive mode) is the trust anchor. Never execute that source
# directly. Copy its fixed-name regular file into owner-private staging.
found="$(find "$tmp" -type f -name thv -print -quit)"
[ -n "$found" ] || exit 34
cp "$found" "$tmp/verified-thv" || exit 35
chmod 0700 "$tmp/verified-thv" || exit 35
# Check only the owner-private staged binary before publication.
version="$("$tmp/verified-thv" version 2>/dev/null || true)"
case "$version" in *"$EXPECTED_VERSION"*) ;; *) exit 36 ;; esac
digest="$(shasum -a 256 "$tmp/verified-thv" | awk '{print $1}')"
[ -n "$digest" ] || exit 35
printf '%s\n' "$EXPECTED_SHA256" > "$tmp/archive.sha256"
printf '%s\n' "$digest" > "$tmp/executable.sha256"
# Publish receipts first and the complete executable LAST. Interrupted
# installation remains retryable rather than leaving an unverified binary.
mv "$tmp/archive.sha256" "$ROOT/archive.sha256" || exit 37
mv "$tmp/executable.sha256" "$ROOT/executable.sha256" || exit 37
mv "$tmp/verified-thv" "$TARGET" || exit 37
printf '%s\n' "$TARGET"
