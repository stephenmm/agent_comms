# agent_comms

Minimal file-based channel for two AI agents to exchange prompts with no human relay.

The protocol **is** [`agent_channel.py`](agent_channel.py): an agent reads the script and uses its four
commands, and never writes channel files by hand. Why code rather than a prose spec:
[DECISIONS.md](DECISIONS.md) D1.

## Status
Level 0 implemented and tested within one session; cross-session trials pending. Milestones and the
definition of done are in [PLAN.md](PLAN.md).

## How a channel runs
1. The **primary** agent creates the channel and sends the first message, whose body gives the secondary
   its role and task:
   ```bash
   python agent_channel.py init <parent-dir>           # prints the channel path and the secondary's start prompt
   python agent_channel.py selftest                    # 120 s of silence; pass = the agent woke on its own
   echo "Your role is ... Your task is ..." | python agent_channel.py send <channel-dir> primary
   python agent_channel.py recv <channel-dir> primary  # blocks until the reply arrives
   ```
2. The owner pastes the printed start prompt into the **secondary** agent. That paste is the only human
   step.
3. Both agents alternate `recv` → act → `send` until one sends `--end`.
4. The owner can halt both agents at any time with `python agent_channel.py stop <channel-dir>`; each
   sees `closed` on its next command, a blocked `recv` within 5 s.

Every command prints one JSON object with a `status` of `message`, `waiting`, `closed` or `error`
(exit codes 0, 2, 3, 4).

## Tests
```bash
py -3.12 -m unittest test_agent_channel -v   # 27 black-box tests, about 1 min
py -3.12 mutation_check.py                   # removes each guard in turn; every one must turn the suite red (about 4 min)
py -3.12 -m mypy --strict agent_channel.py test_agent_channel.py mutation_check.py
```

## Layout
| Path | What |
|---|---|
| `agent_channel.py` | the protocol |
| `test_agent_channel.py`, `mutation_check.py` | tests and the guard-removal check |
| `trials/` | transcripts of live agent-to-agent trials, one directory each |
| `docs/AGENT_CHANNEL_L0_v0.1.md` | the original prose spec, archived |
| `DECISIONS.md`, `HISTORY.md`, `PLAN.md` | why, how we got here, what is left |

Lives at `E:\proj\agent_comms` (`/mnt/e/proj/agent_comms` in WSL); backed up to a private GitHub repo.
