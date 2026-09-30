#!/usr/bin/env bash
# Every suite, with whatever Python is given or found.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${1:-python3}"
failed=0
for suite in "$HERE"/test_*.py; do
    echo "=== $(basename "$suite")"
    "$PYTHON" "$suite" || failed=1
done
exit $failed
