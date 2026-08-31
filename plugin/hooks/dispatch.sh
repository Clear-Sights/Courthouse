#!/usr/bin/env bash
# Courthouse demo mode. Observability only: always exit 0, always print an object.
# `${CLAUDE_PLUGIN_ROOT}` is set by the host; the fallback keeps a direct run working.
set -u
root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
"${COURTHOUSE_PYTHON:-python3}" "${root}/hooks/demo_hook.py" 2>/dev/null || echo '{}'
exit 0
