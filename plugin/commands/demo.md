---
description: Courthouse demo mode — show what each judge on the bench is doing
argument-hint: "[on|off]"
arguments: state
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/courthouse/demo.py" *)
disable-model-invocation: true
---

## Courthouse demo mode

!`python3 "${CLAUDE_PLUGIN_ROOT}/courthouse/demo.py" ${ARGUMENTS:+--$ARGUMENTS}`

Three guard engines run as hooks inside the process they constrain, so when they work you
see nothing: a hook that allows a call looks exactly like a hook that was never installed.
Demo mode is the window into that. It is a **mode**, not a tour — switch it on with
`/demo on` and keep working; every time a judge actually fires, you see it.

What appears is only what **came back positive**: a deny, a Stop-time block, a fault. Checks
that passed are deliberately absent — Ward and Keel both refuse to log allowed calls, having
measured that policy at 99%+ noise, and a demo that narrates every allowed `Bash` call is one
nobody watches long enough to see a real deny.

Nothing here is simulated. This reads `decisions.jsonl`, the plugin-attributed record each
engine already writes for its own reasons, so what it prints is what happened.

**One engine is honest about being unreadable.** Makoto writes no such journal — its record
proves it *saw* an event but carries no verdict — so it is reported `NOT OBSERVABLE` and never
as clean. Absence of a record is not a record of absence.

Exit `0` every engine observable · `2` at least one is not. This command reads; it never writes
to an engine's state and never changes a verdict.
