"""A terminal button finds the tab a session already lives in, by pid."""
import unittest

import iterm_link


ROWS = {
    "iterm": [
        {"app": "iterm", "window": "1", "tab": "1", "session": "A", "tty": "/dev/ttys001", "name": "one"},
        {"app": "iterm", "window": "1", "tab": "2", "session": "B", "tty": "/dev/ttys002", "name": "two"},
    ],
    "terminal": [
        {"app": "terminal", "window": "9", "tab": "1", "session": "", "tty": "/dev/ttys007", "name": ""},
    ],
}
TTYS = {100: "/dev/ttys001", 200: "/dev/ttys002", 700: "/dev/ttys007", 999: "/dev/ttys050"}


class Reveal(unittest.TestCase):
    def setUp(self):
        self._orig = (iterm_link.tty_of, iterm_link.running_apps, iterm_link.inventory)
        iterm_link.tty_of = lambda pid, ps_out=None: TTYS.get(pid)
        iterm_link.running_apps = lambda ps_out=None: ["iterm", "terminal"]
        iterm_link.inventory = lambda app: ROWS[app]

    def tearDown(self):
        iterm_link.tty_of, iterm_link.running_apps, iterm_link.inventory = self._orig

    def test_pid_picks_its_own_tab_not_the_first_in_the_folder(self):
        hit = iterm_link.find({"pid": 200, "cwd": "/same/folder"})
        self.assertEqual((hit["app"], hit["tab"], hit["session"]), ("iterm", "2", "B"))

    def test_terminal_tabs_are_found_too(self):
        hit = iterm_link.find({"pid": 700})
        self.assertEqual((hit["app"], hit["tab"], hit["tty"]), ("terminal", "1", "/dev/ttys007"))

    def test_no_pid_means_nothing_to_reveal(self):
        self.assertIsNone(iterm_link.find({"cwd": "/same/folder"}))
        self.assertIsNone(iterm_link.find({"pid": None}))
        self.assertIsNone(iterm_link.find({"pid": "nope"}))

    def test_a_tty_no_app_owns_is_not_a_tab(self):
        # A daemon's background job, or a pty the board itself opened.
        self.assertIsNone(iterm_link.find({"pid": 999}))

    def test_apps_not_running_are_never_asked(self):
        asked = []
        iterm_link.running_apps = lambda ps_out=None: ["iterm"]
        iterm_link.inventory = lambda app: asked.append(app) or ROWS[app]
        self.assertIsNone(iterm_link.find({"pid": 700}))
        self.assertEqual(asked, ["iterm"])

    def test_running_apps_reads_the_process_table(self):
        running_apps = self._orig[1]
        ps = "/Applications/iTerm.app/Contents/MacOS/iTerm2\n/usr/bin/foo\n"
        self.assertEqual(running_apps(ps), ["iterm"])
        ps += "/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal\n"
        self.assertEqual(running_apps(ps), ["iterm", "terminal"])

    def test_tty_of_parses_ps(self):
        tty_of = self._orig[0]
        ps = "  100 ttys001\n  200 ??\n"
        self.assertEqual(tty_of(100, ps), "/dev/ttys001")
        self.assertIsNone(tty_of(200, ps))
        self.assertIsNone(tty_of(300, ps))


if __name__ == "__main__":
    unittest.main()
