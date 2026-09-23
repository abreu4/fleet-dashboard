"""The long record: day rows built off every transcript, sealed once the day closes."""
import json
import os
import shutil
import tempfile
import time
import unittest

import totals
import usage

MIN = usage.MINUTE_MS


def iso(ms):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms / 1000)) + ".000Z"


def noon(days_ago, now=None):
    """Local noon `days_ago` calendar days before today, in ms."""
    lt = time.localtime((now or time.time()))
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday - days_ago, 12, 0, 0, 0, 0, -1)) * 1000)


def opening(at, cwd="/Users/x/Dev/proj"):
    return json.dumps({"type": "user", "timestamp": iso(at), "cwd": cwd,
                       "message": {"role": "user", "content": "go"}})


def claude_row(at, out, rid, model="claude-opus-5", cache_read=1000):
    return json.dumps({
        "type": "assistant", "requestId": rid, "timestamp": iso(at),
        "message": {"model": model, "usage": {
            "input_tokens": 3, "output_tokens": out,
            "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": 7}},
    })


def codex_meta(at, cwd="/Users/x/Dev/other"):
    return json.dumps({"timestamp": iso(at), "type": "session_meta",
                       "payload": {"cwd": cwd, "base_instructions": {"text": "x" * 5000}}})


def codex_row(at, total_out, total_in=100, cached=40):
    return json.dumps({
        "type": "event_msg", "timestamp": iso(at),
        "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": total_in, "cached_input_tokens": cached,
                                  "output_tokens": total_out},
            "last_token_usage": {"input_tokens": 10, "output_tokens": 1},
            "model_context_window": 258400}},
    })


class Record(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.claude = os.path.join(self.root, "projects")
        self.codex = os.path.join(self.root, "codex")
        self.file = os.path.join(self.root, "config", "totals.json")
        self.proj = os.path.join(self.claude, "-Users-x-Dev-proj")
        os.makedirs(self.proj)
        os.makedirs(self.codex)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def book(self):
        return totals.Totals(path=self.file, claude_root=self.claude, codex_root=self.codex)

    def write(self, path, rows):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(rows) + "\n")
        return path

    def read(self):
        with open(self.file, encoding="utf-8") as handle:
            return handle.read()

    def session(self, name, rows):
        return self.write(os.path.join(self.proj, name + ".jsonl"), rows)

    def test_days_are_credited_where_the_tokens_were_written(self):
        two, one = noon(2), noon(1)
        self.session("a", [opening(two), claude_row(two, 100, "r1"),
                           claude_row(two, 100, "r1"),              # streamed twice, counted once
                           claude_row(one, 40, "r2", model="claude-fable-5-1")])
        book = self.book(); book.refresh()
        days = book.days()
        d2, d1 = totals.day_key(two), totals.day_key(one)
        self.assertEqual(days[d2]["out"], 100)
        self.assertEqual(days[d1]["out"], 40)
        # Started on the first day only, though it wrote on both.
        self.assertEqual((days[d2]["started"], days[d1]["started"]), (1, 0))
        self.assertEqual((days[d2]["sessions"], days[d1]["sessions"]), (1, 1))
        self.assertEqual(days[d1]["byModel"], {"claude-fable-5-1": 40})
        self.assertEqual(days[d2]["byProject"], {"proj": 100})
        self.assertEqual(days[d2]["hours"][12], 100)
        self.assertEqual(days[d2]["cacheRead"], 1000)                  # kept, never reported
        self.assertEqual(days[d2]["peak"], {"out": 100, "at": two // MIN * MIN})

    def test_subagents_count_for_tokens_not_as_sessions(self):
        at = noon(1)
        self.session("parent", [opening(at), claude_row(at, 10, "p1")])
        self.write(os.path.join(self.proj, "parent", "subagents", "agent-1.jsonl"),
                   [opening(at + MIN, cwd="/Users/x/Dev/proj/.claude/worktrees/w"),
                    claude_row(at + MIN, 30, "s1")])
        book = self.book(); book.refresh()
        row = book.days()[totals.day_key(at)]
        self.assertEqual(row["out"], 40)
        self.assertEqual((row["started"], row["sessions"]), (1, 1))
        self.assertEqual(row["byProject"], {"proj": 40})               # the worktree lands on its repo

    def test_codex_counts_by_its_deltas(self):
        at = noon(1)
        lt = time.localtime(at / 1000)
        path = os.path.join(self.codex, "%04d" % lt.tm_year, "%02d" % lt.tm_mon,
                            "%02d" % lt.tm_mday, "rollout.jsonl")
        self.write(path, [codex_meta(at), codex_row(at, 50), codex_row(at + MIN, 80, 300, 200)])
        book = self.book(); book.refresh()
        row = book.days()[totals.day_key(at)]
        self.assertEqual(row["out"], 80)
        self.assertEqual(row["byProvider"]["codex"]["requests"], 2)
        self.assertEqual(row["startedBy"], {"codex": 1})
        self.assertEqual(row["byModel"], {"codex": 80})
        self.assertEqual(row["byProject"], {"other": 80})

    def test_appended_bytes_fold_into_today(self):
        start = int(time.time() * 1000) - 10 * MIN
        path = self.session("live", [opening(start), claude_row(start, 5, "a")])
        book = self.book(); book.refresh()
        self.write(path, [claude_row(start + MIN, 7, "b")])
        book.refresh()
        self.assertEqual(sum(r["out"] for r in book.days().values()), 12)

    def test_a_closed_day_outlives_its_transcripts(self):
        old, today = noon(3), int(time.time() * 1000)
        a = self.session("old", [opening(old), claude_row(old, 500, "o")])
        self.session("new", [opening(today - MIN), claude_row(today - MIN, 9, "n")])
        first = self.book(); first.refresh()
        on_disk = json.loads(self.read())["days"]
        self.assertTrue(on_disk[totals.day_key(old)]["sealed"])
        self.assertFalse(on_disk[totals.day_key(today - MIN)].get("sealed"))
        os.unlink(a)                                                 # Claude's 30-day cleanup
        second = self.book(); second.refresh()
        self.assertEqual(second.days()[totals.day_key(old)]["out"], 500)
        self.assertEqual(second.summary()["totals"]["out"], 509)

    def test_a_sealed_row_is_never_recomputed(self):
        old = noon(4)
        path = self.session("old", [opening(old), claude_row(old, 500, "o")])
        self.book().refresh()
        # A later walk that would count differently (a row appended with an
        # old stamp) does not move a day already sealed.
        self.write(path, [claude_row(old + MIN, 99, "late")])
        again = self.book(); again.refresh()
        self.assertEqual(again.days()[totals.day_key(old)]["out"], 500)

    def test_an_old_version_is_thrown_away(self):
        os.makedirs(os.path.dirname(self.file))
        with open(self.file, "w") as handle:
            json.dump({"version": 0, "days": {"2020-01-01": {"out": 7, "sealed": True}}}, handle)
        self.assertEqual(self.book().days(), {})

    def test_two_boards_write_the_same_past(self):
        for i, days_ago in enumerate((5, 4, 2)):
            at = noon(days_ago)
            self.session("s%d" % i, [opening(at), claude_row(at, 10 * (i + 1), "r%d" % i)])
        self.book().refresh()
        one = self.read()
        os.unlink(self.file)
        self.book().refresh()
        self.assertEqual(self.read(), one)
        self.assertFalse([n for n in os.listdir(os.path.dirname(self.file)) if n.endswith(".tmp")])

    def test_records(self):
        # Worked five days ago, then three in a row ending yesterday.
        for name, days_ago, out, starts in (("a", 5, 10, 1), ("b", 3, 300, 1),
                                            ("c", 2, 20, 3), ("d", 1, 30, 1)):
            for n in range(starts):
                at = noon(days_ago) + n * MIN
                rows = [opening(at)] + ([claude_row(at, out, name)] if n == 0 else [])
                self.session("%s%d" % (name, n), rows)
        book = self.book(); book.refresh()
        got = book.summary()
        self.assertTrue(got["ready"])
        self.assertEqual(got["totals"]["out"], 360)
        self.assertEqual(got["totals"]["started"], 6)
        self.assertEqual(got["records"]["biggestDay"], {"day": totals.day_key(noon(3)), "out": 300})
        self.assertEqual(got["records"]["mostStarted"], {"day": totals.day_key(noon(2)), "started": 3})
        self.assertEqual(got["records"]["longestRun"]["days"], 3)
        self.assertEqual(got["records"]["worked"], {"days": 4, "elapsed": 6})
        self.assertEqual(got["records"]["peakMinute"]["out"], 300)
        self.assertEqual(got["projects"], [{"name": "proj", "out": 360}])

    def test_reads_before_the_first_walk_and_with_no_history(self):
        book = self.book()
        got = book.summary()
        self.assertFalse(got["ready"])
        self.assertEqual((got["totals"]["out"], got["days"], got["records"]["biggestDay"]),
                         (0, [], None))
        shutil.rmtree(self.claude)                                   # a Mac that never ran Claude
        book.refresh()
        got = book.summary()
        self.assertTrue(got["ready"])
        self.assertEqual(got["records"]["worked"], {"days": 0, "elapsed": 0})
        self.assertIsNone(got["records"]["longestRun"])

    def test_the_file_serves_before_the_walk(self):
        old = noon(2)
        self.session("old", [opening(old), claude_row(old, 70, "o")])
        self.book().refresh()
        cold = self.book()                                           # a restart, not yet walked
        got = cold.summary()
        self.assertFalse(got["ready"])
        self.assertEqual(got["totals"]["out"], 70)


class LedgerSubagents(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.claude = os.path.join(self.root, "projects")
        proj = os.path.join(self.claude, "-Users-x-proj")
        now = int(time.time() * 1000)
        self.now = now
        os.makedirs(os.path.join(proj, "parent", "subagents"))
        with open(os.path.join(proj, "parent.jsonl"), "w") as handle:
            handle.write(claude_row(now - 2 * MIN, 10, "p") + "\n")
        with open(os.path.join(proj, "parent", "subagents", "agent-1.jsonl"), "w") as handle:
            handle.write(claude_row(now - 2 * MIN, 30, "s") + "\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_the_live_ledger_reads_subagents_too(self):
        ledger = usage.Ledger(claude_root=self.claude, codex_root=os.path.join(self.root, "codex"))
        ledger.scan(self.now)
        today = ledger.summary(self.now)["today"]
        self.assertEqual(today["out"], 40)
        self.assertEqual(today["sessions"], 1)


if __name__ == "__main__":
    unittest.main()
