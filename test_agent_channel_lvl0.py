"""Black-box tests for agent_channel_lvl0.py: every test drives the real CLI in separate processes.

Run:  python -m unittest test_agent_channel_lvl0 -v
Set AGENT_CHANNEL_SCRIPT to test another copy of the script (used by mutation_check.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

# Sleeps around timeouts allow 2 s of slack: exFAT rounds modification times up to 2 s.
SCRIPT = os.environ.get("AGENT_CHANNEL_SCRIPT", str(Path(__file__).with_name("agent_channel_lvl0.py")))


def start(*args: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen([sys.executable, SCRIPT, *args],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def finish(proc: subprocess.Popen[bytes], body: str | None = None) -> tuple[int, dict[str, Any]]:
    stdout, stderr = proc.communicate(None if body is None else body.encode("utf-8"), timeout=60)
    try:
        result = json.loads(stdout)
    except ValueError:
        raise AssertionError(f"not one JSON object: {stdout!r} stderr={stderr!r}") from None
    return proc.returncode, result


def run(*args: str, body: str | None = None) -> tuple[int, dict[str, Any]]:
    return finish(start(*args), body)


class ChannelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        code, result = run("init", self.tmp.name, "--session", "t")
        self.assertEqual((code, result["status"]), (0, "created"))
        self.dir = result["dir"]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def send(self, role: str, body: str, *extra: str) -> tuple[int, dict[str, Any]]:
        return run("send", self.dir, role, *extra, body=body)

    def recv(self, role: str, block: str = "0") -> tuple[int, dict[str, Any]]:
        return run("recv", self.dir, role, "--block-seconds", block)

    def messages(self) -> list[str]:
        return sorted(p.name for p in Path(self.dir).iterdir() if p.name.startswith("ch-"))

    def test_init_refuses_existing_channel(self) -> None:
        proc = start("init", self.tmp.name, "--session", "t")
        proc.communicate(timeout=60)
        self.assertNotEqual(proc.returncode, 0)

    def test_secondary_cannot_send_first(self) -> None:
        code, result = self.send("secondary", "hello")
        self.assertEqual((code, result["status"]), (4, "error"))
        self.assertEqual(self.messages(), [])

    def test_no_double_send(self) -> None:
        self.assertEqual(self.send("primary", "one")[0], 0)
        code, result = self.send("primary", "two")
        self.assertEqual((code, result["status"]), (4, "error"))
        self.assertEqual(self.messages(), ["ch-p2s-000.json"])

    def test_roundtrip_preserves_awkward_text(self) -> None:
        body = 'quote " backslash \\ path C:\\tmp\\x\nnewline\ttab ü 日本語 {"json": [1, 2]}'
        self.send("primary", body)
        code, result = self.recv("secondary")
        self.assertEqual((code, result["status"], result["file"]), (0, "message", "ch-p2s-000.json"))
        self.assertEqual(result["body"], body)

    def test_body_file(self) -> None:
        path = Path(self.tmp.name) / "body.txt"
        path.write_text("from a file ü", encoding="utf-8")
        run("send", self.dir, "primary", "--body-file", str(path))
        self.assertEqual(self.recv("secondary")[1]["body"], "from a file ü")

    def test_bom_from_powershell_is_stripped(self) -> None:
        path = Path(self.tmp.name) / "body.txt"
        path.write_bytes("﻿reply from PowerShell".encode("utf-8"))
        run("send", self.dir, "primary", "--body-file", str(path))
        self.assertEqual(self.recv("secondary")[1]["body"], "reply from PowerShell")
        self.send("secondary", "ok")
        code, result = run("send", self.dir, "primary", body="﻿piped")
        self.assertEqual(code, 0)
        self.assertEqual(self.recv("secondary")[1]["body"], "piped")

    def test_recv_is_idempotent_and_stateless(self) -> None:
        self.send("primary", "task")
        self.assertEqual(self.recv("secondary"), self.recv("secondary"))

    def test_recv_reports_waiting(self) -> None:
        self.send("primary", "task")
        code, result = self.recv("primary")
        self.assertEqual((code, result["status"], result["expecting"]), (2, "waiting", "ch-s2p-000.json"))

    def test_blocked_recv_wakes_when_peer_sends(self) -> None:
        self.send("primary", "task")
        waiter = start("recv", self.dir, "primary", "--block-seconds", "30")
        time.sleep(1)
        self.assertIsNone(waiter.poll(), "recv returned before the peer sent anything")
        self.send("secondary", "done")
        code, result = finish(waiter)
        self.assertEqual((code, result["status"], result["body"]), (0, "message", "done"))

    def test_multi_round_numbering(self) -> None:
        for i in range(3):
            self.send("primary", f"p{i}")
            self.assertEqual(self.recv("secondary")[1]["body"], f"p{i}")
            self.send("secondary", f"s{i}")
            self.assertEqual(self.recv("primary")[1]["body"], f"s{i}")
        self.assertEqual(self.messages(), [f"ch-{d}-00{i}.json" for d in ("p2s", "s2p") for i in range(3)])

    def test_end_closes_for_both_sides(self) -> None:
        self.send("primary", "task")
        code, result = self.send("secondary", "REFUSED: cannot stay awake", "--end")
        self.assertEqual((code, result["status"]), (3, "closed"))
        code, result = self.recv("primary")
        self.assertEqual((code, result["status"], result["by"]), (3, "closed", "secondary"))
        self.assertEqual(result["body"], "REFUSED: cannot stay awake")
        before = self.messages()
        for role in ("primary", "secondary"):
            code, result = self.send(role, "more")
            self.assertEqual((code, result["status"]), (3, "closed"))
        self.assertEqual(self.messages(), before)

    def test_timeout_closes_and_late_reply_is_refused(self) -> None:
        self.send("primary", "task", "--max-wait-minutes", "0.02")
        time.sleep(4)
        code, result = self.recv("primary")
        self.assertEqual((code, result["status"], result["by"]), (3, "closed", "primary"))
        self.assertTrue(result["body"].startswith("TIMEOUT:"))
        code, result = self.send("secondary", "late")
        self.assertEqual((code, result["status"]), (3, "closed"))
        self.assertTrue(result["body"].startswith("TIMEOUT:"))
        self.assertNotIn("ch-s2p-000.json", self.messages())

    def test_timeout_clock_survives_rerun(self) -> None:
        self.send("primary", "task", "--max-wait-minutes", "0.05")  # 3 s
        self.assertEqual(self.recv("primary")[1]["status"], "waiting")
        time.sleep(6)
        self.assertEqual(self.recv("primary")[1]["status"], "closed")

    def test_first_message_sets_wait_for_secondary_too(self) -> None:
        self.send("primary", "task", "--max-wait-minutes", "0.02")
        self.send("secondary", "reply")
        time.sleep(4)
        code, result = self.recv("secondary")
        self.assertEqual((code, result["by"]), (3, "secondary"))
        self.assertTrue(result["body"].startswith("TIMEOUT:"))

    def test_empty_channel_times_out_from_directory_age(self) -> None:
        old = time.time() - 2 * 3600
        os.utime(self.dir, (old, old))
        code, result = self.recv("secondary")
        self.assertEqual((code, result["status"]), (3, "closed"))
        self.assertTrue(result["body"].startswith("TIMEOUT:"))

    def test_stop_interrupts_a_blocked_recv(self) -> None:
        self.send("primary", "task")
        waiter = start("recv", self.dir, "primary", "--block-seconds", "60")
        time.sleep(1)
        self.assertIsNone(waiter.poll(), "recv returned before the owner stopped the channel")
        began = time.monotonic()
        code, result = run("stop", self.dir)
        self.assertEqual((code, result["status"]), (0, "stopped"))
        code, result = finish(waiter)
        self.assertLess(time.monotonic() - began, 30, "recv did not notice STOP within one poll")
        self.assertEqual((code, result["status"], result["by"]), (3, "closed", "owner"))
        self.assertTrue(result["body"].startswith("STOP:"))

    def test_stop_closes_for_both_sides_and_is_idempotent(self) -> None:
        self.send("primary", "task")
        self.assertEqual(run("stop", self.dir)[1]["status"], "stopped")
        self.assertEqual(run("stop", self.dir)[1]["status"], "stopped")
        before = self.messages()
        for role in ("primary", "secondary"):
            code, result = self.send(role, "more")
            self.assertEqual((code, result["status"], result["by"]), (3, "closed", "owner"))
            code, result = self.recv(role)
            self.assertEqual((code, result["status"], result["by"]), (3, "closed", "owner"))
        self.assertEqual(self.messages(), before)

    def test_corrupt_message_closes_with_error(self) -> None:
        (Path(self.dir) / "ch-p2s-000.json").write_text('{"header": {}', encoding="utf-8")
        code, result = self.recv("secondary")
        self.assertEqual((code, result["status"]), (3, "closed"))
        self.assertTrue(result["body"].startswith("ERROR:"))

    def test_wrong_shape_closes_with_error(self) -> None:
        for content in ('{"header": {}, "body": 5}', '{"header": {}, "body": "x", "extra": 1}',
                        '{"header": {"end": "yes"}, "body": "x"}', '["header", "body"]'):
            with self.subTest(content=content):
                d = Path(tempfile.mkdtemp(dir=self.tmp.name))
                (d / "ch-p2s-000.json").write_text(content, encoding="utf-8")
                code, result = run("recv", str(d), "secondary", "--block-seconds", "0")
                self.assertEqual((code, result["status"]), (3, "closed"))
                self.assertTrue(result["body"].startswith("ERROR:"))

    def test_out_of_sequence_closes_with_error(self) -> None:
        # The newest file is well-formed, so only the sequence check can notice ch-p2s-000 is missing.
        for missing_first in ("ch-s2p-000.json", "ch-p2s-001.json"):
            (Path(self.dir) / missing_first).write_text('{"header": {}, "body": "x"}', encoding="utf-8")
        code, result = self.recv("secondary")
        self.assertEqual((code, result["status"]), (3, "closed"))
        self.assertTrue(result["body"].startswith("ERROR: messages out of sequence"))

    def test_send_refuses_while_another_writer_holds_the_temp_file(self) -> None:
        (Path(self.dir) / ".ch-p2s-000.json.tmp").write_text("half-written", encoding="utf-8")
        code, result = self.send("primary", "task")
        self.assertEqual((code, result["status"]), (4, "error"))
        self.assertEqual(self.messages(), [])

    def test_other_files_are_ignored(self) -> None:
        for junk in (".selftest-primary", "notes.txt", "ch-p2s-0000.json", "ch-p2s-00.json", "xch-s2p-000.json"):
            (Path(self.dir) / junk).write_text("junk", encoding="utf-8")
        self.send("primary", "task")
        self.assertEqual(self.recv("secondary")[1]["body"], "task")

    def test_extra_header_fields_are_ignored(self) -> None:
        (Path(self.dir) / "ch-p2s-000.json").write_text(
            '{"header": {"priority": "high"}, "body": "task"}', encoding="utf-8")
        self.assertEqual(self.recv("secondary")[1]["body"], "task")

    def test_messages_are_never_rewritten(self) -> None:
        self.send("primary", "task")
        first = Path(self.dir) / "ch-p2s-000.json"
        original = first.read_bytes()
        self.send("secondary", "reply")
        self.send("primary", "bye", "--end")
        self.recv("secondary")
        self.assertEqual(first.read_bytes(), original)

    def test_concurrent_senders_produce_exactly_one_message(self) -> None:
        procs = [start("send", self.dir, "primary") for _ in range(8)]
        results = [finish(p, f"body {i}") for i, p in enumerate(procs)]
        statuses = sorted(r["status"] for _, r in results)
        self.assertEqual(statuses, ["error"] * 7 + ["sent"])
        self.assertEqual(self.messages(), ["ch-p2s-000.json"])
        winner = next(i for i, (_, r) in enumerate(results) if r["status"] == "sent")
        self.assertEqual(self.recv("secondary")[1]["body"], f"body {winner}")
        self.assertEqual([p.name for p in Path(self.dir).iterdir() if p.name.endswith(".tmp")], [])

    def test_empty_body_rejected(self) -> None:
        code, result = self.send("primary", "   \n")
        self.assertEqual((code, result["status"]), (4, "error"))

    def test_spawn_launches_a_secondary_that_can_reply(self) -> None:
        parent = Path(self.tmp.name) / "spawned"
        # Fake secondary: read the prompt file, find the channel dir in it, reply with the prompt's length.
        fake = (
            "import re,subprocess,sys,pathlib;"
            "p=pathlib.Path(sys.argv[1]).read_text(encoding='utf-8');"
            "d=re.search(r'recv (.+?) secondary', p).group(1);"
            "subprocess.run([sys.executable, %r, 'send', d, 'secondary'], input=('prompt chars: %%d' %% len(p)).encode())"
        ) % SCRIPT
        template = f'"{sys.executable}" -c "{fake}" "{{prompt_file}}"'
        code, result = run("spawn", str(parent), "--via", "command", "--command", template, "--session", "x",
                           body="first task")
        self.assertEqual((code, result["status"], result["file"]), (0, "spawned", "ch-p2s-000.json"))
        d = result["dir"]
        prompt = (Path(d) / ".secondary-prompt.txt").read_text(encoding="utf-8")
        self.assertIn(d, prompt)
        code, result = run("recv", d, "primary", "--block-seconds", "30")
        self.assertEqual((code, result["status"]), (0, "message"))
        self.assertEqual(result["body"], f"prompt chars: {len(prompt)}")
        self.assertEqual(run("recv", d, "secondary", "--block-seconds", "0")[1]["status"], "waiting")

    def test_spawn_rejects_bad_command_template(self) -> None:
        code, result = run("spawn", str(Path(self.tmp.name) / "bad"), "--via", "command", "--command", "echo hi",
                           "--session", "x", body="task")
        self.assertEqual((code, result["status"]), (4, "error"))

    def test_selftest_is_silent_then_passes(self) -> None:
        began = time.monotonic()
        code, result = run("selftest", "--seconds", "2")
        self.assertEqual((code, result["status"]), (0, "pass"))
        self.assertGreaterEqual(time.monotonic() - began, 2)


if __name__ == "__main__":
    unittest.main()
