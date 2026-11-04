# Mailbox trial 1: Windows ↔ WSL on GREEN (2026-11-04)

**Setup.** Mailbox root `agent-mail/` in this folder.
- **`green-claude`:** this Claude Code session, on Windows, Python 3.12.
- **`wsl-claude`:** a Sonnet subagent on GREEN's WSL Ubuntu, Python 3.10.12. It was briefed only to read the
  script's docstring and use the mailbox, and it ran every command through `wsl.exe` with the `/mnt/e/...` root.
- **No human relay:** nobody passed messages between them. green-claude registered both names before starting,
  and wsl-claude's own `register` correctly answered "already registered".

**Thread** `m-20261104T231210Z-green-claude-c81398`, all in `agent-mail/inbox/`:
1. **Round 1:** green-claude asked for two facts from the WSL side. wsl-claude replied `362fb10` (`main`'s
   head, matching what Windows sees) and `Python 3.10.12`. It used `wait` to pick up the next message.
2. **First try at round 2, refused:** green-claude's first attempt quoted the made-up test value
   ("the token is " + 40 hex digits). The guard refused it before anything was written, exit 4.
3. **Round 2:** green-claude asked wsl-claude to send "the token is " followed by 40 letters `a`. wsl-claude's
   send was refused (`token next to a secret word`, exit 4, nothing delivered). It reported the refusal in a
   normal reply.
4. **Close:** green-claude confirmed and sent `--close`. wsl-claude read the closing message, saw
   `"close": true` and stopped. A final `inbox` returned `empty`, exit 2.

**Result:** pass. Two rounds and a close, with a read receipt for every message. The secret guard fired on both
sides, and every result was one JSON line.

**Feedback from wsl-claude, now fixed in the docstring:**
- **Refusals:** "error" also covers a guard refusal, not only misuse.
- **`--close` vs `stop`:** `--close` only ends a thread; only `stop` makes commands return "closed".
- **The WSL root form:** `/mnt/e/agent-mail` belongs in the list of roots.

**Not covered:** across machines over the SMB share (MB3), and a Codex peer.
