"""Black-box tests for agent_channel_lvl0.py: every test drives the real CLI in separate processes.

Run:  python -m unittest test_agent_channel_lvl0 -v
Set AGENT_CHANNEL_SCRIPT to test another copy of the script (used by mutation_check.py).
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

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


def load_script() -> Any:
    """The script as a module, for the few things a subprocess cannot reach (injected OS failures, PATH search)."""
    spec = importlib.util.spec_from_file_location("agent_channel_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call(module: Any, *argv: str, stdin: bytes = b"") -> tuple[int, dict[str, Any]]:
    """Run module.main() in-process with this argv; return its exit code and the one JSON object it printed."""
    buf = io.StringIO()
    code: Any = None
    fake_stdin = types.SimpleNamespace(buffer=io.BytesIO(stdin))
    with mock.patch.object(sys, "argv", ["agent_channel", *argv]), mock.patch.object(sys, "stdin", fake_stdin), \
            contextlib.redirect_stdout(buf):
        try:
            module.main()
        except SystemExit as exc:
            code = exc.code
    return int(code), json.loads(buf.getvalue())


class FakeProc:
    """A started secondary whose stdin is already closed on its side, so delivering the prompt fails."""
    pid = 999999999

    def __init__(self) -> None:
        self.killed = False
        self.stdin = mock.Mock()
        self.stdin.write.side_effect = BrokenPipeError("pipe closed by the child")

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        return 0


class ChannelTest(unittest.TestCase):
    def setUp(self) -> None:
        # Detached children spawned by some tests may hold their log open a moment after the test ends.
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
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
        code, result = run("init", self.tmp.name, "--session", "t")
        self.assertEqual((code, result["status"]), (4, "error"))
        self.assertIn("cannot create the channel", result["body"])

    def test_unreadable_body_file_is_a_structured_error(self) -> None:
        missing = str(Path(self.tmp.name) / "no-such-file.txt")
        code, result = run("send", self.dir, "primary", "--body-file", missing)
        self.assertEqual((code, result["status"]), (4, "error"))
        self.assertIn("cannot read the body", result["body"])

    def test_recv_survives_a_first_message_that_became_unreadable(self) -> None:
        # Message 0 is broken, the newest message (the secondary's own) is fine: only the max-wait reread sees it.
        (Path(self.dir) / "ch-p2s-000.json").write_text('{"header": {', encoding="utf-8")
        (Path(self.dir) / "ch-s2p-000.json").write_text('{"header": {}, "body": "x"}', encoding="utf-8")
        code, result = self.recv("secondary")
        self.assertEqual((code, result["status"]), (3, "closed"))
        self.assertTrue(result["body"].startswith("ERROR:"))

    def test_send_that_was_waiting_for_stdin_is_refused_after_a_timeout(self) -> None:
        self.send("primary", "task", "--max-wait-minutes", "0.02")
        pending = start("send", self.dir, "secondary")  # blocked on stdin while the channel dies
        time.sleep(4)
        code, result = self.recv("primary")
        self.assertEqual((code, result["status"]), (3, "closed"))
        code, result = finish(pending, "late reply")
        self.assertEqual((code, result["status"]), (3, "closed"))
        self.assertNotIn("ch-s2p-000.json", self.messages())

    def test_send_that_was_waiting_for_stdin_is_refused_after_stop(self) -> None:
        self.send("primary", "task")
        pending = start("send", self.dir, "secondary")
        time.sleep(2)
        self.assertEqual(run("stop", self.dir)[1]["status"], "stopped")
        code, result = finish(pending, "late reply")
        self.assertEqual((code, result["status"], result["by"]), (3, "closed", "owner"))
        self.assertNotIn("ch-s2p-000.json", self.messages())

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
        procs = [start("send", self.dir, "primary") for _ in range(16)]
        time.sleep(1.5)  # every sender is now blocked reading stdin
        for i, p in enumerate(procs):
            assert p.stdin is not None
            p.stdin.write(f"body {i}".encode())
            p.stdin.flush()
        for p in procs:  # release them as close together as a loop allows, so their writes overlap
            assert p.stdin is not None
            p.stdin.close()
        results = [finish(p) for p in procs]
        statuses = sorted(r["status"] for _, r in results)
        self.assertEqual(statuses, ["error"] * 15 + ["sent"])
        self.assertEqual(self.messages(), ["ch-p2s-000.json"])
        winner = next(i for i, (_, r) in enumerate(results) if r["status"] == "sent")
        self.assertEqual(self.recv("secondary")[1]["body"], f"body {winner}")
        self.assertEqual([p.name for p in Path(self.dir).iterdir() if p.name.endswith(".tmp")], [])

    def test_empty_body_rejected(self) -> None:
        code, result = self.send("primary", "   \n")
        self.assertEqual((code, result["status"]), (4, "error"))

    def test_spawn_launches_a_secondary_that_gets_exactly_the_prompt_on_stdin(self) -> None:
        parent = Path(self.tmp.name) / "spawned"
        # Fake secondary: read the prompt from stdin, find the channel dir in it, reply with the stdin length.
        fake = (
            "import re,subprocess,sys;"
            "p=sys.stdin.buffer.read().decode('utf-8');"
            "d=re.search(r'recv (.+?) secondary', p).group(1);"
            "import hashlib;"
            "subprocess.run([sys.executable, %r, 'send', d, 'secondary'],"
            " input=('stdin sha256: %%s' %% hashlib.sha256(p.encode('utf-8')).hexdigest()).encode())"
        ) % SCRIPT
        template = f'"{sys.executable}" -c "{fake}" "{{prompt_file}}"'
        code, result = run("spawn", str(parent), "--via", "command", "--command", template, "--session", "x",
                           body="first task")
        self.assertEqual((code, result["status"], result["file"]), (0, "spawned", "ch-p2s-000.json"))
        d = result["dir"]
        prompt = (Path(d) / ".secondary-prompt.txt").read_text(encoding="utf-8")
        self.assertIn(d, prompt)
        self.assertGreater(prompt.count("\n"), 3, "the start prompt is multi-line; that is what shims truncate")
        code, result = run("recv", d, "primary", "--block-seconds", "30")
        self.assertEqual((code, result["status"]), (0, "message"))
        self.assertEqual(result["body"], f"stdin sha256: {hashlib.sha256(prompt.encode('utf-8')).hexdigest()}",
                         "the child must receive exactly the saved prompt, byte for byte")
        self.assertEqual(run("recv", d, "secondary", "--block-seconds", "0")[1]["status"], "waiting")

    def test_spawn_validates_before_creating_anything_and_can_be_retried(self) -> None:
        parent = Path(self.tmp.name) / "retry"
        code, result = run("spawn", str(parent), "--via", "command", "--command", "echo hi", "--session", "x",
                           body="task")
        self.assertEqual((code, result["status"]), (4, "error"))
        self.assertFalse(parent.exists(), "a rejected spawn must leave no channel behind")
        env = {**os.environ, "PATH": ""}  # no claude on PATH: validation must fail before the channel exists
        proc = subprocess.Popen([sys.executable, SCRIPT, "spawn", str(parent), "--via", "claude", "--session", "x"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        code, result = finish(proc, "task")
        self.assertEqual((code, result["status"]), (4, "error"))
        self.assertFalse(parent.exists())
        fake = "import sys,pathlib; sys.stdin.read(); pathlib.Path('done').write_text('1')"
        template = f'"{sys.executable}" -c "{fake}" "{{prompt_file}}"'
        code, result = run("spawn", str(parent), "--via", "command", "--command", template, "--session", "x",
                           body="task")
        self.assertEqual((code, result["status"]), (0, "spawned"), "same session must work once the launcher is valid")
        deadline = time.monotonic() + 20
        while not (Path(result["dir"]) / "done").exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertTrue((Path(result["dir"]) / "done").exists(), "spawned child did not run to completion")

    def test_selftest_is_silent_then_passes(self) -> None:
        proc = start("selftest", "--seconds", "3")
        assert proc.stdout is not None
        lines: list[bytes] = []
        reader = threading.Thread(target=lambda: lines.append(proc.stdout.readline()), daemon=True)  # type: ignore[union-attr]
        reader.start()
        reader.join(1.5)
        self.assertEqual(lines, [], "selftest printed something before its silent period was over")
        reader.join(30)
        code = proc.wait(timeout=30)
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            if pipe:
                pipe.close()
        self.assertEqual((code, json.loads(lines[0])["status"]), (0, "pass"))


class SpawnFailureTest(unittest.TestCase):
    """Failures an OS rarely produces on demand: injected into the script loaded in-process."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.module = load_script()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def spawn(self) -> tuple[int, dict[str, Any], Path]:
        parent = Path(self.tmp.name) / "spawned"
        code, result = call(self.module, "spawn", str(parent), "--via", "command", "--command", "x {prompt_file}",
                            "--session", "s", stdin=b"first task")
        return code, result, parent / "s_agent_channel"

    def assert_terminal(self, code: int, result: dict[str, Any], d: Path) -> None:
        self.assertEqual((code, result["status"], result["by"]), (3, "closed", "primary"))
        self.assertTrue(result["body"].startswith("ERROR: could not start the secondary"), result["body"])
        self.assertTrue((d / "ch-abort-primary.json").exists(), "the primary would wait for a secondary that never ran")
        code, result = call(self.module, "recv", str(d), "primary", "--block-seconds", "0")
        self.assertEqual((code, result["status"]), (3, "closed"))

    def test_failed_prompt_delivery_stops_the_child_and_closes_the_channel(self) -> None:
        proc = FakeProc()
        with mock.patch.object(self.module.subprocess, "Popen", return_value=proc), \
                mock.patch.object(self.module.subprocess, "run"):
            code, result, d = self.spawn()
        self.assert_terminal(code, result, d)
        self.assertTrue(proc.killed, "a child that never got its prompt was left running")

    def test_process_start_failure_closes_the_channel(self) -> None:
        with mock.patch.object(self.module.subprocess, "Popen", side_effect=OSError("[WinError 193] not a valid exe")):
            code, result, d = self.spawn()
        self.assert_terminal(code, result, d)

    def test_setup_failure_after_message_zero_closes_the_channel(self) -> None:
        popen = mock.Mock()
        with mock.patch.object(Path, "write_text", side_effect=PermissionError("denied")), \
                mock.patch.object(self.module.subprocess, "Popen", popen):
            code, result, d = self.spawn()
        self.assert_terminal(code, result, d)
        popen.assert_not_called()


class CodexDiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.module = load_script()
        root = Path(self.tmp.name)
        self.sandbox, self.good, self.empty = root / "sandbox" / "codex.exe", root / "good" / "codex.exe", root / "app"
        for exe in (self.sandbox, self.good):
            exe.parent.mkdir(parents=True)
            exe.write_text("not a real exe", encoding="utf-8")
            exe.chmod(0o755)
        self.empty.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def find(self, *path: Path) -> str:
        env = {"PATH": os.pathsep.join(str(p.parent) for p in path), "LOCALAPPDATA": str(self.empty)}
        with mock.patch.dict(os.environ, env), mock.patch.object(self.module, "SANDBOX_CODEX", self.sandbox):
            return str(self.module.codex_exe())

    def test_sandbox_copy_first_on_path_does_not_hide_a_usable_cli_later_on_path(self) -> None:
        self.assertEqual(Path(self.find(self.sandbox, self.good)).resolve(), self.good.resolve())

    def test_sandbox_copy_alone_is_an_error_not_a_fallback(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as caught:
            self.find(self.sandbox)
        self.assertEqual(caught.exception.code, 4)
        self.assertEqual(json.loads(buf.getvalue())["status"], "error")


if __name__ == "__main__":
    unittest.main()
