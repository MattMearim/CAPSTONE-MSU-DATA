#!/bin/bash
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec "$ROOT/FRIB_Decision_Support/Run Security Checks.command" "$@"
