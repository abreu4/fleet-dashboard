"""A tab is named after the session running inside it, whatever the agent."""
import time
import unittest

import terminal


class FakePty:
    """Just the attributes adopt() reads and writes; no fork, no fd."""

    def __init__(self, tid, pid, cwd="/tmp/x", title="~", opened_for=None, started=None):
        self.id, self.pid, self.cwd = tid, pid, cwd
        self.title, self.fallback = title, "~"
        self.session_id = self.opened_for = opened_for
        self.started = time.time() if started is None else started
        self.exited = None

    def meta(self):
        return {"id": self.id, "session_id": self.session_id, "title": self.title}


def board(terms):
    t = terminal.Terminals()
    t._ptys = {p.id: p for p in terms}
    sent = []
    t._broadcast = lambda event, payload: sent.append((event, payload))
    return t, sent


class Adopt(unittest.TestCase):
    def test_a_shell_takes_the_name_of_the_agent_typed_into_it(self):
        shell = FakePty("t1", pid=100)
        t, sent = board([shell])
        # shell 100 -> claude 200 (a Claude session on the roster)
        t.adopt([{"id": "claude:abc", "name": "plot-zoom", "pid": 200}], {200: 100, 100: 1})
        self.assertEqual((shell.title, shell.session_id), ("plot-zoom", "claude:abc"))
        self.assertEqual(sent, [("meta", shell.meta())])

    def test_any_agent_and_string_pids(self):
        shell = FakePty("t1", pid=100)
        t, _ = board([shell])
        t.adopt([{"id": "codex:1", "name": "fix the build", "pid": "300"}], {300: 100})
        self.assertEqual(shell.title, "fix the build")

    def test_the_nearest_agent_wins_over_one_it_spawned(self):
        shell = FakePty("t1", pid=100)
        t, _ = board([shell])
        # shell -> claude 200 -> bash 210 -> claude 220 (a tool call running claude)
        t.adopt([{"id": "inner", "name": "inner", "pid": 220},
                 {"id": "outer", "name": "outer", "pid": 200}],
                {200: 100, 210: 200, 220: 210})
        self.assertEqual(shell.session_id, "outer")

    def test_a_rename_on_the_board_reaches_the_tab(self):
        shell = FakePty("t1", pid=100)
        t, sent = board([shell])
        t.adopt([{"id": "s", "name": "first", "pid": 200}], {200: 100})
        t.adopt([{"id": "s", "name": "renamed", "pid": 200}], {200: 100})
        t.adopt([{"id": "s", "name": "renamed", "pid": 200}], {200: 100})
        self.assertEqual(shell.title, "renamed")
        self.assertEqual(len(sent), 2)              # nothing sent when nothing changed

    def test_the_folder_name_comes_back_when_the_agent_exits(self):
        shell = FakePty("t1", pid=100, cwd="/tmp/x")
        t, _ = board([shell])
        t.adopt([{"id": "s", "name": "work", "pid": 200}], {200: 100})
        t.adopt([{"id": "s", "name": "work", "pid": None}], {100: 1})
        self.assertEqual((shell.title, shell.session_id), ("~", None))

    def test_a_tab_opened_for_a_session_keeps_it_while_attached(self):
        # `claude attach` is pid 250 under the shell; the session's own pid is
        # 900, in some iTerm tab. Old enough to be past the grace period.
        tab = FakePty("t1", pid=100, title="theia-b6", opened_for="claude:x", started=time.time() - 600)
        t, sent = board([tab])
        t.adopt([{"id": "claude:x", "name": "theia-b6", "pid": 900}], {250: 100, 900: 5})
        self.assertEqual((tab.title, tab.session_id), ("theia-b6", "claude:x"))
        self.assertEqual(sent, [])
        # renamed on the board: the tab follows
        t.adopt([{"id": "claude:x", "name": "theia b6 (mine)", "pid": 900}], {250: 100, 900: 5})
        self.assertEqual(tab.title, "theia b6 (mine)")
        # the attach ends and the tab is a bare shell: folder name, no link
        t.adopt([{"id": "claude:x", "name": "theia b6 (mine)", "pid": 900}], {900: 5})
        self.assertEqual((tab.title, tab.session_id, tab.opened_for), ("~", None, None))

    def test_a_fresh_resume_is_not_stripped_before_it_starts(self):
        tab = FakePty("t1", pid=100, title="work", opened_for="s")
        t, sent = board([tab])
        t.adopt([{"id": "s", "name": "work", "pid": None}], {100: 1})   # nothing under the shell yet
        self.assertEqual((tab.title, tab.session_id), ("work", "s"))
        self.assertEqual(sent, [])

    def test_dead_terminals_are_left_alone(self):
        gone = FakePty("t1", pid=100)
        gone.exited = 0
        t, sent = board([gone])
        t.adopt([{"id": "s", "name": "x", "pid": 200}], {200: 100})
        self.assertEqual(gone.title, "~")
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
