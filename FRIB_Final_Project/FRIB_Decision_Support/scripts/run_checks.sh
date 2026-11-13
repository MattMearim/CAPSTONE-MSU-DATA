#!/bin/bash
# Shared macOS/Linux entry point; never relies on Finder's working directory.
set -u
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
probe='import sys, struct, ssl, venv, ensurepip, tomllib; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) and struct.calcsize("P") == 8 else 1)'
python=""
if [ -n "${FRIB_PYTHON:-}" ]; then
    if "$FRIB_PYTHON" -c "$probe" >/dev/null 2>&1; then
        python="$FRIB_PYTHON"
    else
        echo "FRIB_PYTHON must point to a working 64-bit Python 3.11, 3.12 or 3.13 with venv and SSL." >&2
        exit 1
    fi
else
    for candidate in python3.13 python3.12 python3.11 python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 /Library/Frameworks/Python.framework/Versions/3.11/bin/python3; do
        if "$candidate" -c "$probe" >/dev/null 2>&1; then
            python="$candidate"
            break
        fi
    done
fi
if [ -z "$python" ]; then
    echo "FRIB needs 64-bit Python 3.11, 3.12 or 3.13. Install Python 3.12 from https://www.python.org/downloads/macos/ and launch again." >&2
    exit 1
fi
cd "$PROJECT" || exit 1
exec "$python" "$PROJECT/scripts/run_tests.py" "$@"
