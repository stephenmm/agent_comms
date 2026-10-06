> **Archived 2026-10-06.** This is the prose specification the project started from, kept verbatim as a
> historical record. It is superseded by [`agent_channel.py`](../agent_channel.py), which is now the
> normative protocol (see [DECISIONS.md](../DECISIONS.md) D1). Known defects of this text are listed in
> [HISTORY.md](../HISTORY.md), entry 2026-10-05.

# Agent Channel — Level 0 Specification

Version 0.1 (2026-10-05). The keywords MUST, MUST NOT, SHOULD and MAY are used as in RFC 2119.

Level 0 is the minimum two AI agents need to exchange prompts through a shared directory, with no human
relaying messages between them. Agents may add header fields; Level 0 ignores them.

## 1. Roles

- One agent is the **primary**; the other is the **secondary**.
- The primary decides the secondary's role and task, and states them in the body of its first message.
- The primary creates the channel. The secondary only joins it.

## 2. Channel directory

- The primary creates a new, empty directory named `<session>_agent_channel`.
  `<session>` is the primary's session name or ID. If it has none, it uses a timestamp such as
  `20261005T2300`.
- The directory MUST be on storage that both agents can read and write. It is always referred to by its
  **absolute path**.
- The directory MUST NOT already contain channel files. Each session uses a new channel.

## 3. Message files

- **Names:** `ch-p2s-NNN.json` (primary to secondary) and `ch-s2p-NNN.json` (secondary to primary).
  `NNN` is a three-digit number, zero-padded and starting at `000`.
- Only names that exactly match `ch-(p2s|s2p)-[0-9]{3}.json` are messages. Readers ignore every other file.
- **Strict alternation:**

  ```
  ch-p2s-000 -> ch-s2p-000 -> ch-p2s-001 -> ch-s2p-001 -> ...
  ```

  - After writing `p2s-N`, the primary waits for `s2p-N`.
  - After writing `s2p-N`, the secondary waits for `p2s-(N+1)`.
  - Each agent therefore knows exactly which file to wait for, and needs no record of which files it has
    read.
- **Atomic write:** write the full content to a temporary file in the same directory, named
  `.<final-name>.tmp`. Then rename it to the final name. A file that has its final name is complete.
- **Immutable:** once renamed, a message is never edited, deleted, renamed or reused.

## 4. File format

UTF-8 JSON with exactly two top-level keys:

```json
{
  "header": {
    "reference_file": "ch-p2s-000.json"
  },
  "body": "The prompt for the other agent, as one string."
}
```

| Header field | Required | Meaning |
|---|---|---|
| `reference_file` | yes | Name of the message this one answers. `"NONE"` only in `ch-p2s-000.json`. |
| `end` | no | `true` closes the channel (§6). If absent, it is `false`. |
| `max_wait_minutes` | no | Only read from `ch-p2s-000.json`. Sets the wait timeout for both sides. Default 60. |

- `reference_file` MUST name the previous message in the order of §3:
  - `s2p-N` answers `p2s-N`;
  - `p2s-N`, for N > 0, answers `s2p-(N-1)`.
- Agents MUST write the file with a JSON library (for example Python `json.dump` or `jq`), never by
  hand-escaping text.
- If a reader finds invalid JSON, a missing field or a wrong `reference_file`, it is a protocol error
  (§6).

## 5. Waiting and self-wake

**No human may be needed to wake an agent.** The owner must never have to tell an agent to check the
channel.

- **Requirement:** after writing a message, the agent MUST keep waiting for the expected file without any
  human input, for up to `max_wait_minutes`. When the file appears, it MUST resume on its own and read it.
- **Efficiency:** the waiting SHOULD be done by a process outside the model, such as a shell loop,
  `inotifywait`, or a background job. The model should be re-invoked only when that process reports
  something.
  - Typical checks are every 5–30 s.
  - The agent MUST NOT spend model calls listing the directory repeatedly while nothing has changed,
    unless its environment offers no other way to stay awake.
- **Self-test before joining:** each agent MUST prove that its mechanism works before it joins.
  1. Start a separate process that creates `<dir>/.selftest-<role>` after **at least 120 s** with no
     output.
  2. Wait for that file with the same mechanism the agent will use in the channel.
  3. **Pass:** the agent resumes on its own and reads the file, with no user message in between.
     **Fail:** anything else, including the agent ending its turn and needing to be prompted.
  4. The agent MAY then delete its own `.selftest-*` file.
- **Refusal:** an agent that cannot pass the self-test MUST refuse the connection.
  - **Primary:** it does not write `ch-p2s-000.json`, and tells its owner why.
  - **Secondary:** it writes `ch-s2p-000.json` with `"end": true` and a body beginning `REFUSED:` that
    gives the reason. Then it stops.
- **Known mechanisms (informative):**

  | Agent | Mechanism that keeps the agent awake |
  |---|---|
  | Claude Code | A background Bash job that wakes the agent when it exits, or a blocking wait loop re-run within the tool timeout. |
  | GitHub Copilot (VS Code) | An async terminal waiter that prints a heartbeat, polled with `get_terminal_output` **within the same turn**. Ending the turn to wait for a notification is not reliable, and fails the self-test. |
  | Any shell-capable agent | A blocking `until [ -e "$F" ]; do sleep 5; done`, bounded below the tool's time limit and re-run until the file appears or the channel times out. |

## 6. Ending the channel

- **Normal close:** either agent closes the channel by writing its next message with `"end": true`. The
  body MAY contain a final message.
- **Receiver of an `end` message:** it reads the message, MUST NOT reply, and stops waiting.
- **Timeout:** an agent that waits longer than `max_wait_minutes` writes its own next message with
  `"end": true` and a body beginning `TIMEOUT:`. Then it stops and reports to its owner.
  - Because this is the agent's own next number, it cannot collide with the peer's file.
  - If the peer answers late, it will then find this `end` file as the next message it expects.
- **Protocol error:** an agent that detects one (§4) writes its next message with `"end": true` and a body
  beginning `ERROR:` that describes the problem. Then it stops.

## 7. Starting a channel

Agents are started by prompt. Each start prompt MUST contain:
- the agent's role;
- the absolute path of the channel directory;
- these rules, either the full text or the absolute path to this file.

Steps:
1. The owner gives the primary its start prompt.
2. The primary:
   1. creates the directory;
   2. runs the self-test;
   3. writes `ch-p2s-000.json`. Its body gives the secondary's role and its first task.
3. The primary prints the secondary's start prompt, with the directory filled in. The owner pastes it into
   the secondary agent once. This one paste is the only human step in the session.
4. The secondary:
   1. runs the self-test, then either refuses (§5) or reads `ch-p2s-000.json`;
   2. carries out the request;
   3. writes `ch-s2p-000.json`, then waits.

### 7.1 Primary start prompt (template)

```
You are the PRIMARY of a Level 0 agent channel. Follow the spec at <ABS PATH TO AGENT_CHANNEL_L0.md>.
1. Create the channel directory <ABS PARENT>/<session>_agent_channel.
2. Run the self-wake self-test (spec §5). If it fails, stop and tell me why.
3. Write ch-p2s-000.json (reference_file "NONE"). Its body gives the secondary's role and first task:
   <ROLE AND TASK FOR THE SECONDARY>
4. Print the secondary start prompt (spec §7.2) with the directory path filled in.
5. Wait for each reply without asking me. Continue until the task is done, then close the channel with
   "end": true.
```

### 7.2 Secondary start prompt (template)

```
You are the SECONDARY of a Level 0 agent channel. Follow the spec at <ABS PATH TO AGENT_CHANNEL_L0.md>.
Channel directory: <ABS PATH>/<session>_agent_channel
Your role is set by the primary in ch-p2s-000.json.
1. Run the self-wake self-test (spec §5). If it fails, write ch-s2p-000.json with "end": true and a body
   beginning "REFUSED:", then stop.
2. Otherwise read ch-p2s-000.json. Carry out the request and reply in ch-s2p-000.json.
3. After each reply, wait for the next ch-p2s file without asking me. Stop when you receive "end": true.
```

## 8. Compliance checklist

- [ ] Writes every message to a `.tmp` file, then renames it.
- [ ] Never modifies a message after the rename.
- [ ] Waits only for the next expected filename (§3).
- [ ] Writes valid JSON with the correct `reference_file`.
- [ ] Passed the self-test, or refused.
- [ ] Never asks the owner to wake it.
- [ ] Ends with `end: true` on completion, timeout or protocol error.
