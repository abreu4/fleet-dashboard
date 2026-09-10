#!/bin/bash
set -euo pipefail
LABEL="com.tiago.fleet-dashboard"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "removed $LABEL"
