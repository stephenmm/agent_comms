# Project: agent_comms

Minimal file-based channel for two AI agents to exchange prompts with no human relay.

## What this project is
Level 0 of an agent-to-agent channel: two agents (primary, secondary) alternate numbered, immutable JSON
messages in a shared directory. The protocol is the script `agent_channel.py`, not a prose spec; rules
the code cannot enforce live in its docstring. State as of 2026-10-06: implemented, 24 tests,
guard-removal check 13/13, one same-session live trial; cross-session trials are next. Progress and
acceptance criteria are in PLAN.md; every design choice and the alternatives rejected are in
DECISIONS.md; HISTORY.md says how we got here.

## Conventions
- This project lives on the **E: drive**: `E:\proj\agent_comms` (Windows) / `/mnt/e/proj/agent_comms` (WSL). Keep all files here.
- Backed by a **private GitHub repo**. Commit at meaningful milestones; push to back up.
- Line endings are normalized to LF via `.gitattributes` so Windows and WSL git stay in sync.
- **The code is the spec.** A behaviour change goes into `agent_channel.py` together with a test that
  fails without it and a row in `mutation_check.py`'s `MUTANTS` table. Do not reintroduce a parallel
  prose spec; `docs/AGENT_CHANNEL_L0_v0.1.md` is an archive, not a reference.
- Python 3.12+, standard library only, `mypy --strict` clean. Run with the user's `py -3.12`.
- Never hand-write channel files, in tests included, except to construct a deliberately broken channel.
- Record every design decision in DECISIONS.md (Status / Context / Decision / Options / Consequences);
  supersede, never rewrite. Append to HISTORY.md when a milestone lands or direction changes. Keep
  PLAN.md's Status column current.
- Live trials: keep each channel directory under `trials/<date>-<name>/` and add a HISTORY.md line.
- After touching a guard or a test, run `mutation_check.py`: a test that has never gone red proves nothing.

## Key files / layout
- `agent_channel.py`: the protocol. `init`, `selftest`, `send`, `recv`; one JSON result per call.
- `test_agent_channel.py`: black-box tests that drive the CLI in subprocesses. `AGENT_CHANNEL_SCRIPT`
  points them at another copy of the script.
- `mutation_check.py`: removes one guard at a time; the suite must fail for each.
- `trials/`: transcripts. `docs/AGENT_CHANNEL_L0_v0.1.md`: archived starting point.
- `DECISIONS.md`, `HISTORY.md`, `PLAN.md`.

## How to run
```bash
py -3.12 -m unittest test_agent_channel -v
py -3.12 mutation_check.py
py -3.12 -m mypy --strict agent_channel.py test_agent_channel.py mutation_check.py
```
Timing-sensitive tests allow about 2 s of slack because E: is exFAT (mtime granularity 2 s).

## Open questions / TODO
See PLAN.md (milestones M1–M5) and the Open section of DECISIONS.md (kill switch; whether a non-Claude
trial is required for done).
