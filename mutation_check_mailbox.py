"""Prove the tests can go red: remove one guard at a time from agent_mailbox.py and expect a failure.

Run:  python mutation_check_mailbox.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
SOURCE = (HERE / "agent_mailbox.py").read_text(encoding="utf-8")

# guard removed -> (text in the script, replacement)
MUTANTS: dict[str, tuple[str, str]] = {
    "owner kill switch": ("if (self.root / STOP).exists():", "if False:"),
    "kill switch while waiting": ("        if (box.root / STOP).exists():", "        if False:"),
    "recipient must be registered": ("if not NAME.fullmatch(args.to) or not box.registered(args.to):", "if False:"),
    "sender must be registered": ("if not self.registered(name):", "if False:"),
    "no mail to yourself": ("if args.to == me:", "if False:"),
    "empty body": ("    if not body:\n", "    if False:\n"),
    "size limit": ("if len(raw) > MAX_BODY_BYTES:", "if False:"),
    "BOM stripped": ('raw.decode("utf-8-sig").strip()  # utf-8-sig', 'raw.decode("utf-8").strip()  # utf-8-sig'),
    "secret scan": ("        if kind:\n", "        if False:\n"),
    "GitHub token pattern": ('r"\\b(?:gh[pousr]_', 'r"\\bNEVER(?:gh[pousr]_'),
    "hex token needs a secret word": (r'(?:token|secret|password|passwd|api[_ -]?key)[^\n]{0,30}?\b[0-9a-f]{32,}\b',
                                      r'(?:)[0-9a-f]{32,}\b'),
    "read leaves a receipt": ('write_once(box.receipt(me, args.id), {"read_by": me, "read_at": now().isoformat()})',
                              "None"),
    "inbox hides read mail": ("if box.receipt(me, mid).exists():", "if False:"),
    "write-once": ("    if path.exists():\n        tmp.unlink()", "    if False:\n        tmp.unlink()"),
    "message filename filter": ('if p.suffix == ".json" and MSG.fullmatch(p.stem)]', 'if p.suffix == ".json"]'),
    "id matches the file name": ('if header.get("id") != path.stem:', "if False:"),
    "read only your own inbox": ('path = box.inbox_dir(me) / f"{args.id}.json"',
                                 'path = (box.find(args.id) or (me, box.inbox_dir(me) / f"{args.id}.json"))[1]'),
    "reply only in your conversations": ('if me not in (parent.get("from"), parent.get("to")):', "if False:"),
    "reply keeps the thread": ('"thread": thread or mid,', '"thread": mid,'),
    "thread only for participants": ('if h.get("thread") == args.thread and me in (h.get("from"), h.get("to")):',
                                     'if h.get("thread") == args.thread:'),
    "registration conflict": ('if (existing.get("machine"), existing.get("kind")) != (args.machine, args.kind):',
                              "if False:"),
    "name validation": ('NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?")', 'NAME = re.compile(r".+")'),
}


def tests_pass(script: Path) -> bool:
    env = {**os.environ, "AGENT_MAILBOX_SCRIPT": str(script)}
    proc = subprocess.run([sys.executable, "-m", "unittest", "test_agent_mailbox"],
                          cwd=HERE, env=env, capture_output=True)
    return proc.returncode == 0


def check(guard: str, tmp: str) -> bool:
    """True if removing this guard turns the test suite red."""
    old, new = MUTANTS[guard]
    if SOURCE.count(old) != 1:
        print(f"STALE     {guard}: pattern found {SOURCE.count(old)} times", flush=True)
        return False
    folder = Path(tmp) / str(list(MUTANTS).index(guard))
    folder.mkdir()
    mutant = folder / "agent_mailbox.py"
    mutant.write_text(SOURCE.replace(old, new), encoding="utf-8")
    caught = not tests_pass(mutant)
    print(f"{'caught  ' if caught else 'SURVIVED'}  {guard}", flush=True)
    return caught


def main() -> int:
    stale = [g for g, (old, _) in MUTANTS.items() if SOURCE.count(old) != 1]
    if stale:
        print(f"stale patterns, fix the table first: {stale}")
        return 1
    if not tests_pass(HERE / "agent_mailbox.py"):
        print("the unmodified script fails its tests; fix that first")
        return 1
    with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(max_workers=6) as pool:
        caught = sum(pool.map(lambda guard: check(guard, tmp), MUTANTS))
    print(f"{caught}/{len(MUTANTS)} guards are covered by a test that goes red")
    return 0 if caught == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
