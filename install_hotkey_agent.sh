#!/bin/bash
set -euo pipefail

agent_label="com.nyarlathotep.realtime-ton.hotkey"
agent_plist="$HOME/Library/LaunchAgents/$agent_label.plist"
agent_domain="gui/$(id -u)"

/bin/launchctl bootout "$agent_domain" "$agent_plist" >/dev/null 2>&1 || true
if [ -f "$agent_plist" ]; then
    echo "Stopped legacy hotkey agent: $agent_label"
    echo "The existing plist was left unchanged."
else
    echo "Legacy hotkey agent is already disabled."
fi

echo "Control + S is available to other applications."
