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
