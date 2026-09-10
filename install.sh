#!/bin/bash
# Deploy the fleet dashboard outside macOS-protected Documents, install its
# Python dependency in an isolated environment, and keep it running at login.
set -euo pipefail

SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="${FLEET_RUNTIME_DIR:-$HOME/.local/share/fleet-dashboard}"
LABEL="com.tiago.fleet-dashboard"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PORT="${1:-8787}"

mkdir -p "$RUNTIME" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

# LaunchAgents do not inherit a terminal application's permission to read
# ~/Documents. Keep a small runtime copy somewhere launchd can always read.
FILES=(README.md actions.py collectors.py dashboard.py fleet.command install.sh
       metrics.py music.py notes.py requirements.txt uninstall.sh ui.html)
if [[ "$SOURCE" != "$RUNTIME" ]]; then
  for file in "${FILES[@]}"; do
    cp -p "$SOURCE/$file" "$RUNTIME/$file"
  done
fi

# ytmusicapi 1.12+ requires Python 3.10. Prefer Homebrew, but accept any modern
# interpreter already installed on the machine.
PYTHON=""
CANDIDATES=(/opt/homebrew/bin/python3 /opt/anaconda3/bin/python3)
if command -v python3 >/dev/null 2>&1; then CANDIDATES+=("$(command -v python3)"); fi
for candidate in "${CANDIDATES[@]}"; do
  if [[ -x "$candidate" ]] && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
    PYTHON="$candidate"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  echo "fleet requires Python 3.10 or newer" >&2
  exit 1
fi

VENV="$RUNTIME/.venv"
if [[ -x "$VENV/bin/python" ]] && \
   ! "$VENV/bin/python" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
  mv "$VENV" "$VENV.python-old.$(date +%Y%m%d%H%M%S)"
fi
if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check \
  -r "$RUNTIME/requirements.txt"
PYTHON="$VENV/bin/python"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>$RUNTIME/dashboard.py</string>
    <string>--port</string>
    <string>$PORT</string>
  </array>
  <key>WorkingDirectory</key><string>$RUNTIME</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/fleet-dashboard.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/fleet-dashboard.log</string>
</dict>
</plist>
PLISTEOF

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"
launchctl kickstart -k "gui/$UID/$LABEL"

echo "installed $LABEL on port $PORT"
echo "runtime:       $RUNTIME"
echo "open it with:  $RUNTIME/fleet.command   (or http://127.0.0.1:$PORT)"
