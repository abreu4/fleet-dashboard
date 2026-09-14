#!/bin/bash
# Open the board in its own chromeless window, sized for a side panel.
PORT="${1:-8787}"
URL="http://127.0.0.1:$PORT"
HERE="$(cd "$(dirname "$0")" && pwd)"
BROWSER="$HERE/.fleet-browser"
BROWSER_SOURCE="$HERE/fleet-browser.swift"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Chrome executes Cmd-T before a web page sees the key event. The small WebKit
# shell gives this dashboard its own application menu, so Cmd-T and the tab
# cycling shortcuts belong to the dashboard. Build it lazily so install.sh
# remains architecture-independent and a copied runtime stays self-contained.
if [ -f "$BROWSER_SOURCE" ] && { [ ! -x "$BROWSER" ] || [ "$BROWSER_SOURCE" -nt "$BROWSER" ]; }; then
  if command -v xcrun >/dev/null 2>&1; then
    xcrun swiftc -O -framework Cocoa -framework WebKit \
      "$BROWSER_SOURCE" -o "$BROWSER.new" >/dev/null 2>&1 && mv "$BROWSER.new" "$BROWSER"
  fi
fi

if [ -x "$BROWSER" ]; then
  "$BROWSER" "$URL" >/dev/null 2>&1 &
elif [ -x "$CHROME" ]; then
  # Called through the binary rather than `open -na`. The -n forced a whole new
  # Chrome instance per launch, and every one of them stayed: 37 processes and
  # 923MB had accumulated, four of them browser shells holding no window at all.
  # Run directly and Chrome's singleton hands the command line to the instance
  # already running, so a relaunch costs one window instead of one browser.
  "$CHROME" --app="$URL" --window-size=900,1000 --window-position=0,0 >/dev/null 2>&1 &
else
  open "$URL"
fi
