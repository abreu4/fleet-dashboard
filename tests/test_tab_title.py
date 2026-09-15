import os
import unittest

import terminal


class TabTitle(unittest.TestCase):
    def test_home_is_tilde_not_the_login_name(self):
        home = os.path.realpath(os.path.expanduser("~"))
        self.assertEqual(terminal.tab_title(home, "shell"), "~")
        self.assertEqual(terminal.tab_title(home + "/", "claude"), "~ · claude")

    def test_a_folder_in_home_keeps_the_tilde(self):
        home = os.path.realpath(os.path.expanduser("~"))
        self.assertEqual(terminal.tab_title(os.path.join(home, "Documents"), "shell"), "~/Documents")

    def test_deeper_folders_go_by_their_last_component(self):
        home = os.path.realpath(os.path.expanduser("~"))
        deep = os.path.join(home, "Documents", "Dev", "agent-dashboard")
        self.assertEqual(terminal.tab_title(deep, "shell"), "agent-dashboard")
        self.assertEqual(terminal.tab_title(deep, "antigravity"), "agent-dashboard · agy")


if __name__ == "__main__":
    unittest.main()
