import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import collectors


def message(ordinal, role, text, phase=""):
    return {
        "ordinal": ordinal,
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": role,
            "phase": phase,
            "content": [{
                "type": "input_text" if role == "user" else "output_text",
                "text": text,
            }],
        },
    }


class CodexTranscriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rollout = os.path.join(self.temp.name, "rollout.jsonl")

    def tearDown(self):
        self.temp.cleanup()

    def append(self, *rows):
        with open(self.rollout, "a", encoding="utf8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def test_reader_skips_harness_and_updates_incrementally(self):
        self.append(
            message(1, "user", "# AGENTS.md instructions\ninternal harness text"),
            message(2, "user", "Investigate why production backups stopped"),
            message(3, "assistant", "I found the failed timer and am checking its logs.", "commentary"),
        )
        reader = collectors.CodexTranscripts()
        first = reader.read(self.rollout)
        self.assertEqual(first["turns"], 1)
        self.assertIn("failed timer", first["last_assistant"])
        offset = first["offset"]

        self.append(message(4, "user", "Merge the tested fix"))
        second = reader.read(self.rollout)
        self.assertGreater(second["offset"], offset)
        self.assertEqual(second["last_user"], "Merge the tested fix")
        self.assertEqual(second["turns"], 2)
        self.assertGreater(second["mtime"], 0)

    def test_collector_prefers_name_and_rollout_progress(self):
        self.append(
            message(1, "user", "Fix nightly backup failures"),
            message(2, "assistant", "The timer is restored and the catch-up upload is running.", "commentary"),
        )
        database = os.path.join(self.temp.name, "state_5.sqlite")
        conn = sqlite3.connect(database)
        conn.execute("""create table threads (
            id text, name text, agent_nickname text, title text, cwd text,
            git_branch text, tokens_used integer, first_user_message text,
            preview text, rollout_path text, created_at integer,
            updated_at integer, archived integer)""")
        now = int(__import__("time").time())
        conn.execute("insert into threads values (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            "thread-1", "Fix nightly backup failures", None,
            "This raw opening prompt is much too long to be a useful title",
            self.temp.name, "main", 123, "Fix the backup service",
            "Fix the backup service", self.rollout, now - 60, now, 0,
        ))
        conn.commit()
        conn.close()

        with mock.patch.object(collectors, "CODEX_DIR", self.temp.name), \
             mock.patch.object(collectors, "merge_live", side_effect=lambda rows, *_: rows):
            session = collectors.collect_codex(collectors.CodexTranscripts())[0]

        self.assertEqual(session["name"], "Fix nightly backup failures")
        self.assertEqual(session["brief"], "Fix the backup service")
        self.assertIn("catch-up upload is running", session["now"])
        self.assertEqual(session["turns"], 1)

    def test_live_process_reattaches_to_named_session_that_looks_idle(self):
        session = {
            "id": "thread-1", "provider": "codex", "name": "Fix backups",
            "cwd": self.temp.name, "state": "idle", "updated": 200_000,
        }
        process = {"pid": 123, "cwd": self.temp.name, "started": 100_000}
        with mock.patch.object(collectors, "live_processes", return_value=[process]):
            merged = collectors.merge_live([session], "codex", "codex")
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["name"], "Fix backups")
        self.assertEqual(merged[0]["state"], "running")
        self.assertEqual(merged[0]["pid"], 123)

    def test_new_process_does_not_steal_old_session_metadata(self):
        session = {
            "id": "old", "provider": "codex", "name": "Old task",
            "cwd": self.temp.name, "state": "idle", "updated": 50_000,
        }
        process = {"pid": 456, "cwd": self.temp.name, "started": 200_000}
        with mock.patch.object(collectors, "live_processes", return_value=[process]):
            merged = collectors.merge_live([session], "codex", "codex")
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[1]["name"], "codex 456")


if __name__ == "__main__":
    unittest.main()
