#!/bin/bash
# Open the board in its own chromeless window, sized for a side panel.
PORT="${1:-8787}"
URL="http://127.0.0.1:$PORT"
if [ -d "/Applications/Google Chrome.app" ]; then
  open -na "Google Chrome" --args --app="$URL" --window-size=900,1000 --window-position=0,0
else
  open "$URL"
fi
