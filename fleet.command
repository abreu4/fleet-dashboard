#!/bin/bash
# Open the board in its own chromeless window, sized for a side panel.
PORT="${1:-8787}"
URL="http://127.0.0.1:$PORT"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ -x "$CHROME" ]; then
  # Called through the binary rather than `open -na`. The -n forced a whole new
  # Chrome instance per launch, and every one of them stayed: 37 processes and
  # 923MB had accumulated, four of them browser shells holding no window at all.
  # Run directly and Chrome's singleton hands the command line to the instance
  # already running, so a relaunch costs one window instead of one browser.
  "$CHROME" --app="$URL" --window-size=900,1000 --window-position=0,0 >/dev/null 2>&1 &
else
  open "$URL"
fi
