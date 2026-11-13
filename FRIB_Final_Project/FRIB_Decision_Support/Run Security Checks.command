#!/bin/bash
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
"$ROOT/scripts/run_checks.sh" --security --install-tools "$@"
status=$?
if [ -t 0 ] && [ "${FRIB_NO_PAUSE:-0}" != 1 ]; then
  read -r -p "Checks finished. Press Return to close..." _
fi
exit "$status"
