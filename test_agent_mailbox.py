"""Black-box tests for agent_mailbox.py: every test drives the real CLI in separate processes.

Run:  python -m unittest test_agent_mailbox -v
Set AGENT_MAILBOX_SCRIPT to test another copy of the script (used by mutation_check_mailbox.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

SCRIPT = os.environ.get("AGENT_MAILBOX_SCRIPT", str(Path(__file__).with_name("agent_mailbox.py")))
FAKE_SHA = "3f9c2a7b1e4d5c6f8a9b0c1d2e3f4a5b6c7d8e9f"  # 40 hex digits, like a commit id or a Forgejo token


def start(*args: str, env: dict[str, str] | None = None) -> subprocess.Popen[bytes]:
    return subprocess.Popen([sys.executable, SCRIPT, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env)


def finish(proc: subprocess.Popen[bytes], body: str | bytes | None = None) -> tuple[int, dict[str, Any]]:
    data = body.encode("utf-8") if isinstance(body, str) else body
    stdout, stderr = proc.communicate(data, timeout=60)
    try:
        result = json.loads(stdout)
    except ValueError:
        raise AssertionError(f"not one JSON object: {stdout!r} stderr={stderr!r}") from None
    if not isinstance(result, dict):
        raise AssertionError(f"not one JSON object: {stdout!r}")
    return proc.returncode, result


class MailboxTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name) / "agent-mail"
        self.root.mkdir()
        for name, machine in (("green-claude", "GREEN"), ("rnbw-claude", "RNBW"), ("rnbw-codex", "RNBW")):
            code, result = self.run_cli("register", name, "--machine", machine, "--kind", name.split("-")[1])
            self.assertEqual((code, result["status"]), (0, "ok"), result)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, *args: str, body: str | bytes | None = None) -> tuple[int, dict[str, Any]]:
        return finish(start("--root", str(self.root), *args), body)

    def send(self, frm: str, to: str, body: str, *extra: str, subject: str = "hello") -> tuple[int, dict[str, Any]]:
        return self.run_cli("send", "--as", frm, "--to", to, "--subject", subject, *extra, body=body)

    def sent_ok(self, frm: str, to: str, body: str, *extra: str) -> str:
        code, result = self.send(frm, to, body, *extra)
        self.assertEqual((code, result["status"]), (0, "ok"), result)
        return str(result["id"])

    def inbox(self, who: str) -> tuple[int, dict[str, Any]]:
        return self.run_cli("inbox", "--as", who)

    def files(self, who: str) -> list[str]:
        return sorted(p.name for p in (self.root / "inbox" / who).iterdir())

    # ---- registration

    def test_register_is_idempotent_and_refuses_conflicts(self) -> None:
        code, result = self.run_cli("register", "green-claude", "--machine", "GREEN", "--kind", "claude")
        self.assertEqual((code, result["body"]), (0, "already registered"))
        code, result = self.run_cli("register", "green-claude", "--machine", "ELSEWHERE", "--kind", "claude")
        self.assertEqual((code, result["status"]), (4, "error"))
        code, result = self.run_cli("agents")
        self.assertEqual(sorted(a["name"] for a in result["agents"]), ["green-claude", "rnbw-claude", "rnbw-codex"])
        self.assertEqual({a["name"]: a["machine"] for a in result["agents"]}["green-claude"], "GREEN")

    def test_invalid_names_are_refused(self) -> None:
        for bad in ("Green", "a/b", "..", "-x", "x" * 41, "has space"):
            code, result = self.run_cli("register", "--machine", "M", "--kind", "k", "--", bad)
            self.assertEqual((code, result["status"]), (4, "error"), bad)

    def test_root_must_exist(self) -> None:
        code, result = finish(start("--root", str(self.root / "missing"), "agents"))
        self.assertEqual((code, result["status"]), (4, "error"))
        env = {k: v for k, v in os.environ.items() if k != "AGENT_MAILBOX_ROOT"}
        code, result = finish(start("agents", env=env))
        self.assertEqual((code, result["status"]), (4, "error"))
        code, result = finish(start("agents", env={**env, "AGENT_MAILBOX_ROOT": str(self.root)}))
        self.assertEqual((code, result["status"]), (0, "ok"))

    # ---- the normal round trip

    def test_send_inbox_read_receipt(self) -> None:
        mid = self.sent_ok("green-claude", "rnbw-claude", "Please review prjX#5", "--ref", "prjX#5")
        code, result = self.inbox("rnbw-claude")
        self.assertEqual((code, result["status"]), (0, "messages"))
        self.assertEqual([(m["id"], m["from"], m["ref"]) for m in result["unread"]], [(mid, "green-claude", "prjX#5")])
        code, result = self.run_cli("sent", "--as", "green-claude")
        self.assertEqual([(m["id"], m["read"]) for m in result["sent"]], [(mid, False)])

        code, result = self.run_cli("read", "--as", "rnbw-claude", mid)
        self.assertEqual((code, result["status"], result["body"]), (0, "message", "Please review prjX#5"))
        code, result = self.inbox("rnbw-claude")
        self.assertEqual((code, result["status"]), (2, "empty"))
        code, result = self.run_cli("sent", "--as", "green-claude")
        self.assertEqual([(m["id"], m["read"]) for m in result["sent"]], [(mid, True)])
        self.assertEqual(self.inbox("green-claude")[1]["status"], "empty")  # nothing came back

    def test_read_twice_keeps_the_first_receipt(self) -> None:
        mid = self.sent_ok("green-claude", "rnbw-claude", "x")
        self.run_cli("read", "--as", "rnbw-claude", mid)
        receipt = self.root / "inbox" / "rnbw-claude" / f"{mid}.read"
        first = receipt.read_text(encoding="utf-8")
        time.sleep(1.1)
        code, result = self.run_cli("read", "--as", "rnbw-claude", mid)
        self.assertEqual((code, result["status"]), (0, "message"))
        self.assertEqual(receipt.read_text(encoding="utf-8"), first)

    def test_messages_listed_oldest_first_and_never_overwritten(self) -> None:
        with ThreadPoolExecutor(max_workers=6) as pool:
            ids = list(pool.map(lambda i: self.sent_ok("green-claude", "rnbw-claude", f"msg {i}"), range(12)))
        self.assertEqual(len(set(ids)), 12)
        code, result = self.inbox("rnbw-claude")
        listed = [m["id"] for m in result["unread"]]
        self.assertEqual(sorted(listed), sorted(ids))
        self.assertEqual(listed, sorted(listed))
        bodies = {self.run_cli("read", "--as", "rnbw-claude", i)[1]["body"] for i in ids}
        self.assertEqual(bodies, {f"msg {i}" for i in range(12)})

    def test_bom_is_stripped(self) -> None:
        mid = self.sent_ok("green-claude", "rnbw-claude", "﻿hello")
        self.assertEqual(self.run_cli("read", "--as", "rnbw-claude", mid)[1]["body"], "hello")

    # ---- who may do what

    def test_recipient_and_sender_must_be_registered(self) -> None:
        code, result = self.send("green-claude", "nobody", "x")
        self.assertEqual((code, result["status"]), (4, "error"))
        code, result = self.send("nobody", "green-claude", "x")
        self.assertEqual((code, result["status"]), (4, "error"))
        self.assertEqual(self.files("green-claude"), [])

    def test_no_mail_to_yourself(self) -> None:
        code, result = self.send("green-claude", "green-claude", "x")
        self.assertEqual((code, result["status"]), (4, "error"))
        self.assertEqual(self.files("green-claude"), [])

    def test_empty_and_oversized_bodies_are_refused(self) -> None:
        self.assertEqual(self.send("green-claude", "rnbw-claude", "   \n")[0], 4)
        self.assertEqual(self.send("green-claude", "rnbw-claude", "x" * (256 * 1024 + 1))[0], 4)
        self.assertEqual(self.files("rnbw-claude"), [])

    def test_cannot_read_someone_elses_mail(self) -> None:
        mid = self.sent_ok("green-claude", "rnbw-claude", "for rnbw-claude only")
        code, result = self.run_cli("read", "--as", "rnbw-codex", mid)
        self.assertEqual((code, result["status"]), (4, "error"))
        self.assertNotIn(f"{mid}.read", self.files("rnbw-claude"))

    # ---- secrets

    def test_secrets_are_refused(self) -> None:
        samples = {
            "private key": "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaA==\n",
            "GitHub token": "use ghp_" + "a1B2c3D4" * 5,
            "fine-grained GitHub token": "github_pat_" + "11ABCDEFG0" * 6,
            "Anthropic key": "sk-ant-" + "abcDEF123_" * 3,
            "AWS key": "AKIA" + "ABCDEFGHIJKLMNOP",
            "auth header": "curl -H 'Authorization: token " + FAKE_SHA + "'",
            "URL password": "git clone https://stephenmm:hunter2pass@192.168.87.31:3000/x.git",
            "Forgejo token": "the token is " + FAKE_SHA,
            "Forgejo token, punctuated": "api_key: " + FAKE_SHA,
            "password": "password = correct-horse-battery",
        }
        for label, text in samples.items():
            code, result = self.send("green-claude", "rnbw-claude", f"look: {text}")
            self.assertEqual((code, result["status"]), (4, "error"), label)
            self.assertIn("secret", result["body"], label)
        code, result = self.send("green-claude", "rnbw-claude", "fine", subject="token " + FAKE_SHA)
        self.assertEqual(code, 4, "secret in the subject")
        self.assertEqual(self.files("rnbw-claude"), [])

    def test_commit_ids_and_secret_talk_are_allowed(self) -> None:
        for text in (f"Merged as {FAKE_SHA} on main.", "The token is in ~/.forgejo/stephenmm-claude.token",
                     "Rotate the password next week.", "See https://192.168.87.31:3000/stephenmm/prjX/pulls/5"):
            code, result = self.send("green-claude", "rnbw-claude", text)
            self.assertEqual((code, result["status"]), (0, "ok"), text)

    # ---- threads

    def test_reply_keeps_the_thread_and_close_shows(self) -> None:
        first = self.sent_ok("green-claude", "rnbw-claude", "Can you review prjX#5?", "--ref", "prjX#5")
        reply = self.sent_ok("rnbw-claude", "green-claude", "Approved.", "--reply-to", first)
        last = self.sent_ok("green-claude", "rnbw-claude", "Merged, thanks.", "--reply-to", reply, "--close")
        code, result = self.run_cli("thread", "--as", "rnbw-claude", first)
        self.assertEqual(code, 0)
        self.assertEqual([m["id"] for m in result["messages"]], [first, reply, last])
        self.assertEqual({m["thread"] for m in result["messages"]}, {first})
        self.assertEqual(result["messages"][1]["in_reply_to"], first)
        self.assertTrue(result["closed"])

    def test_reply_only_to_your_own_conversations(self) -> None:
        mid = self.sent_ok("green-claude", "rnbw-claude", "private")
        code, result = self.send("rnbw-codex", "green-claude", "butting in", "--reply-to", mid)
        self.assertEqual((code, result["status"]), (4, "error"))
        code, result = self.run_cli("thread", "--as", "rnbw-codex", mid)
        self.assertEqual((code, result["status"]), (4, "error"))

    # ---- damage and noise

    def test_junk_files_are_ignored(self) -> None:
        box = self.root / "inbox" / "rnbw-claude"
        (box / "notes.txt").write_text("hi", encoding="utf-8")
        (box / "m-bad.json").write_text("{}", encoding="utf-8")
        (box / ".m-20261104T000000Z-green-claude-abcdef.json.tmp").write_text("partial", encoding="utf-8")
        self.assertEqual(self.inbox("rnbw-claude")[1]["status"], "empty")

    def test_damaged_message_is_reported_not_fatal(self) -> None:
        good = self.sent_ok("green-claude", "rnbw-claude", "fine")
        box = self.root / "inbox" / "rnbw-claude"
        (box / "m-20200101T000000Z-green-claude-000000.json").write_text("{not json", encoding="utf-8")
        renamed = "m-20200101T000001Z-green-claude-000001"
        data = json.loads((box / f"{good}.json").read_text(encoding="utf-8"))
        (box / f"{renamed}.json").write_text(json.dumps(data), encoding="utf-8")  # id does not match its name
        code, result = self.inbox("rnbw-claude")
        self.assertEqual(code, 0)
        errors = {m["id"] for m in result["unread"] if "error" in m}
        self.assertEqual(errors, {"m-20200101T000000Z-green-claude-000000", renamed})
        self.assertIn(good, {m["id"] for m in result["unread"] if "error" not in m})
        code, result = self.run_cli("read", "--as", "rnbw-claude", renamed)
        self.assertEqual((code, result["status"]), (4, "error"))

    # ---- the owner's kill switch and waiting

    def test_stop_closes_every_command(self) -> None:
        mid = self.sent_ok("green-claude", "rnbw-claude", "before stop")
        self.assertEqual(self.run_cli("stop")[0], 0)
        for args in (("inbox", "--as", "rnbw-claude"), ("read", "--as", "rnbw-claude", mid), ("agents",),
                     ("sent", "--as", "green-claude"), ("wait", "--as", "rnbw-claude", "--block-seconds", "0")):
            code, result = self.run_cli(*args)
            self.assertEqual((code, result["status"], result.get("by")), (3, "closed", "owner"), args)
        code, result = self.send("green-claude", "rnbw-claude", "after stop")
        self.assertEqual(code, 3)
        self.assertEqual([f for f in self.files("rnbw-claude") if f.endswith(".json")], [f"{mid}.json"])

    def test_wait_wakes_on_mail_and_on_stop(self) -> None:
        code, result = self.run_cli("wait", "--as", "rnbw-claude", "--block-seconds", "0")
        self.assertEqual((code, result["status"]), (2, "waiting"))
        waiter = start("--root", str(self.root), "wait", "--as", "rnbw-claude", "--block-seconds", "60")
        time.sleep(2)
        mid = self.sent_ok("green-claude", "rnbw-claude", "wake up")
        code, result = finish(waiter)
        self.assertEqual((code, result["status"]), (0, "messages"))
        self.assertEqual([m["id"] for m in result["unread"]], [mid])

        self.run_cli("read", "--as", "rnbw-claude", mid)
        waiter = start("--root", str(self.root), "wait", "--as", "rnbw-claude", "--block-seconds", "60")
        time.sleep(2)
        self.run_cli("stop")
        began = time.time()
        code, result = finish(waiter)
        self.assertEqual((code, result["status"]), (3, "closed"))
        self.assertLess(time.time() - began, 15)


if __name__ == "__main__":
    unittest.main()
