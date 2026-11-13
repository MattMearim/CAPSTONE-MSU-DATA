#!/bin/bash
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
export FRIB_CONFIG_DIR="$ROOT/FRIB_Decision_Support/config"
export FRIB_DATA_DIR="$ROOT/Demo_Workspace_AI"
export FRIB_EMBEDDING_PROVIDER=sentence_transformers
export FRIB_EMBEDDING_MODEL=all-MiniLM-L6-v2
export FRIB_VECTOR_PROVIDER=sqlite
echo "Starting fictional data with real local AI in Demo_Workspace_AI."
"$ROOT/FRIB_Decision_Support/scripts/start_unix.sh" --local-ai "$@"
status=$?
if [ "$status" -ne 0 ]; then
    echo "FRIB stopped with exit code $status. See the message above and FRIB_Decision_Support/.frib/setup.log."
fi
if [ -t 0 ] && [ "${FRIB_NO_PAUSE:-0}" != 1 ]; then
    read -r -p "Press Return to close this window..." _
fi
exit "$status"
