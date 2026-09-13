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
# Every module dashboard.py imports (directly or through actions/terminal)
# has to be here, or the copy starts and dies on an ImportError; vendor/ holds
# xterm, the fonts and the sound bank the page loads from /vendor/.
FILES=(README.md actions.py aliases.py collectors.py dashboard.py fleet-name
       fleet.command flush.py install.sh instance.py iterm_link.py metrics.py
       music.py notes.py requirements.txt sunset.py terminal.py uninstall.sh
       ui.html)
if [[ "$SOURCE" != "$RUNTIME" ]]; then
  for file in "${FILES[@]}"; do
    cp -p "$SOURCE/$file" "$RUNTIME/$file"
  done
  rm -rf "$RUNTIME/vendor"
  cp -Rp "$SOURCE/vendor" "$RUNTIME/vendor"
  # A stale bytecode cache from an older copy can shadow a fresh module.
  rm -rf "$RUNTIME/__pycache__"
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
    <string>--terminal</string>
    <string>--kiosk</string>
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

# bootout is asynchronous: a bootstrap issued straight after it fails with
# "Input/output error" while launchd is still tearing the old job down, and
# under set -e that left the plist written but never loaded -- a board that
# looks installed and serves nothing. Wait for the job to be gone, and give
# bootstrap a few tries.
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
for _ in $(seq 1 50); do
  launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1 || break
  sleep 0.1
done
loaded=0
for attempt in 1 2 3 4 5; do
  if launchctl bootstrap "gui/$UID" "$PLIST" 2>/dev/null; then loaded=1; break; fi
  sleep 1
done
if [[ "$loaded" != 1 ]]; then
  echo "could not load $LABEL into launchd (see: launchctl bootstrap gui/$UID $PLIST)" >&2
  exit 1
fi

# RunAtLoad already started it; prove the port answers before claiming success.
for _ in $(seq 1 100); do
  curl -sf -m 2 -o /dev/null "http://127.0.0.1:$PORT/api/state" && break
  sleep 0.2
done
if ! curl -sf -m 2 -o /dev/null "http://127.0.0.1:$PORT/api/state"; then
  echo "$LABEL is loaded but nothing answers on port $PORT; see $HOME/Library/Logs/fleet-dashboard.log" >&2
  exit 1
fi

echo "installed $LABEL on port $PORT"
echo "runtime:       $RUNTIME"
echo "open it with:  $RUNTIME/fleet.command   (or http://127.0.0.1:$PORT)"
