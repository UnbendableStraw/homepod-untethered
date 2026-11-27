#!/usr/bin/env bash
#
# Run every check for the tools/ contributions: the findings validator, both
# unittest suites, and — on macOS — the APFS gold check against a throwaway
# real APFS image. Zero third-party dependencies; needs Python 3.11+.
#
#   tools/run_checks.sh
#
# Suitable for CI. The gold check is skipped automatically off macOS (it needs
# hdiutil to mint a real APFS container); everything else is portable.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

echo "== findings: validate registry =="
python3 tools/findings/validate.py

echo "== findings: unit tests =="
python3 -m unittest discover -s tools/findings

echo "== apfs: unit tests =="
python3 -m unittest discover -s tools/apfs

if [ "$(uname)" = "Darwin" ] && command -v hdiutil >/dev/null 2>&1; then
  echo "== apfs: gold check against real APFS objects =="
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' EXIT
  img="$tmpdir/gold.dmg"
  hdiutil create -size 16m -fs APFS -volname GOLD -layout GPTSPUD "$img" >/dev/null
  APFS_GOLD_OBJECT="$img" python3 -m unittest discover -s tools/apfs
else
  echo "== apfs: gold check SKIPPED (not macOS / no hdiutil) =="
fi

echo "ALL CHECKS PASSED"
