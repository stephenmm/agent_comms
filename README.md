# agent_comms

Minimal file-based channel for two AI agents to exchange prompts with no human relay.

The protocol **is** [`agent_channel_lvl0.py`](agent_channel_lvl0.py): an agent reads the script and uses its four
commands, and never writes channel files by hand. Why code rather than a prose spec:
[DECISIONS.md](DECISIONS.md) D1.

## Status
Level 0 complete, tagged `v1.1.2`: five live trials passed (same-session, `waiting` re-run,
Windows↔WSL, cross-session Claude↔Claude, Claude↔Codex, and a Codex secondary spawned by the primary with no paste at
all), each with no human relaying messages.
Milestones and the definition of done are in [PLAN.md](PLAN.md); each trial's transcript is under
[`trials/`](trials/).

## How a channel runs
1. The **primary** agent creates the channel and sends the first message, whose body gives the secondary
   its role and task:
   ```bash
   python agent_channel_lvl0.py init <parent-dir>           # prints the channel path and the secondary's start prompt
   python agent_channel_lvl0.py selftest                    # 120 s of silence; pass = the agent woke on its own
   echo "Your role is ... Your task is ..." | python agent_channel_lvl0.py send <channel-dir> primary
   python agent_channel_lvl0.py recv <channel-dir> primary  # blocks until the reply arrives
   ```
2. The owner pastes the printed start prompt into the **secondary** agent. That paste is the only human
   step.
3. Both agents alternate `recv` → act → `send` until one sends `--end`.
   Alternatively `spawn <parent-dir> --via codex|claude|command` does steps 1–2 itself and launches the
   secondary headlessly (see the docstring); then the primary just runs `recv`.
4. The owner can halt both agents at any time with `python agent_channel_lvl0.py stop <channel-dir>`; each
   sees `closed` on its next command, a blocked `recv` within 5 s.

Every command prints one JSON object with a `status` of `message`, `waiting`, `closed` or `error`
(exit codes 0, 2, 3, 4).

## Tests
```bash
py -3.12 -m unittest test_agent_channel_lvl0 -v   # 38 tests (black-box, plus in-process injected failures), about 1.5 min
py -3.12 mutation_check.py                   # removes each guard in turn; every one must turn the suite red (about 15 min)
py -3.12 -m mypy --strict agent_channel_lvl0.py test_agent_channel_lvl0.py mutation_check.py
```

## Mailbox: asynchronous mail between machines
[`agent_mailbox.py`](agent_mailbox.py) is the second protocol ([DECISIONS.md](DECISIONS.md) D13). It's for agents
whose sessions don't overlap, such as Claude and Codex on GREEN and on RNBWMSIAMD9900X working on the same
Forgejo issues. Unlike Level 0, it needs no live peer and no paste.

Each agent registers once and then works with its own inbox:
```bash
export AGENT_MAILBOX_ROOT=/mnt/e/agent-mail          # GREEN: E:\agent-mail; other machines: the share, e.g. \\192.168.87.31\E\agent-mail
python agent_mailbox.py register green-claude --machine GREEN --kind claude
python agent_mailbox.py inbox --as green-claude      # at the start and end of every session
python agent_mailbox.py read --as green-claude <id>
echo "Approved prjX#5; merge when ready." | python agent_mailbox.py send --as green-claude --to rnbw-codex \
    --subject "prjX#5 review" --ref prjX#5 --reply-to <id>
python agent_mailbox.py wait --as green-claude --block-seconds 300   # for live back-and-forth
```
- **No secrets:** `send` refuses text that looks like a token, password or private key.
- **Your kill switch:** `python agent_mailbox.py stop` makes every command return `closed` until you delete
  `<root>/STOP`.
- **Instructions for each agent:** [`docs/MAILBOX_START.md`](docs/MAILBOX_START.md) has the lines to add to each
  machine's agent instructions, and the one-time setup for a new machine.

## Layout
| Path | What |
|---|---|
| `agent_channel_lvl0.py` | the protocol |
| `test_agent_channel_lvl0.py`, `mutation_check.py` | tests and the guard-removal check |
| `agent_mailbox.py` | the asynchronous mailbox (D13) |
| `test_agent_mailbox.py`, `mutation_check_mailbox.py` | its tests and guard-removal check |
| `trials/` | transcripts of live agent-to-agent trials, one directory each |
| `docs/AGENT_CHANNEL_L0_v0.1.md` | the original prose spec, archived |
| `DECISIONS.md`, `HISTORY.md`, `PLAN.md` | why, how we got here, what is left |

Releases are tagged `vMAJOR.MINOR.PATCH`; the protocol level is in the script name, so Level 1 would be a
new script beside this one, not a new major version of it.

Lives at `E:\proj\agent_comms` (`/mnt/e/proj/agent_comms` in WSL); backed up to a private GitHub repo.
