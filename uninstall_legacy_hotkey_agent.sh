#!/bin/bash
set -euo pipefail

agent_label="com.nyarlathotep.realtime-ton.hotkey"
agent_domain="gui/$(id -u)"
active_plist="$HOME/Library/LaunchAgents/$agent_label.plist"
disabled_plist="$HOME/Library/LaunchAgents/Disabled/$agent_label.plist"
backup_root="$HOME/Library/Application Support/Anotime/LaunchAgent Backups"
backup_dir="$backup_root/$(date +%Y%m%d-%H%M%S)"
moved_any=false

# Either form may be needed depending on how the historical agent was loaded.
/bin/launchctl bootout "$agent_domain/$agent_label" >/dev/null 2>&1 || true
if [[ -f "$active_plist" ]]; then
    /bin/launchctl bootout "$agent_domain" "$active_plist" >/dev/null 2>&1 || true
fi

if [[ -f "$active_plist" ]]; then
    /bin/mkdir -p "$backup_dir"
    /bin/mv "$active_plist" "$backup_dir/active-$agent_label.plist"
    moved_any=true
fi

if [[ -f "$disabled_plist" ]]; then
    /bin/mkdir -p "$backup_dir"
    /bin/mv "$disabled_plist" "$backup_dir/disabled-$agent_label.plist"
    moved_any=true
fi

if /bin/launchctl print "$agent_domain/$agent_label" >/dev/null 2>&1; then
    echo "Legacy hotkey LaunchAgent is still loaded." >&2
    exit 1
fi

if [[ "$moved_any" == true ]]; then
    echo "Legacy hotkey LaunchAgent unloaded; plist backups: $backup_dir"
else
    echo "Legacy hotkey LaunchAgent was already absent."
fi
