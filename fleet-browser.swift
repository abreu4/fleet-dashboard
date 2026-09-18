import Cocoa
import WebKit

final class FleetApp: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    private let dashboardURL: URL
    private var window: NSWindow!
    private var webView: WKWebView!
    private var shortcutMonitor: Any?
    private var recoveries = 0
    private var showingPlaceholder = false
    private var boardNavigation: WKNavigation?
    private var watchdog: Timer?
    private var misses = 0

    init(url: URL) {
        dashboardURL = url
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenu()
        installShortcutMonitor()
        installWatchdog()

        let visible = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 900, height: 1000)
        let size = NSSize(width: min(900, visible.width), height: min(1000, visible.height))
        let frame = NSRect(x: visible.minX, y: visible.maxY - size.height,
                           width: size.width, height: size.height)
        window = NSWindow(contentRect: frame,
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "FLEET · agent console"
        window.setFrameAutosaveName("fleet-dashboard")

        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        // This is a dedicated local status board, not an arbitrary web page.
        // Notifications have to survive the automatic reloads used to pick up
        // dashboard updates, so do not put each fresh Web Audio context behind
        // WKWebView's media gesture gate. The page still owns its persisted
        // mute / volume / click-cue controls.
        configuration.mediaTypesRequiringUserActionForPlayback = []
        webView = WKWebView(frame: window.contentView!.bounds, configuration: configuration)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        webView.uiDelegate = self
        // Safari's Develop menu can then attach to this view (Web Inspector ->
        // Timelines), which is how a "the board lags" report gets a recording
        // instead of a guess. Local page in a local shell: nothing to protect.
        if #available(macOS 13.3, *) {
            webView.isInspectable = true
        }
        window.contentView = webView
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        boardNavigation = webView.load(URLRequest(url: dashboardURL))
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let shortcutMonitor {
            NSEvent.removeMonitor(shortcutMonitor)
        }
        watchdog?.invalidate()
    }

    // A page already on screen never navigates when its server dies: the
    // board just goes to its OFFLINE face and stays there. So the shell asks
    // every few seconds whether anyone is home. Three misses in a row is a
    // dead board rather than a restart in progress (install.sh is back in
    // under five seconds); then start the job and reload, which puts the
    // placeholder up and hands the retries to didFailProvisionalNavigation.
    private func installWatchdog() {
        watchdog = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            self?.checkBoard()
        }
    }

    private func checkBoard() {
        var request = URLRequest(url: dashboardURL.appendingPathComponent("api/ping"))
        request.timeoutInterval = 3
        request.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: request) { [weak self] _, response, error in
            DispatchQueue.main.async {
                guard let self else { return }
                // Any answer at all, a 404 from an older board included, means alive.
                if error == nil, response is HTTPURLResponse {
                    self.misses = 0
                    if self.showingPlaceholder && self.recoveries > 40 {
                        self.recoveries = 0
                        self.boardNavigation = self.webView.load(URLRequest(url: self.dashboardURL))
                    }
                    return
                }
                self.misses += 1
                if self.misses == 3 || (self.misses > 3 && self.misses % 6 == 0) {
                    self.startBoard()
                }
                if self.misses == 3 && !self.showingPlaceholder {
                    self.boardNavigation = self.webView.load(URLRequest(url: self.dashboardURL))
                }
            }
        }.resume()
    }

    private func installShortcutMonitor() {
        // WebKit treats Cmd-[ and Cmd-] as browser history before its page gets
        // a keyboard event. A local AppKit monitor runs earlier in dispatch,
        // letting the dashboard own those chords just as the Cmd-T menu item
        // does. Compare produced characters as well as the unmodified ones so
        // keyboard layouts that need Option to type a bracket work too.
        shortcutMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
            guard flags.contains(.command), !flags.contains(.control) else { return event }
            let characters = [event.characters, event.charactersIgnoringModifiers].compactMap { $0 }
            // Command-W belongs to the active embedded terminal, never to the
            // one dashboard window. Exact modifiers preserve the conventional
            // Command-Option-W meaning should the app gain one later.
            if flags == [.command] && characters.contains(where: { $0.lowercased() == "w" }) {
                self?.closeTerminal()
                return nil
            }
            if characters.contains(where: { $0 == "[" }) {
                self?.previousTerminal()
                return nil
            }
            if characters.contains(where: { $0 == "]" }) {
                self?.nextTerminal()
                return nil
            }
            // ANSI bracket key codes cover layouts where Command suppresses
            // the character value before AppKit exposes the event.
            if flags == [.command] && event.keyCode == 33 {
                self?.previousTerminal()
                return nil
            }
            if flags == [.command] && event.keyCode == 30 {
                self?.nextTerminal()
                return nil
            }
            return event
        }
    }

    private func installMenu() {
        let main = NSMenu()
        NSApp.mainMenu = main

        let appItem = NSMenuItem()
        main.addItem(appItem)
        let appMenu = NSMenu()
        appItem.submenu = appMenu
        appMenu.addItem(withTitle: "Quit Fleet Dashboard",
                        action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")

        // Without an Edit menu AppKit has nowhere to route Command-C/V/X/A, so
        // the web view never receives copy:/paste: and the embedded terminals
        // could neither copy a selection nor paste into a prompt. The standard
        // selectors with a nil target go to the first responder -- the WKWebView
        // -- which turns them into the DOM events xterm already handles.
        let editItem = NSMenuItem()
        main.addItem(editItem)
        let editMenu = NSMenu(title: "Edit")
        editItem.submenu = editMenu
        editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = editMenu.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")

        let terminalItem = NSMenuItem()
        main.addItem(terminalItem)
        let terminalMenu = NSMenu(title: "Terminal")
        terminalItem.submenu = terminalMenu
        addCommand("New Terminal", key: "t", action: #selector(newTerminal), to: terminalMenu)
        addCommand("Close Terminal", key: "w", action: #selector(closeTerminal), to: terminalMenu)
        terminalMenu.addItem(.separator())
        addCommand("Previous Terminal", key: "[", action: #selector(previousTerminal), to: terminalMenu)
        addCommand("Next Terminal", key: "]", action: #selector(nextTerminal), to: terminalMenu)

        let viewItem = NSMenuItem()
        main.addItem(viewItem)
        let viewMenu = NSMenu(title: "View")
        viewItem.submenu = viewMenu
        addCommand("Reload", key: "r", action: #selector(reload), to: viewMenu)
        let fullscreen = NSMenuItem(title: "Enter Full Screen",
                                    action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        fullscreen.keyEquivalentModifierMask = [.command, .control]
        viewMenu.addItem(fullscreen)
    }

    private func addCommand(_ title: String, key: String, action: Selector, to menu: NSMenu) {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self
        item.keyEquivalentModifierMask = [.command]
        menu.addItem(item)
    }

    private func run(_ javascript: String) {
        webView?.evaluateJavaScript(javascript, completionHandler: nil)
    }

    @objc private func newTerminal() {
        run("window.fleetNewTerminal?.()")
    }

    @objc private func closeTerminal() {
        run("window.fleetCloseTerminal?.()")
    }

    @objc private func previousTerminal() {
        run("window.fleetCycleTerminal?.(-1)")
    }

    @objc private func nextTerminal() {
        run("window.fleetCycleTerminal?.(1)")
    }

    @objc private func reload() {
        webView?.reload()
    }

    // The board is a launchd job the app does not own; a Desktop double-click
    // must still work when that job is down (a restart that never finished,
    // a fresh login before it came up). Connection refused means "start it
    // and try again", not an error page. bootstrap is a no-op if the job is
    // loaded, kickstart a no-op if it is running -- neither touches a live
    // board or the terminals it holds.
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        let failure = error as NSError
        guard failure.domain == NSURLErrorDomain, failure.code != NSURLErrorCancelled else { return }
        recoveries += 1
        if !showingPlaceholder {
            showingPlaceholder = true
            webView.loadHTMLString(placeholder, baseURL: dashboardURL)
        }
        if recoveries == 1 || recoveries % 4 == 0 {
            startBoard()
        }
        if recoveries <= 40 {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
                guard let self else { return }
                self.boardNavigation = self.webView.load(URLRequest(url: self.dashboardURL))
            }
        } else {
            run("document.getElementById('note').textContent = "
                + "'The board is not answering on \(dashboardURL.absoluteString). "
                + "See ~/Library/Logs/fleet-dashboard.log, or run install.sh.'")
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // The placeholder finishes too, under the same base URL; only the
        // board's own navigation ends a recovery.
        if navigation === boardNavigation {
            showingPlaceholder = false
            recoveries = 0
        }
    }

    private func startBoard() {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let domain = "gui/\(getuid())"
        let label = "com.tiago.fleet-dashboard"
        let plist = "\(home)/Library/LaunchAgents/\(label).plist"
        DispatchQueue.global(qos: .userInitiated).async {
            for arguments in [["bootstrap", domain, plist], ["kickstart", "\(domain)/\(label)"]] {
                let launchctl = Process()
                launchctl.executableURL = URL(fileURLWithPath: "/bin/launchctl")
                launchctl.arguments = arguments
                launchctl.standardOutput = FileHandle.nullDevice
                launchctl.standardError = FileHandle.nullDevice
                try? launchctl.run()
                launchctl.waitUntilExit()
            }
        }
    }

    private var placeholder: String {
        """
        <!doctype html><meta charset="utf-8"><title>FLEET</title>
        <style>
          html,body{height:100%;margin:0;background:#0f1424;color:#aab3c8;
            font:14px/1.5 -apple-system,system-ui,sans-serif;display:grid;place-items:center}
          .card{text-align:center;padding:24px 32px}
          .dots{display:inline-flex;gap:14px;margin-bottom:20px}
          .dots i{width:12px;height:12px;border-radius:50%;background:#73e69e;
            box-shadow:0 0 14px #73e69e;animation:pulse 1.4s ease-in-out infinite}
          .dots i:nth-child(2){background:#fac254;box-shadow:0 0 14px #fac254;animation-delay:.25s}
          .dots i:nth-child(3){background:#7585a8;box-shadow:none;animation-delay:.5s}
          @keyframes pulse{0%,100%{opacity:.35}50%{opacity:1}}
          h1{font-size:13px;letter-spacing:.24em;margin:0 0 6px;color:#e6ebf5;font-weight:600}
          p{margin:0;max-width:34em}
        </style>
        <div class="card"><div class="dots"><i></i><i></i><i></i></div>
        <h1>FLEET</h1><p id="note">Starting the board&hellip;</p></div>
        """
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction,
                 windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url {
            NSWorkspace.shared.open(url)
        }
        return nil
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        let isDashboard = url.host == dashboardURL.host && url.port == dashboardURL.port
        if navigationAction.targetFrame?.isMainFrame == true && !isDashboard {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
        } else {
            decisionHandler(.allow)
        }
    }
}

// Finder passes no arguments: a double-click means the board on its usual
// port. fleet.command still passes the URL explicitly for a custom port.
let argument = CommandLine.arguments.dropFirst().first ?? "http://127.0.0.1:8787"
guard let url = URL(string: argument), ["http", "https"].contains(url.scheme ?? "") else {
    fputs("usage: FleetDashboard [http://127.0.0.1:PORT]\n", stderr)
    exit(2)
}

let application = NSApplication.shared
let delegate = FleetApp(url: url)
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
