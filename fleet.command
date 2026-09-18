#!/bin/bash
# Open the board in its own chromeless window, sized for a side panel.
#   fleet.command [PORT]      build the app if stale, then open it
#   fleet.command --build     build only (install.sh calls this)
BUILD_ONLY=0
if [ "${1:-}" = "--build" ]; then BUILD_ONLY=1; shift; fi
PORT="${1:-8787}"
URL="http://127.0.0.1:$PORT"
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/Fleet Dashboard.app"
BROWSER="$APP/Contents/MacOS/FleetDashboard"
ICON="$APP/Contents/Resources/AppIcon.icns"
BROWSER_SOURCE="$HERE/fleet-browser.swift"
ICON_SOURCE="$HERE/fleet-icon.swift"
PLIST_SOURCE="$HERE/fleet-browser.plist"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Chrome executes Cmd-T before a web page sees the key event. The small WebKit
# shell gives this dashboard its own application menu, so Cmd-T and the tab
# cycling shortcuts belong to the dashboard. Build it lazily so install.sh
# remains architecture-independent and a copied runtime stays self-contained.
# The bundle is a visible, ordinary app: install.sh links it onto the Desktop,
# and a double-click there opens the board (starting it if it is down).
if command -v xcrun >/dev/null 2>&1 && [ -f "$BROWSER_SOURCE" ] && [ -f "$PLIST_SOURCE" ]; then
  if [ ! -x "$BROWSER" ] || [ "$BROWSER_SOURCE" -nt "$BROWSER" ] || [ "$PLIST_SOURCE" -nt "$BROWSER" ]; then
    mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
    cp "$PLIST_SOURCE" "$APP/Contents/Info.plist"
    xcrun swiftc -O -framework Cocoa -framework WebKit \
      "$BROWSER_SOURCE" -o "$BROWSER.new" >/dev/null 2>&1 && mv "$BROWSER.new" "$BROWSER"
  fi
  # The icon is drawn by a second small program rather than kept as a binary
  # in the repository; it follows its source the same way the shell does.
  if [ -f "$ICON_SOURCE" ] && { [ ! -f "$ICON" ] || [ "$ICON_SOURCE" -nt "$ICON" ]; }; then
    mkdir -p "$APP/Contents/Resources"
    ICON_BUILD="$(mktemp -d)"
    xcrun swiftc -O -framework Cocoa "$ICON_SOURCE" -o "$ICON_BUILD/fleet-icon" >/dev/null 2>&1 \
      && "$ICON_BUILD/fleet-icon" "$ICON" >/dev/null 2>&1
    rm -rf "$ICON_BUILD"
    # Finder and the Dock cache icons by bundle; tell LaunchServices it changed.
    touch "$APP"
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
      -f "$APP" >/dev/null 2>&1 || true
  fi
  # The bundle used to be hidden as .fleet-browser.app; one visible app is enough.
  rm -rf "$HERE/.fleet-browser.app" "$HERE/.fleet-browser" "$HERE/.fleet-browser.new"
fi

if [ "$BUILD_ONLY" = 1 ]; then
  [ -x "$BROWSER" ] || { echo "could not build $APP (is Xcode's command line tools installed?)" >&2; exit 1; }
  exit 0
fi

if [ -x "$BROWSER" ]; then
  # LaunchServices, rather than this short-lived shell, owns the app process.
  # Reopening the command raises the existing dashboard instead of leaving a
  # trail of browser processes behind.
  open "$APP" --args "$URL"
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
