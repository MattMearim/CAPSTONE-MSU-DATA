#!/bin/bash
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
"$ROOT/scripts/start_unix.sh" --test-lab --output "$ROOT/test_lab_results" "$@"
status=$?
if [ "$status" -ne 0 ]; then
    echo "FRIB stopped with exit code $status. See the message above and FRIB_Decision_Support/.frib/setup.log."
fi
if [ -t 0 ] && [ "${FRIB_NO_PAUSE:-0}" != 1 ]; then
    read -r -p "Press Return to close this window..." _
fi
exit "$status"
