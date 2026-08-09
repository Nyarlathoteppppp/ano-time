#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    exit 1
fi

state_path="/tmp/realtime-ton-version"
log_path="/tmp/realtime-ton.log"
current_version="$({
    git rev-parse HEAD 2>/dev/null || true
    find . -maxdepth 1 \( -name '*.py' -o -name '*.sh' -o -name '*.applescript' \) \
        -exec stat -f '%m %N' {} + | sort
} | shasum -a 256 | awk '{print $1}')"
previous_version="$(test -f "$state_path" && sed -n '1p' "$state_path" || true)"

# One-time migration from the old PID-only launcher. Kill only a verified
# dashboard process, never an unrelated process that reused the PID.
legacy_pid_path="/tmp/realtime-ton.pid"
if [ ! -f "$state_path" ] && [ -f "$legacy_pid_path" ]; then
    legacy_pid="$(sed -n '1p' "$legacy_pid_path")"
    legacy_command="$(ps -p "$legacy_pid" -o command= 2>/dev/null || true)"
    if [[ "$legacy_pid" =~ ^[0-9]+$ ]] && [[ "$legacy_command" == *"realtime-ton"* || "$legacy_command" == *"dashboard.py"* ]]; then
        kill -TERM "$legacy_pid" 2>/dev/null || true
        /bin/sleep 0.4
    fi
    rm -f "$legacy_pid_path"
fi

if [ -n "$previous_version" ] && [ "$previous_version" != "$current_version" ]; then
    .venv/bin/python dashboard.py --quit-existing >/dev/null 2>&1 || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        .venv/bin/python dashboard.py --quit-existing >/dev/null 2>&1 || break
        /bin/sleep 0.1
    done
fi

printf '%s\n' "$current_version" > "$state_path"
# The AppleScript launcher must return immediately; blocking its main thread
# makes Finder report the wrapper app as unresponsive. The dashboard remains a
# resident single instance and owns its own global-shortcut lifecycle.
nohup ./start_mac.sh > "$log_path" 2>&1 < /dev/null &
