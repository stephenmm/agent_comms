# History

How this project got here, oldest first. Append an entry when a milestone lands or direction changes.

## 2026-10-05 — Starting point: a prose spec
Stephen brought `AGENT_CHANNEL_L0.md` v0.1 (archived at [docs/AGENT_CHANNEL_L0_v0.1.md](docs/AGENT_CHANNEL_L0_v0.1.md)):
a Level 0 specification for two AI agents exchanging prompts through a shared directory with no human
relaying messages. Strict alternation of numbered JSON files, write-then-rename, a self-wake self-test,
timeout and error handling, start-prompt templates.

Review (Claude Code, Opus 5.5) judged the design workable and found one contradiction: on timeout an agent
writes its next message, but §4 required that message's `reference_file` to name a file that never
existed. Also flagged: no defined timeout clock; Windows and WSL see different absolute paths;
`inotifywait` does not fire on WSL `/mnt`; the self-test wording was ambiguous for Claude Code's
background jobs; permission prompts could break "no human needed"; no rule that a channel message carries
none of the owner's authority.

## 2026-10-05 — Decision: the protocol is code
Stephen: "create a very small python script that imposes these rules rather than enumerating them in
inefficient english language", so that agents infer the protocol from the script
([DECISIONS.md](DECISIONS.md) D1).

`agent_channel.py` written: four commands (`init`, `selftest`, `send`, `recv`), one JSON result per call,
about 200 lines, standard library only, `mypy --strict` clean. Two departures from v0.1: `reference_file`
dropped (D3); TIMEOUT and ERROR write an abort file instead of consuming a sequence number (D4).
Smoke-tested from one shell playing both roles.

## 2026-10-05/06 — Testing
- `test_agent_channel.py`: 24 black-box tests that drive the real CLI in subprocesses.
- `mutation_check.py`: removes one guard at a time and expects the suite to go red. First run 11/13; the
  sequence check and the exclusive write had no test that could fail, so tests were added. Now 13/13.
- Found on the way: E: is exFAT and rounds file mtimes up to 2 s (timing margins widened); a
  concurrent-writer race, fixed by creating the temp file exclusively (D6).

## 2026-10-05/06 — Live trial 1, same session
Primary: the Claude Code session doing the work. Secondary: a Sonnet subagent given only the start prompt
that `init` prints. Both passed the 120 s self-test; two rounds; clean close; no human relay. Transcript:
[trials/2026-10-05-trial1-same-session/](trials/2026-10-05-trial1-same-session/).

The secondary's review, folded in: the empty-channel timeout clock reset on every `recv` re-run (fixed,
D5); the docstring now warns that tool time limits must exceed 120 s and `--block-seconds`; and it states
that the primary sends before the secondary is started, so the secondary's first `recv` returns at once.

## 2026-10-06 — Direction check against common patterns
Stephen asked whether a survey of file-based agent communication (blackboard, inbox/outbox queues, lock
files, SQLite, A2A, git) should change direction. Conclusion: no. Those patterns cover mechanics already
in use or deliberately avoided, and none address the hard part, keeping an LLM agent awake without a
human. Recorded as D2.

## 2026-10-06 — Project created
Repo `agent_comms` scaffolded on E: with its private GitHub repo. Code, tests, trial transcript, the
archived v0.1 spec, DECISIONS.md, PLAN.md and this file committed. Milestone M0 of
[PLAN.md](PLAN.md) done.

## 2026-10-06 — Kill switch (D9) and trials 2 and 3, run in parallel
- `stop <dir>` added: writes `STOP`; a blocked `recv` closes within one poll (26 tests, 14 mutants).
  Recorded as D9, awaiting Stephen's confirmation.
- **Trial 2, `waiting` re-run** ([trials/2026-10-06-trial2-waiting-rerun/](trials/2026-10-06-trial2-waiting-rerun/)):
  a Sonnet subagent as primary ran `recv --block-seconds 60` against a peer process that slept 200 s.
  Three `waiting` results, message picked up on the fourth run, no human input. Finding: a body piped
  from PowerShell 5.1 carries a UTF-8 BOM that `.strip()` leaves in place.
- **Trial 3, Windows ↔ WSL** ([trials/2026-10-06-trial3-windows-wsl/](trials/2026-10-06-trial3-windows-wsl/)):
  Windows primary (this session), secondary run inside WSL via `wsl.exe` by a Sonnet subagent. Self-test
  passed in WSL; paths translated to `/mnt/e/...` as the start prompt says; one round and a clean close.
  Findings: WSL has `python3` but no `python`, so the start prompt's bare `python` is not portable; the
  BOM again, this time from the Windows primary's own PowerShell `send`. M4 done.
- Both findings fixed: `send` decodes bodies as `utf-8-sig` (test and mutant added, 27 tests, 15
  mutants); the secondary start prompt now says to run with `python` or `python3`, whichever exists.

## 2026-10-06 — Trial 4, cross-session Claude ↔ Claude (M2)
Primary: this session. Secondary: a second Claude Code session that Stephen started with one paste of the
printed start prompt; it opened in a scratch workspace and moved itself to the project. Self-test passed;
three rounds; clean close; the secondary reports it never ended its turn or needed its owner between
messages, and saw no permission prompt for the channel commands (foreground Bash, explicit tool
timeouts). Transcript: [trials/2026-10-06-trial4-cross-session/](trials/2026-10-06-trial4-cross-session/).
Taken from its replies: the docstring now shows `--block-seconds 45` as a concrete way to fit a short tool
limit, and the Copilot (M3) start prompt uses it. M2 done; the Level 0 "done" bar now needs only M3.

## 2026-10-06 — Trial 5, Claude ↔ Codex (M3, non-Claude agent)
Primary: this session. Secondary: OpenAI Codex in the Codex desktop app, which Stephen pasted the start
prompt into (the plan named Copilot; the bar is "a non-Claude agent", and Codex meets it). Self-test
passed: Codex kept the 120 s process in a command session and polled it within one turn. Three rounds,
clean close, no owner prompt between messages. Transcript:
[trials/2026-10-06-trial5-codex/](trials/2026-10-06-trial5-codex/). Findings:
- The pasted path reached Codex as `E:\proj\agent\_comms\agent\_channel.py`: underscores had been
  backslash-escaped somewhere between this session's output and Codex's input (a markdown artifact).
  Codex recovered by searching `E:\proj`. Lesson: paste start prompts from a code block, and prefer
  hyphens over underscores in channel and project names.
- Writing into the channel needed a sandbox escalation on the Codex side, because the directory is
  outside its writable roots; its automatic review allowed it. A stricter sandbox would have stalled the
  trial, which is the "permission prompts" risk in PLAN.md showing up on a non-Claude agent.
- `recv --block-seconds 45` never returned `waiting` because the primary replied within each block.
M3 done. Copilot in VS Code remains untested.

## 2026-10-06 — Release v1.0.0 (M5)
Stephen confirmed D9 (kill switch stays) and chose three-part tags with the level in the script name (D10).
`agent_channel.py` renamed to `agent_channel_lvl0.py`, tests to `test_agent_channel_lvl0.py`; all live
references updated, historical ones left as written. Suite, `mypy --strict` and the guard-removal check
re-run after the rename. Tagged `v1.0.0`. Level 0 is complete: every milestone in PLAN.md done, five live
trials, no human relaying a message in any of them.

## 2026-10-06 — `spawn` added to Level 0 (D11); trial 6 attempts
Stephen asked whether a Codex session could be started remotely, then decided spawning belongs in Level 0,
with Level 1 reserved for a measured initialization stage. `spawn <parent> --via codex|claude|command`
added with a test that launches a fake secondary through `--via command` and two mutants (29 tests,
17/17 guards). Live trial 6, four attempts, none yet complete:
1. Codex: `--sandbox` and `--approve-for-me` are mutually exclusive in `codex exec`. Flag removed.
2. Codex: the desktop app's bundled `codex.exe` routes its shell tool through `codex-code-mode-host.exe`,
   which is not shipped; every command fails closed. Codex reported the block and exited.
3. Codex with `--disable code_mode_host`: the router still refuses ("code-mode host is disabled").
   Conclusion: headless Codex here needs the public CLI, not the app's bundled copy.
4. Claude CLI (`claude -p`, Bash limited to Python, project dir readable): "OAuth session expired and could
   not be refreshed". Needs one interactive `claude` login, then the trial is unchanged.
In all four the spawn mechanics worked: process launched detached, prompt delivered, log captured.
5. Codex, fifth attempt, success: the app keeps a complete CLI (binary plus `codex-code-mode-host.exe`) under
   `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\`; `codex_exe()` now prefers it. The primary spawned Codex with
   no human step; Codex passed the 120 s self-test in `workspace-write` with approvals `never`, completed two
   rounds and saw the close. Transcript and the secondary's own log:
   [trials/2026-10-06-trial6-spawn-codex/](trials/2026-10-06-trial6-spawn-codex/). M6 done; tagged `v1.1.0`.
   Still untested live: `--via claude` (needs an interactive `claude` login first).
