#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) archive=cedar-policy-cli-aarch64-apple-darwin.tar.xz ;;
  *) echo 'error: Cedar reconstruction is currently verified only for Darwin arm64' >&2; exit 2 ;;
esac
version=4.13.0
expected=53c3ddc467519a3371919a92da1167fe143d9eb8efe0b29fdde8237fa0fe9cae
url="https://github.com/cedar-policy/cedar/releases/download/cedar-policy-cli-v${version}/${archive}"
dir="$ROOT/.tools/cedar"
cedar="$dir/cedar-policy-cli-aarch64-apple-darwin/cedar"
if [ ! -x "$cedar" ]; then
  mkdir -p "$dir"
  curl --fail --location --silent --show-error "$url" -o "$dir/$archive"
  actual=$(shasum -a 256 "$dir/$archive" | awk '{print $1}')
  [ "$actual" = "$expected" ] || { echo "error: Cedar CLI checksum mismatch: $actual" >&2; exit 3; }
  tar -xJf "$dir/$archive" -C "$dir"
fi
"$cedar" --version
