import json
import os
import tempfile
import unittest
from unittest import mock

import collectors
import notes


def user(text, stamp, **extra):
    row = {"type": "user", "timestamp": stamp,
           "message": {"role": "user", "content": text}}
    row.update(extra)
    return row


def assistant(text, stamp):
    return {"type": "assistant", "timestamp": stamp,
            "message": {"role": "assistant",
                        "content": [{"type": "text", "text": text}]}}


class ClaudeTranscriptNamingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "session.jsonl")

    def tearDown(self):
        self.temp.cleanup()

    def append(self, *rows):
        with open(self.path, "a", encoding="utf8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def test_titles_are_read_and_the_custom_one_wins(self):
        self.append(
            user("Rename every session tile after what it is doing, please", "2026-09-15T10:00:00.000Z"),
            {"type": "ai-title", "aiTitle": "Session tile naming", "sessionId": "s"},
        )
        entry = collectors.Transcripts().read(self.path)
        self.assertEqual(entry["ai_title"], "Session tile naming")
        self.assertIsNone(entry["custom_title"])
        self.append({"type": "custom-title", "customTitle": "naming-lane", "sessionId": "s"})
        entry = collectors.Transcripts().read(self.path)
        self.assertEqual(entry["custom_title"], "naming-lane")

    def test_reply_after_prompt_is_the_newer_of_the_two(self):
        self.append(
            {"type": "last-prompt", "lastPrompt": "Make the tiles readable from a metre away"},
            user("Make the tiles readable from a metre away", "2026-09-15T10:00:00.000Z"),
            assistant("Done: the name is now the title Claude Code wrote itself.", "2026-09-15T10:05:00.000Z"),
        )
        reader = collectors.Transcripts()
        entry = reader.read(self.path)
        self.assertGreater(entry["reply_seq"], entry["prompt_seq"])
        self.assertEqual(entry["prompt_at"], 1789466400000)

        self.append(
            {"type": "last-prompt", "lastPrompt": "Now do the same for the drawer, with the handle beside the name"},
            user("Now do the same for the drawer, with the handle beside the name", "2026-09-15T10:07:00.000Z"),
        )
        entry = reader.read(self.path)
        self.assertGreater(entry["prompt_seq"], entry["reply_seq"])
        self.assertEqual(entry["prompt_at"], 1789466820000)

    def test_injected_turns_do_not_count_as_the_user_speaking(self):
        self.append(
            user("Investigate the flaky backup timer on the build box", "2026-09-15T10:00:00.000Z"),
            assistant("Looking at the timer unit now.", "2026-09-15T10:01:00.000Z"),
            user("<task-notification>agent finished</task-notification>", "2026-09-15T10:02:00.000Z"),
            user("hook output: lint passed", "2026-09-15T10:03:00.000Z", isMeta=True),
        )
        entry = collectors.Transcripts().read(self.path)
        self.assertGreater(entry["reply_seq"], entry["prompt_seq"])
        self.assertEqual(entry["prompt_at"], 1789466400000)


class EpochTests(unittest.TestCase):
    def test_iso_variants(self):
        self.assertEqual(collectors._epoch_ms("2026-09-15T10:00:00Z"), 1789466400000)
        self.assertEqual(collectors._epoch_ms("2026-09-15T10:00:00.250Z"), 1789466400250)
        self.assertEqual(collectors._epoch_ms("2026-09-15T11:00:00+01:00"), 1789466400000)
        self.assertEqual(collectors._agy_ms("2026-09-15 10:00:00.732754+00:00"), 1789466400732)
        self.assertIsNone(collectors._epoch_ms(""))
        self.assertIsNone(collectors._epoch_ms("yesterday"))


class AntigravityScrapeTests(unittest.TestCase):
    def test_length_prefix_byte_is_dropped(self):
        prompt = b"Confirm this deployed repo has a way of automatically ingesting new data at a given frequency"
        self.assertEqual(len(prompt), 93)          # 93 == ord("]")
        blob = b"\x12" + bytes([len(prompt)]) + prompt + b"\x1a\x05\x08\x01" \
             + b"\x12" + bytes([len(prompt)]) + prompt
        self.assertEqual(collectors._agy_text(blob), prompt.decode())

    def test_short_prompt_survives(self):
        blob = b"\x12\x0btest_update\x1a\x02\x08\x01\x12\x0btest_update"
        self.assertEqual(collectors._agy_text(blob), "test_update")


class NoteFreshnessTests(unittest.TestCase):
    def attach(self, session, note_at):
        note = {"text": "waiting on review", "at": note_at, "by": "", "cwd": "",
                "session": "sid", "name": "sid"}
        with mock.patch.object(notes, "load", return_value=({"sid": note}, {})):
            return notes.attach([session])[0]

    def test_note_leads_until_the_user_speaks_again(self):
        current = self.attach({"sessionId": "sid", "cwd": "/w", "promptAt": 1000}, 5000)
        self.assertEqual(current["note"], "waiting on review")
        self.assertFalse(current["noteStale"])

        overtaken = self.attach({"sessionId": "sid", "cwd": "/w", "promptAt": 60000}, 5000)
        self.assertNotIn("note", overtaken)
        self.assertEqual(overtaken["staleNote"], "waiting on review")
        self.assertTrue(overtaken["noteStale"])

    def test_prompt_within_grace_does_not_overtake(self):
        session = self.attach({"sessionId": "sid", "cwd": "/w", "promptAt": 7000}, 5000)
        self.assertEqual(session["note"], "waiting on review")

    def test_no_prompt_time_means_the_note_stands(self):
        session = self.attach({"sessionId": "sid", "cwd": "/w"}, 5000)
        self.assertEqual(session["note"], "waiting on review")


if __name__ == "__main__":
    unittest.main()
