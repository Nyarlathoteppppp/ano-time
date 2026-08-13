#!/bin/bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")" && pwd)"
python_path="$project_root/.venv-pyside/bin/python"
agent_label="com.nyarlathotep.realtime-ton.hotkey"
agent_plist="$HOME/Library/LaunchAgents/$agent_label.plist"
agent_domain="gui/$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents"
if [ ! -x "$python_path" ]; then
    echo "[ERROR] PySide6 environment is missing: $python_path"
    echo "Run ./install_mac.sh first."
    exit 1
fi
if [ ! -f "$agent_plist" ]; then
    /usr/bin/plutil -create xml1 "$agent_plist"
fi

/usr/libexec/PlistBuddy -c "Clear dict" "$agent_plist"
/usr/libexec/PlistBuddy -c "Add :Label string $agent_label" "$agent_plist"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments array" "$agent_plist"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments:0 string $python_path" "$agent_plist"
/usr/libexec/PlistBuddy -c "Add :ProgramArguments:1 string $project_root/hotkey_daemon.py" "$agent_plist"
/usr/libexec/PlistBuddy -c "Add :WorkingDirectory string $project_root" "$agent_plist"
/usr/libexec/PlistBuddy -c "Add :RunAtLoad bool true" "$agent_plist"
/usr/libexec/PlistBuddy -c "Add :KeepAlive bool true" "$agent_plist"
/usr/libexec/PlistBuddy -c "Add :ProcessType string Interactive" "$agent_plist"
/usr/libexec/PlistBuddy -c "Add :StandardOutPath string /tmp/realtime-ton-hotkey.log" "$agent_plist"
/usr/libexec/PlistBuddy -c "Add :StandardErrorPath string /tmp/realtime-ton-hotkey.log" "$agent_plist"

/bin/launchctl bootout "$agent_domain" "$agent_plist" >/dev/null 2>&1 || true
/bin/launchctl bootstrap "$agent_domain" "$agent_plist"
/bin/launchctl kickstart -k "$agent_domain/$agent_label"

echo "Installed hotkey agent: $agent_label"
