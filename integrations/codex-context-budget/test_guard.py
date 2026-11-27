import concurrent.futures
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

import guard


class ContextBudgetTests(unittest.TestCase):
    def test_portable_apply_requires_explicit_home_and_leaves_ambient_home_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            env = dict(os.environ, CODEX_HOME=str(home))
            result = subprocess.run([sys.executable, '-B', str(Path(guard.__file__)),
                                     'install', '--apply'], env=env, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertFalse((home / 'hooks.json').exists())

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.policy = {"schema_version": 1, "warning_bytes": 100,
                       "maximum_bytes": 200, "maximum_tool_image_bytes": 90}

    def picture(self, identifier, count=50):
        return {"hook_event_name": "PostToolUse", "session_id": "fixture-session", "turn_id": "turn-1",
                "tool_use_id": identifier, "tool_response": {"content": [
                    {"type": "image", "mimeType": "image/png", "data": "x" * count}]}}

    def call(self, payload):
        return guard.hook(payload, self.home, self.policy)

    def test_normal_image_is_retained_and_warning_is_once_per_compaction_window(self):
        self.assertEqual({}, self.call(self.picture("first", 60)))
        warning = self.call(self.picture("second", 60))
        self.assertIn("systemMessage", warning)
        self.assertNotIn("decision", warning)
        self.assertEqual({}, self.call(self.picture("second", 60)))
        self.assertEqual({}, self.call(self.picture("third", 30)))
        self.assertEqual({}, self.call({"hook_event_name": "UserPromptSubmit", "session_id": "fixture-session",
                                       "turn_id": "later-turn"}))
        state = guard.read_json(guard.state_path(self.home, "fixture-session"))
        self.assertEqual(150, state["estimated_bytes"])
        self.assertNotIn("xxxxx", json.dumps(state))

    def test_single_large_tool_result_is_rejected_before_accumulating(self):
        result = self.call(self.picture("large", 91))
        self.assertEqual("block", result["decision"])
        state = guard.read_json(guard.state_path(self.home, "fixture-session"))
        self.assertEqual(0, state["estimated_bytes"])

    def test_concurrent_images_cannot_all_pass_the_same_remaining_budget(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda index: self.call(self.picture(str(index), 60)), range(8)))
        self.assertEqual(3, sum(result.get("decision") != "block" for result in results))
        self.assertEqual(180, guard.read_json(guard.state_path(self.home, "fixture-session"))["estimated_bytes"])

    def test_wire_baseline_and_compaction_reset(self):
        with closing(sqlite3.connect(self.home / "logs_2.sqlite")) as connection:
            connection.execute("CREATE TABLE logs (id INTEGER PRIMARY KEY, ts INTEGER, ts_nanos INTEGER, "
                               "feedback_log_body TEXT, target TEXT, thread_id TEXT)")
            now = time.time_ns()
            connection.execute("INSERT INTO logs VALUES (1,?,?,?,?,?)", (
                now // 1_000_000_000, now % 1_000_000_000,
                "Compressed request body post_compression_bytes=170", "codex_http_client::request", "fixture-session"))
            connection.commit()
        self.assertEqual("block", self.call(self.picture("over-wire", 40))["decision"])
        self.call({"hook_event_name": "PostCompact", "session_id": "fixture-session"})
        self.assertEqual({}, self.call(self.picture("after-compact", 60)))

    def test_prompts_and_stop_only_warn_even_above_the_image_budget(self):
        path = guard.state_path(self.home, "fixture-session")
        for event in ("UserPromptSubmit", "Stop"):
            for budget in (200, 220, 1000):
                with self.subTest(event=event, budget=budget):
                    state = guard.new_state("fixture-session")
                    state["estimated_bytes"] = budget
                    guard.write_json(path, state)
                    result = self.call({"hook_event_name": event, "session_id": "fixture-session"})
                    self.assertIn("systemMessage", result)
                    self.assertNotIn("decision", result)
                    self.assertNotIn("continue", result)
        self.assertEqual({}, self.call({"hook_event_name": "PostToolUse", "session_id": "fixture-session",
                                        "tool_response": "ordinary text output"}))
        self.assertEqual("block", self.call(self.picture("additional-image", 10))["decision"])

    def test_native_mcp_and_json_wrapped_images(self):
        url = "data:image/png;base64,abc"
        wrapped = json.dumps({"type": "input_image", "image_url": url})
        self.assertEqual(len(url), guard.image_bytes(wrapped))
        self.assertEqual(len(url) + 4, guard.image_bytes([
            {"image_url": url}, {"type": "image", "data": "abcd"}]))
        self.assertEqual(0, guard.image_bytes("ordinary tool output"))

    def test_install_is_idempotent_and_uninstall_keeps_other_hooks(self):
        path = self.home / "hooks.json"
        original = {"description": "existing", "hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "existing-command"}]}]}}
        guard.write_json(path, original)
        policy = Path(guard.__file__).parent / "policy.json"
        guard.configure_hooks(self.home, policy, False)
        self.assertEqual(original, guard.read_json(path))
        guard.configure_hooks(self.home, policy, True)
        self.assertFalse(guard.configure_hooks(self.home, policy, True)["changed"])
        guard.configure_hooks(self.home, policy, True, remove=True)
        self.assertEqual(original, guard.read_json(path))

    @unittest.skipUnless(os.name == "nt", "Windows command compatibility")
    def test_installed_command_runs_in_both_windows_shells(self):
        policy = Path(guard.__file__).parent / "policy.json"
        guard.configure_hooks(self.home, policy, True)
        command = guard.read_json(self.home / "hooks.json")["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
        for shell in (["cmd.exe", "/d", "/s", "/c"],
                      ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]):
            result = subprocess.run([*shell, command], input=json.dumps(self.picture("shell-check", 10)),
                                    capture_output=True, text=True, encoding="utf-8", timeout=10)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual({}, json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
