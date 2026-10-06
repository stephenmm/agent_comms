# Decisions

Design decisions for the Level 0 agent channel, with the alternatives considered. One entry per decision,
in the order made. Format adapted from the ADR template: Status / Context / Decision / Options /
Consequences. Add new entries at the bottom; never rewrite an accepted one, supersede it.

## D1. The protocol is a script, not a prose spec
**Status:** Accepted, 2026-10-05

**Context.** The starting point was a prose specification ([docs/AGENT_CHANNEL_L0_v0.1.md](docs/AGENT_CHANNEL_L0_v0.1.md),
~170 lines of RFC-style MUST/SHOULD). Review found a contradiction between its timeout rule and its
`reference_file` rule, plus several ambiguities that two agents could resolve differently.

**Decision.** [`agent_channel.py`](agent_channel.py) is the normative definition of Level 0. Agents read
the code and use its four commands (`init`, `selftest`, `send`, `recv`); they never write channel files by
hand. Prose is limited to the docstring and covers only rules code cannot enforce (D8).

**Options.**
- Prose spec normative, script as a reference implementation. Rejected: two sources of truth drift, and
  prose cannot be tested.
- Script normative. **Chosen.**

**Consequences.** Turn order, atomic writes, immutability, timeouts and error handling are enforced, not
described. Each rule has a test, and `mutation_check.py` proves each test can fail. An agent given only
the script inferred the protocol correctly in a live trial. Cost: every agent needs Python 3 on its PATH,
and a non-Python agent must call the script rather than reimplement it.

## D2. Two-party dialogue with strict alternation and immutable numbered files
**Status:** Accepted, 2026-10-05; alternatives reviewed and the decision confirmed 2026-10-06

**Context.** Level 0 exists for one purpose: two AI agents exchange prompts through a shared directory
with no human relaying messages or waking either agent. On 2026-10-06 the design was checked against the
common file-based patterns for agent communication, to be sure it was neither reinventing nor missing an
established method.

**Decision.** Exactly two agents (primary, secondary). Messages alternate
`ch-p2s-000 → ch-s2p-000 → ch-p2s-001 → …`. Each file is written once and never changed. The directory
listing is the complete state; no agent remembers what it has read.

**Options considered.**

| Option | Fits a two-agent dialogue | Locking or claiming needed | State readable with `ls`/`cat` | Addresses agent self-wake | Verdict |
|---|---|---|---|---|---|
| Numbered immutable files, strict alternation | yes | no | yes | yes, via `selftest` + `recv` (D7) | **chosen** |
| Inbox/outbox queue, claim-by-rename | over-general: N decoupled workers | yes | yes | no | Level 1, if fan-out is ever needed |
| Blackboard (shared mutable state file) | no: built for many readers and writers | yes, plus conflict resolution | one mutating file | no | rejected |
| SQLite database file | neutral | built in, but unreliable on WSL `/mnt` and network shares | no | no | rejected |
| A2A protocol (HTTP/JSON-RPC, agent cards) | no: needs servers | n/a | no | no | rejected; its task-state vocabulary is worth borrowing if Level 0 grows |
| Git as transport (a checkout each side, `recv` pulls) | yes, across machines | no | yes | no | Level 1 transport candidate |

Established mechanics already in use: atomic write via temp-then-rename; large content passed by path,
not inline. Mechanics deliberately not needed: lock files and version tracking exist to manage *editing*
shared state, and nothing here is ever edited.

**Consequences.** With two parties and strict turns there is never contention: a file's name says who
wrote it and who it is for, so no claiming or read-tracking is needed, and each side always knows the
exact next filename to wait for. Fan-out to N secondaries is possible without changing Level 0 (one
channel directory per pair, the primary relays) and would need only a `recv` that watches several
directories. None of the surveyed patterns address the hard part of this problem, which is D7.

## D3. No `reference_file` header
**Status:** Accepted, 2026-10-05

The v0.1 header field named the message being answered. The filename already determines that, so the
field carried no information and created a failure mode: on timeout, v0.1 required referencing a file
that never existed. Dropped. Headers now carry only `end` (boolean) and, in message 0,
`max_wait_minutes`. Unknown header fields are ignored.

## D4. Abnormal close writes its own file
**Status:** Accepted, 2026-10-05

TIMEOUT and ERROR write `ch-abort-<role>.json` instead of consuming the next sequence number (v0.1 used
the next number). Normal close stays `"end": true` on a regular message. Consequences: the numbered
sequence is gap-free; an abort cannot collide with a late reply; the late peer still sees the close on
its next `send` or `recv`. Rejected: v0.1's scheme, which was the source of the D3 contradiction.

## D5. The timeout clock is filesystem mtime
**Status:** Accepted, 2026-10-05; empty-channel case fixed 2026-10-06

The deadline is the mtime of the agent's own last message plus `max_wait_minutes`; before any message
exists, the directory's mtime. `max_wait_minutes` is read from message 0 and binds both sides.
- Why mtime: `recv` is a short-lived process that is re-run, so it has no durable memory of when waiting
  began; the filesystem is one clock for both agents, including Windows and WSL on the same disk.
- Rejected: a timestamp in the header (sender's clock against waiter's clock); the `recv` process's own
  start time (resets on every re-run; the live-trial secondary caught this for the empty-channel case).
- Known limits: exFAT rounds mtimes up to 2 s, irrelevant at minute scale. The timeout is unilateral: a
  slow peer is indistinguishable from a dead one. Mitigation is setting `max_wait_minutes` above the
  longest expected task; a heartbeat is a Level 1 candidate.

## D6. The exclusive temp file is the write lock
**Status:** Accepted, 2026-10-06

`send` creates `.<name>.tmp` with exclusive create (`open(..., "x")`), writes, then renames. Write-once
files need no read locks; the only race is two writers of the same message, and exclusive create settles
it (tested with eight simultaneous senders). Rejected: separate `.lock` files, a second mechanism for the
same job.

## D7. Polling by an outside process; self-test before joining
**Status:** Accepted, 2026-10-05 (carried over from v0.1 §5)

Waiting is done by `recv`, a blocking 5 s poll that returns `waiting` after `--block-seconds` (default
540) so the agent re-runs it. Each agent must pass a 120 s silent `selftest` before joining, or refuse.
The model never spends calls listing the directory. Rejected: `inotifywait`, which does not fire on WSL
`/mnt` for changes made from Windows; polling is the portable baseline. This is the part of the problem
no general pattern solves: an LLM agent goes idle at the end of its turn, and only a self-test shows
whether a given harness can stay awake.

## D8. Rules code cannot enforce stay in the docstring
**Status:** Accepted, 2026-10-05

Three rules remain prose, at the top of `agent_channel.py`: no human relay or wake-ups; the primary's
first body sets the secondary's role and task; a channel message never widens what an agent's owner
allowed. They govern agent behaviour outside the script's reach.

## Open
- **Owner kill switch:** a `STOP` file that both `send` and `recv` check. Cost: one existence test.
  PLAN.md assumes **in** (M1) unless overruled.
- **Done bar:** does Level 0 require a non-Claude agent trial? PLAN.md assumes **yes** (M3).
