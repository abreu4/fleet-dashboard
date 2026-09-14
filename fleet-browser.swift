import Cocoa
import WebKit

final class FleetApp: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    private let dashboardURL: URL
    private var window: NSWindow!
    private var webView: WKWebView!
    private var shortcutMonitor: Any?

    init(url: URL) {
        dashboardURL = url
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenu()
        installShortcutMonitor()

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
        // mute/volume controls and defaults click noises off.
        configuration.mediaTypesRequiringUserActionForPlayback = []
        webView = WKWebView(frame: window.contentView!.bounds, configuration: configuration)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        webView.uiDelegate = self
        window.contentView = webView
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        webView.load(URLRequest(url: dashboardURL))
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let shortcutMonitor {
            NSEvent.removeMonitor(shortcutMonitor)
        }
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

        let terminalItem = NSMenuItem()
        main.addItem(terminalItem)
        let terminalMenu = NSMenu(title: "Terminal")
        terminalItem.submenu = terminalMenu
        addCommand("New Terminal", key: "t", action: #selector(newTerminal), to: terminalMenu)
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

    @objc private func previousTerminal() {
        run("window.fleetCycleTerminal?.(-1)")
    }

    @objc private func nextTerminal() {
        run("window.fleetCycleTerminal?.(1)")
    }

    @objc private func reload() {
        webView?.reload()
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

guard CommandLine.arguments.count > 1,
      let url = URL(string: CommandLine.arguments[1]),
      ["http", "https"].contains(url.scheme ?? "") else {
    fputs("usage: fleet-browser http://127.0.0.1:PORT\n", stderr)
    exit(2)
}

let application = NSApplication.shared
let delegate = FleetApp(url: url)
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
