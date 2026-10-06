# Plan: Level 0

**Goal.** Two AI agents exchange prompts through a shared directory with no human relaying messages or
waking either agent. The protocol is [`agent_channel.py`](agent_channel.py) ([DECISIONS.md](DECISIONS.md) D1).

**Level 0 is done when all of these hold:**
1. Two agents in *independent* sessions complete at least 3 rounds and a clean close, with one human
   paste at the start and no other human input (M2).
2. One such trial is with a non-Claude agent, or that agent correctly refuses via the self-test (M3).
3. One trial crosses a Windows/WSL path boundary (M4).
4. Suite and guard-removal check pass on Python 3.12 under `mypy --strict`; tagged and pushed (M1, M5).

## Milestones

Each "done when" is the acceptance test. Update **Status** as milestones land.

| # | Milestone | Done when | Work | Human step | Status |
|---|---|---|---|---|---|
| M0 | Project home | `E:\proj\agent_comms` scaffolded with private repo; code, tests, trial and records committed and pushed; suite passes there | 15 min | none | **done** 2026-10-06 |
| M1 | Harden | Suite and `mutation_check.py` 100% on Python 3.12 with `mypy --strict`; `STOP` kill switch added with a test and a mutant; one trial in which the primary's `recv` returns `waiting` at least once (run it with `--block-seconds 60` against a peer that takes 3–5 min) | 1–2 h | none | **done** 2026-10-06: 27 tests, 15/15 mutants, trial 2; plus BOM and python3 fixes from the trials |
| M2 | Cross-session trial, Claude ↔ Claude | Two independent Claude Code sessions; at least 3 rounds; clean close; transcript kept under `trials/` | 45 min wall | paste the secondary prompt once | **done** 2026-10-06, trial 4 |
| M3 | Heterogeneous trial, Claude ↔ Copilot | Same criteria, or a documented `REFUSED:` with the reason | 1–3 h, uncertain | paste once, in VS Code | not started |
| M4 | Windows ↔ WSL | One side on each; paths translated as the start prompt says; at least 1 round | 30 min | none (a subagent ran the WSL side) | **done** 2026-10-06, trial 3 |
| M5 | Release | README complete; v0.1 prose spec stays archived with its pointer to the script; tag `v1.0`; pushed | 30 min | none | not started |

**Order.** M0 → M1 and M2 in either order → M3 → M4 (folds into M2 or M3 if one side runs in WSL) → M5.
The critical path is the three trials, each gated on one paste.

**Estimate.** Roughly 4–7 hours of working time, most of it waiting on live agents; M3 is the uncertain
item. Calendar time depends on when the pastes can happen: realistically two or three sittings.

## Done so far (2026-10-05/06)
Script (about 200 lines, standard library, `mypy --strict` clean); 24 black-box tests; guard-removal
check 13/13; same-session live trial (2 rounds, clean close); DECISIONS.md, HISTORY.md, this plan; M0.

## Risks
- Copilot cannot stay awake through a 120 s silence. The `REFUSED:` path handles it, but Level 0 then
  has one proven agent family. Decide whether that meets the done bar (DECISIONS.md, Open).
- Permission prompts in a fresh session stall the secondary before it joins. The self-test should
  surface this; if it does, the start prompt needs an allow-list hint.
- A tool time limit below `--block-seconds` kills `recv` silently in some harnesses. The docstring
  warns; M1's `waiting` trial checks the re-run loop in practice.

## Out of scope: Level 1 candidates, not planned
`recv` over several directories (hub-and-spoke, one primary and N secondaries); git as transport; a
heartbeat so a slow peer is distinguishable from a dead one; A2A-style task states.
