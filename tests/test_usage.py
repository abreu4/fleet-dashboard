"""The usage ledger reads what the fleet wrote, and when, off its transcripts."""
import json
import os
import shutil
import tempfile
import time
import unittest

import usage

MIN = usage.MINUTE_MS


def iso(ms):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms / 1000)) + ".000Z"


def claude_row(at, out, inp=2, cache_read=1000, cache_write=0, rid="req_1",
               model="claude-opus-5", effort="high"):
    return json.dumps({
        "type": "assistant", "requestId": rid, "timestamp": iso(at), "effort": effort,
        "message": {"model": model, "usage": {
            "input_tokens": inp, "output_tokens": out,
            "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write}},
    })


def model_row(model_id):
    return json.dumps({"type": "attachment",
                       "attachment": {"type": "model", "identity": {"modelId": model_id}}})


def codex_row(at, total_out, total_in, cached, last_in=100, window=258400):
    return json.dumps({
        "type": "event_msg", "timestamp": iso(at),
        "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": total_in, "cached_input_tokens": cached,
                                  "cache_write_input_tokens": 0, "output_tokens": total_out},
            "last_token_usage": {"input_tokens": last_in, "output_tokens": 7},
            "model_context_window": window}},
    })


class Ledger(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.claude = os.path.join(self.root, "projects")
        self.codex = os.path.join(self.root, "codex")
        os.makedirs(os.path.join(self.claude, "-Users-x-proj"))
        self.ledger = usage.Ledger(claude_root=self.claude, codex_root=self.codex)
        self.now = int(time.time() * 1000) // MIN * MIN + 30_000   # half past a minute

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, name, rows, provider="claude"):
        if provider == "claude":
            path = os.path.join(self.claude, "-Users-x-proj", name + ".jsonl")
        else:
            lt = time.localtime(self.now / 1000)
            day = os.path.join(self.codex, "%04d" % lt.tm_year, "%02d" % lt.tm_mon,
                               "%02d" % lt.tm_mday)
            os.makedirs(day, exist_ok=True)
            path = os.path.join(day, name + ".jsonl")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(rows) + "\n")
        return path

    def test_streamed_rows_of_one_request_count_once(self):
        at = self.now - 3 * MIN
        path = self.write("s1", [claude_row(at, 100, rid="a"), claude_row(at, 100, rid="a"),
                                 claude_row(at + 1000, 50, rid="b")])
        got = self.ledger.session(path)
        self.assertEqual((got["out"], got["requests"]), (150, 2))

    def test_context_is_what_the_last_request_saw(self):
        at = self.now - 2 * MIN
        path = self.write("s2", [model_row("claude-opus-5[1m]"),
                                 claude_row(at, 10, inp=5, cache_read=90_000, cache_write=5_000)])
        got = self.ledger.session(path)
        self.assertEqual(got["ctx"], 95_005)
        self.assertEqual(got["ctxMax"], usage.CONTEXT_LONG)
        self.assertEqual(got["model"], "claude-opus-5[1m]")
        self.assertAlmostEqual(got["ctxPct"], 9.5, places=1)

    def test_context_ceiling_follows_the_model(self):
        for model, ceiling in (("claude-haiku-4-5", usage.CONTEXT_SHORT),
                               ("claude-opus-4-5", usage.CONTEXT_SHORT),
                               ("claude-sonnet-4-5-20250929", usage.CONTEXT_SHORT),
                               ("claude-3-7-sonnet-20250219", usage.CONTEXT_SHORT),
                               ("claude-opus-5", usage.CONTEXT_LONG),
                               ("claude-fable-5-1", usage.CONTEXT_LONG),
                               ("claude-sonnet-4-6", usage.CONTEXT_LONG),
                               ("claude-opus-5[1m]", usage.CONTEXT_LONG)):
            self.assertEqual(usage.context_window(model), ceiling, model)

    def test_a_session_that_outgrows_its_ceiling_is_read_as_long(self):
        at = self.now - MIN
        path = self.write("s3", [model_row("claude-haiku-4-5"),
                                 claude_row(at, 10, cache_read=300_000)])
        self.assertEqual(self.ledger.session(path)["ctxMax"], usage.CONTEXT_LONG)

    def test_reads_only_what_arrived_since_the_last_pass(self):
        at = self.now - 2 * MIN
        path = self.write("s4", [claude_row(at, 100, rid="a")])
        self.assertEqual(self.ledger.session(path)["out"], 100)
        self.write("s4", [claude_row(at + 5000, 25, rid="b")])
        self.assertEqual(self.ledger.session(path)["out"], 125)

    def test_rate_today_and_trace(self):
        m = self.now // MIN
        self.write("s5", [claude_row((m - 1) * MIN, 600, rid="a"),
                          claude_row((m - 3) * MIN, 400, rid="b")])
        self.write("s6", [claude_row((m - 3) * MIN + 100, 500, rid="c")])
        self.ledger.scan(self.now)
        got = self.ledger.summary(self.now, trace_minutes=5)
        self.assertEqual(got["rate"]["perMin"], 300)           # 1500 over 5 whole minutes
        self.assertEqual(got["today"]["out"], 1500)
        self.assertEqual(got["today"]["sessions"], 2)
        self.assertEqual(got["trace"]["out"], [0, 900, 0, 600, 0])
        self.assertEqual(got["trace"]["sessions"], [0, 2, 0, 1, 0])
        self.assertEqual(got["rate"]["peakPerMin"], 900)
        self.assertNotIn("by", got["trace"])                   # one writer: plain bars

    def test_trace_splits_by_provider_when_more_than_one_wrote(self):
        m = self.now // MIN
        self.write("s7", [claude_row((m - 3) * MIN, 400, rid="a")])
        self.write("r2", [codex_row((m - 3) * MIN, 100, 1000, 900),
                          codex_row((m - 1) * MIN, 160, 2500, 2300)], provider="codex")
        self.ledger.scan(self.now)
        trace = self.ledger.summary(self.now, trace_minutes=4)["trace"]
        self.assertEqual(trace["out"], [500, 0, 60, 0])
        self.assertEqual(trace["by"], {"claude": [400, 0, 0, 0], "codex": [100, 0, 60, 0]})

    def test_window_opens_on_the_first_message_and_chains(self):
        m = self.now // MIN
        h = 60
        # a burst 12h ago (guaranteed gap), then 4h ago, then 40 minutes ago
        self.write("s7", [claude_row((m - 12 * h) * MIN, 1, rid="a"),
                          claude_row((m - 4 * h) * MIN, 10, rid="b"),
                          claude_row((m - 40) * MIN, 100, rid="c")])
        self.ledger.scan(self.now)
        start, end, out = self.ledger.window(self.now)
        # 4h ago opened a window that is still running: 40 minutes ago is inside it
        self.assertEqual(start, (m - 4 * h) * MIN)
        self.assertEqual(end, (m - 4 * h + 5 * h) * MIN)
        self.assertEqual(out, 110)

    def test_window_closed_with_nothing_since_is_none(self):
        m = self.now // MIN
        self.write("s8", [claude_row((m - 6 * 60) * MIN, 1, rid="a")])
        self.ledger.scan(self.now)
        self.assertIsNone(self.ledger.window(self.now))

    def test_window_after_expiry_opens_on_the_next_message(self):
        m = self.now // MIN
        h = 60
        self.write("s9", [claude_row((m - 7 * h) * MIN, 1, rid="a"),
                          claude_row((m - 90) * MIN, 20, rid="b")])
        self.ledger.scan(self.now)
        start, end, out = self.ledger.window(self.now)
        self.assertEqual((start, out), ((m - 90) * MIN, 20))

    def test_codex_running_totals_become_deltas(self):
        m = self.now // MIN
        path = self.write("r1", [codex_row((m - 3) * MIN, 100, 1000, 900),
                                 codex_row((m - 2) * MIN, 160, 2500, 2300, last_in=1500)],
                          provider="codex")
        got = self.ledger.session(path, "codex")
        self.assertEqual(got["out"], 160)
        self.assertEqual(got["in"], 200)                 # fresh input, cache taken out
        self.assertEqual(got["cacheRead"], 2300)
        self.assertEqual(got["ctxMax"], 258400)
        self.assertEqual(got["ctx"], 1507)
        self.ledger.scan(self.now)
        trace = self.ledger.summary(self.now, trace_minutes=4)["trace"]["out"]
        self.assertEqual(trace, [100, 60, 0, 0])
        # Codex never opens a Claude window
        self.assertIsNone(self.ledger.window(self.now))


class Finished(unittest.TestCase):
    def test_done_jobs_since_midnight_and_their_merge_requests(self):
        root = tempfile.mkdtemp()
        try:
            usage.CLAUDE_JOBS, saved = root, usage.CLAUDE_JOBS
            usage._jobs_cache.clear()
            now = int(time.time() * 1000)

            def job(name, state, ended, hrefs=()):
                os.makedirs(os.path.join(root, name))
                with open(os.path.join(root, name, "state.json"), "w") as handle:
                    json.dump({"state": state, "lastTerminalAt": iso(ended),
                               "children": [{"kind": "pr", "href": h} for h in hrefs]}, handle)

            job("a", "done", now - 1000, ["https://x/1", "https://x/2"])
            job("b", "done", now - 2000, ["https://x/2"])
            job("c", "done", now - 26 * 3600 * 1000, ["https://x/3"])
            job("d", "running", now - 500)
            got = usage.finished(now - 3600 * 1000)
            self.assertEqual((got["count"], got["mrs"], sorted(got["ids"])), (2, 2, ["a", "b"]))
        finally:
            usage.CLAUDE_JOBS = saved
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
