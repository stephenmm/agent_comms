"""Prove the tests can go red: remove one guard at a time from agent_channel_lvl0.py and expect a failure.

Run:  python mutation_check.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
SOURCE = (HERE / "agent_channel_lvl0.py").read_text(encoding="utf-8")

# guard removed -> (text in the script, replacement)
MUTANTS: dict[str, tuple[str, str]] = {
    "turn order": ("if author(n) != role:", "if False:"),
    "send after end": ('if last_header.get("end", False):', "if False:"),
    "abort file closes channel": ("if abort_file(d, r).exists():", "if False:"),
    "timeout": ("if time.time() - waiting_since > max_wait * 60:", "if False:"),
    "sequence check": ("if found != {name(k) for k in range(n)}:", "if False:"),
    "message shape": ('if set(data) != {"header", "body"} or not isinstance(header, dict) or not isinstance(body, str):',
                      "if False:"),
    "end must be boolean": ('if not isinstance(header.get("end", False), bool):', "if False:"),
    "exclusive write": ('with open(tmp, "x", encoding="utf-8") as f:', 'with open(tmp, "w", encoding="utf-8") as f:'),
    "filename filter": ("if MSG.fullmatch(p.name)}", 'if p.name.startswith("ch-")}'),
    "empty body": ("if not body and not args.end:", "if False:"),
    "selftest silence": ("time.sleep(args.seconds)", "pass"),
    "empty-channel timeout": ("if n else d.stat().st_mtime", "if n else started"),
    "recv waits for the peer": ("if n and author(n - 1) != role:", "if n:"),
    "owner kill switch": ("if (d / STOP).exists():", "if False:"),
    "spawn passes the start prompt": ('prompt_file.write_text(prompt, encoding="utf-8")',
                                      'prompt_file.write_text("x" * 200, encoding="utf-8")'),
    "spawn validates the template": ('if not template or "{prompt_file}" not in template:', "if False:"),
    "spawn feeds the prompt on stdin": ('proc.stdin.write(prompt.encode("utf-8"))', "pass"),
    "spawn validates before creating": ("    cmd, use_shell = launcher(args.via, args.command, d, prompt_file)  # validate before anything is created\n    d, prompt = create_channel(args.parent, args.session)\n",
                                        "    d, prompt = create_channel(args.parent, args.session)\n    cmd, use_shell = launcher(args.via, args.command, d, prompt_file)\n"),
    "spawn feeds the prompt intact": ('proc.stdin.write(prompt.encode("utf-8"))',
                                      'proc.stdin.write(prompt.replace("selftest", "XXXXXXXX").encode("utf-8"))'),
    "spawn handles failures after message 0": ("    except OSError as exc:\n        if proc is not None:",
                                               "    except FileExistsError as exc:\n        if proc is not None:"),
    "spawn stops a child that got no prompt": ("kill_tree(proc)  # started", "pass  # started"),
    "send reads the body before the channel state": (
        "    body = read_body(args.body_file)  # first: stdin may block for a long time, and the channel can close meanwhile\n"
        "    n, last_header, last_body = state(d, role)\n",
        "    n, last_header, last_body = state(d, role)\n    body = read_body(args.body_file)\n"),
    "codex_exe skips the sandbox copy": ("if Path(found).resolve() != SANDBOX_CODEX.resolve():", "if True:"),
    "selftest prints nothing early": ("time.sleep(args.seconds)", 'print("early", flush=True); time.sleep(args.seconds)'),
    "init reports an existing channel as JSON": ("    except OSError as exc:  # FileExistsError included",
                                                 "    except PermissionError as exc:  # FileExistsError included"),
    "unreadable body is a JSON error": ("    except OSError as exc:\n        out(\"error\", ERROR, body=f\"cannot read the body",
                                        "    except PermissionError as exc:\n        out(\"error\", ERROR, body=f\"cannot read the body"),
    "recv closes on an unreadable first message": ("            except ValueError as exc:\n                close(d, role",
                                                   "            except KeyError as exc:\n                close(d, role"),
    "BOM stripped from body": ('return raw.decode("utf-8-sig").strip()', 'return raw.decode("utf-8").strip()'),
}


def tests_pass(script: Path) -> bool:
    env = {**os.environ, "AGENT_CHANNEL_SCRIPT": str(script)}
    proc = subprocess.run([sys.executable, "-m", "unittest", "test_agent_channel_lvl0"],
                          cwd=HERE, env=env, capture_output=True)
    return proc.returncode == 0


def check(guard: str, tmp: str) -> bool:
    """True if removing this guard turns the test suite red."""
    old, new = MUTANTS[guard]
    if SOURCE.count(old) != 1:
        print(f"STALE     {guard}: pattern found {SOURCE.count(old)} times")
        return False
    folder = Path(tmp) / str(list(MUTANTS).index(guard))
    folder.mkdir()
    mutant = folder / "agent_channel_lvl0.py"
    mutant.write_text(SOURCE.replace(old, new), encoding="utf-8")
    caught = not tests_pass(mutant)
    print(f"{'caught  ' if caught else 'SURVIVED'}  {guard}")
    return caught


def main() -> int:
    if not tests_pass(HERE / "agent_channel_lvl0.py"):
        print("the unmodified script fails its tests; fix that first")
        return 1
    with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(max_workers=4) as pool:
        caught = sum(pool.map(lambda guard: check(guard, tmp), MUTANTS))
    print(f"{caught}/{len(MUTANTS)} guards are covered by a test that goes red")
    return 0 if caught == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
