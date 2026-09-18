"""The trail reads a run's steps, prompts and files off its transcript."""
import json
import os
import shutil
import tempfile
import unittest

import graph


def claude(kind, at="2026-09-18T10:00:00.000Z", **row):
    row.update({"type": kind, "timestamp": at})
    return json.dumps(row)


def user(text, **extra):
    return claude("user", cwd="/repo",
                  message={"role": "user", "content": [{"type": "text", "text": text}]},
                  **extra)


def result(tool_id, text="ok"):
    return claude("user", cwd="/repo", message={"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": text}]})


def assistant(mid, block, cwd="/repo"):
    return claude("assistant", cwd=cwd,
                  message={"id": mid, "role": "assistant", "content": [block]})


def text(mid, s):
    return assistant(mid, {"type": "text", "text": s})


def think(mid, s):
    return assistant(mid, {"type": "thinking", "thinking": s})


def tool(mid, tid, name, **inp):
    return assistant(mid, {"type": "tool_use", "id": tid, "name": name, "input": inp})


class TrailFiles(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.trails = graph.Trails()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, name, rows, mode="w"):
        path = os.path.join(self.dir, name)
        with open(path, mode) as handle:
            handle.write("\n".join(rows) + "\n")
        return path

    def read(self, path, provider="claude"):
        return self.trails.read(path, provider).payload()


class ClaudeTrail(TrailFiles):
    def test_a_response_is_one_step_across_its_rows(self):
        rows = [
            user("Add a graph window"),
            think("m1", "The player is the model to copy."),
            text("m1", "I'll look at the player first."),
            tool("m1", "t1", "Read", file_path="/repo/ui.html"),
            tool("m1", "t2", "Grep", pattern="player", path="/repo"),
            result("t1"), result("t2"),
            tool("m2", "t3", "Edit", file_path="/repo/ui.html", old_string="a", new_string="b"),
            result("t3"),
            text("m3", "Done."),
        ]
        p = self.read(self.write("s.jsonl", rows))
        self.assertEqual([s["i"] for s in p["steps"]], [0, 1, 2])
        first = p["steps"][0]
        self.assertEqual(first["kind"], "tool")
        self.assertEqual(first["label"], "I'll look at the player first.")
        self.assertEqual(first["what"], "read ui.html")
        self.assertEqual(first["think"], "The player is the model to copy.")
        self.assertEqual(first["n"], 2)
        self.assertEqual(first["files"], [[0, "read"]])          # Grep on a folder is not a file
        self.assertEqual(p["steps"][1]["files"], [[0, "edit"]])
        self.assertEqual(p["steps"][2]["kind"], "say")
        self.assertEqual(p["files"][0]["name"], "ui.html")
        self.assertEqual((p["files"][0]["reads"], p["files"][0]["writes"]), (1, 1))
        self.assertEqual(p["prompts"], [{"i": 0, "t": p["prompts"][0]["t"], "text": "Add a graph window"}])
        self.assertEqual(p["tail"], "say")
        self.assertFalse(any(s["open"] for s in p["steps"]))

    def test_the_head_of_the_spine_is_open_until_its_result_lands(self):
        rows = [user("go"), tool("m1", "t1", "Bash", command="pytest tests/test_graph.py",
                                 description="Run the trail tests")]
        path = self.write("s.jsonl", rows)
        p = self.read(path)
        self.assertTrue(p["steps"][-1]["open"])
        self.assertEqual(p["tail"], "call")
        self.assertEqual(p["steps"][-1]["label"], "Run the trail tests")
        self.assertEqual(p["files"][0]["path"], "/repo/tests/test_graph.py")
        self.assertEqual(p["steps"][-1]["files"], [[0, "run"]])
        # the result arrives: closed, and the trail grew by the appended bytes only
        self.write("s.jsonl", [result("t1")], mode="a")
        p = self.read(path)
        self.assertFalse(p["steps"][-1]["open"])
        self.assertEqual(p["tail"], "result")
        self.assertEqual(len(p["steps"]), 1)

    def test_prompts_split_the_spine_and_noise_is_not_a_prompt(self):
        rows = [
            user("first ask"),
            tool("m1", "t1", "Write", file_path="/repo/new.py", content="x"), result("t1"),
            user("<system-reminder>injected</system-reminder>"),
            user("[Request interrupted by user]"),
            user("meta", isMeta=True),
            user("second ask"),
            tool("m2", "t2", "Read", file_path="/repo/new.py"), result("t2"),
        ]
        p = self.read(self.write("s.jsonl", rows))
        self.assertEqual([(q["i"], q["text"]) for q in p["prompts"]], [(0, "first ask"), (1, "second ask")])
        self.assertEqual(p["files"][0]["writes"], 1)
        self.assertEqual(p["files"][0]["reads"], 1)

    def test_sidechains_stay_off_the_spine(self):
        rows = [
            user("go"),
            tool("m1", "t1", "Agent", description="Explore the repo", prompt="..."),
            claude("assistant", isSidechain=True, cwd="/repo",
                   message={"id": "side", "content": [{"type": "tool_use", "id": "s1", "name": "Read",
                                                        "input": {"file_path": "/repo/hidden.py"}}]}),
            result("t1"),
        ]
        p = self.read(self.write("s.jsonl", rows))
        self.assertEqual(len(p["steps"]), 1)
        self.assertEqual(p["steps"][0]["kind"], "agent")
        self.assertEqual(p["steps"][0]["label"], "agent: Explore the repo")
        self.assertEqual(p["files"], [])

    def test_a_missing_or_odd_transcript_is_not_an_error(self):
        self.assertIsNone(self.trails.read(os.path.join(self.dir, "nope.jsonl"), "claude"))
        path = self.write("s.jsonl", ["not json", "[1,2]", user("hello"), "{\"type\": \"assistant\"}"])
        p = self.read(path)
        self.assertEqual(len(p["prompts"]), 1)
        self.assertEqual(p["steps"], [])


class ShellPaths(unittest.TestCase):
    def paths(self, command, cwd="/repo"):
        return graph.paths_in_command(command, cwd)

    def test_reads_runs_and_writes_by_what_the_command_does(self):
        self.assertEqual(self.paths("sed -n 1,40p ui.html"), [("/repo/ui.html", "read")])
        self.assertEqual(self.paths("python3 build.py > out.log"),
                         [("/repo/build.py", "run"), ("/repo/out.log", "write")])
        self.assertEqual(self.paths("sed -i '' 's/a/b/' src/x.py"), [("/repo/src/x.py", "edit")])
        self.assertEqual(self.paths("cp ui.html ~/.local/share/fleet/ui.html"),
                         [("/repo/ui.html", "read"),
                          (os.path.expanduser("~/.local/share/fleet/ui.html"), "write")])
        self.assertEqual(self.paths("cd /elsewhere && pytest tests/test_x.py"),
                         [("/elsewhere/tests/test_x.py", "run")])

    def test_patterns_flags_urls_and_folders_are_not_files(self):
        self.assertEqual(self.paths("grep -n 's/^#//' ui.html | head"), [("/repo/ui.html", "read")])
        self.assertEqual(self.paths("ls -la .claude/skills/ tools/"), [])
        self.assertEqual(self.paths("curl https://example.com/a.json"), [])
        self.assertEqual(self.paths("grep -rn P2/P3/P4 docs/TASKS.md"), [("/repo/docs/TASKS.md", "read")])
        self.assertEqual(self.paths("cat > /dev/null"), [])
        self.assertEqual(self.paths("rg --files -g '*.py'"), [])

    def test_after_cd_to_a_variable_nothing_relative_is_placed(self):
        self.assertEqual(self.paths("S=/tmp/x; cd $S && node shot.mjs > run.log; cat /etc/hosts"),
                         [("/etc/hosts", "read")])

    def test_the_same_file_named_twice_keeps_the_stronger_verb(self):
        self.assertEqual(self.paths("cat x.md; sed -i 's/a/b/' x.md"), [("/repo/x.md", "edit")])

    def test_heredoc_bodies_are_skipped(self):
        cmd = "cat > notes.md <<'EOF'\nsee other.py and more.py\nEOF"
        self.assertEqual(self.paths(cmd), [("/repo/notes.md", "write")])

    def test_line_suffixes_and_trailing_punctuation_are_stripped(self):
        self.assertEqual(self.paths("code ui.html:120,"), [("/repo/ui.html", "run")])


def codex(at, payload, rtype="response_item"):
    return json.dumps({"type": rtype, "timestamp": at, "payload": payload})


class CodexTrail(TrailFiles):
    def test_exec_calls_reasoning_and_patches(self):
        at = "2026-09-14T21:09:54.334Z"
        rows = [
            codex(at, {"cwd": "/work"}, "session_meta"),
            codex(at, {"type": "message", "role": "developer",
                       "content": [{"type": "input_text", "text": "You are Codex"}]}),
            codex(at, {"type": "message", "role": "user",
                       "content": [{"type": "input_text", "text": "Tidy the caches and tell me what you removed"}]}),
            codex(at, {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Start by listing what is there."}]}),
            codex(at, {"type": "custom_tool_call", "name": "exec", "call_id": "c1",
                       "input": 'const r = await tools.exec_command({"cmd":"du -sh .cache; cat notes.md","workdir":"/work"});'}),
            codex(at, {"type": "custom_tool_call_output", "call_id": "c1", "output": []}),
            codex(at, {"type": "custom_tool_call", "name": "apply_patch", "call_id": "c2",
                       "input": "*** Begin Patch\n*** Update File: notes.md\n@@\n-a\n+b\n*** Add File: new.txt\n+hi\n*** End Patch"}),
            codex(at, {"type": "custom_tool_call_output", "call_id": "c2", "output": []}),
            codex(at, {"type": "message", "role": "assistant",
                       "content": [{"type": "output_text", "text": "Removed 2 GB of caches."}]}),
        ]
        p = self.read(self.write("r.jsonl", rows), "codex")
        self.assertEqual([q["text"] for q in p["prompts"]], ["Tidy the caches and tell me what you removed"])
        s0, s1, s2 = p["steps"]
        self.assertEqual(s0["think"], "Start by listing what is there.")
        self.assertEqual(s0["label"], "du -sh .cache; cat notes.md")
        self.assertEqual(s0["files"], [[0, "read"]])
        self.assertEqual(p["files"][0]["path"], "/work/notes.md")
        self.assertEqual(s1["label"], "patch notes.md, new.txt")
        self.assertEqual(s1["files"], [[0, "edit"], [1, "write"]])
        self.assertEqual(s2["kind"], "say")
        self.assertEqual(s2["label"], "Removed 2 GB of caches.")
        self.assertEqual(p["tail"], "say")


class Locating(unittest.TestCase):
    def test_antigravity_and_unknown_sessions_say_why(self):
        class NoTranscripts:
            def path_for(self, *a):
                return None
        out = graph.build({"id": "x", "provider": "antigravity", "name": "n", "state": "idle"}, NoTranscripts())
        self.assertFalse(out["available"])
        self.assertIn("Antigravity", out["why"])
        out = graph.build({"id": "y", "provider": "claude", "sessionId": "", "cwd": ""}, NoTranscripts())
        self.assertEqual(out["why"], "nothing written to disk yet")
        self.assertFalse(graph.build(None, NoTranscripts())["available"])


if __name__ == "__main__":
    unittest.main()
