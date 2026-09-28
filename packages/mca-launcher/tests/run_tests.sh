#!/usr/bin/env bash
# Run every launcher suite with whatever python is on PATH.
#
#     ./run_tests.sh              # system python
#     PYTHON=/path/to/mayapy ./run_tests.sh
#
# The window suite needs PySide6 and skips cleanly without it, so a machine with no Qt still
# gets a useful run out of this.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${PYTHON:-python3}"
status=0

for suite in test_core.py test_api.py test_ui_window.py; do
    echo
    echo "=== $suite ==="
    "$python_bin" "$here/$suite" || status=1
done

echo
if [ "$status" -eq 0 ]; then echo "All suites passed."; else echo "Something failed."; fi
exit "$status"
