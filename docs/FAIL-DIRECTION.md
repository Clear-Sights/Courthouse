# Fail direction: what each judge does when its own machinery breaks

**Status:** normative for the three plugins in this marketplace. Ward, Keel and Makoto each
link here from their dispatcher, and each records which way it fell in its own log.

The sequence judge shipped as **Gyroscope** through v1.1.0 and is **Keel** from v2.0.0. The
incident recorded below was measured under the old name and is quoted as it was observed; the
policy sections use the current one.

## The problem this settles

The three plugins disagreed about internal-error handling, and the disagreement was invisible
until one input made all three answer at once.

Ward's `hooks/dispatch.sh` states the principle it follows:

> a gate whose machinery cannot even start fails CLOSED, never silently open

Makoto's observed behaviour on its own crash was the opposite — fail-open, recorded as
`loud-allow`, tool call proceeds unchecked. Gyroscope did a third thing again: a clause whose
subject could not be derived raised inside a per-clause `except Exception: continue`, so it neither
denied nor passed but silently abstained.

Those were three defensible-sounding rules, held by three plugins that share one hook edge, with
nothing anywhere saying which was right. That is not a policy; it is three policies.

### The input that made it concrete

A hook subprocess inherits no `LANG`, so CPython enables UTF-8 mode and gives `sys.stdin` the
`surrogateescape` error handler. A host byte that is not valid UTF-8 therefore enters as a **lone
surrogate** (`0xDC00 + byte`) rather than raising or being replaced. One such byte — `0x9D`, a
CP1252 character in a file being written — produced:

| Plugin | What happened | Verdict on the pending call |
|---|---|---|
| Makoto | `sqlite3` bind raised `UnicodeEncodeError` → catch-all | **allowed, unchecked** (30× in one day, live) |
| Ward | `ast.parse` refused it → `_cannot_evaluate` | **denied**, with a stated reason that was false |
| Gyroscope | `derive_id` raised inside per-clause isolation | **silently abstained**, no record |

One byte, three verdicts, none of them about the pending action. All three now repair the byte at
their own stdin boundary (`wire.py` in each), so no check anywhere is handed a lone surrogate to be
confused by. That removes this instance. The policy below is what governs the next one.

## The policy

**Fail direction follows recoverability, not plugin taste.**

The question is never "is open or closed safer in general" — it is *what is lost if this particular
judge misses this particular event, and can it be recovered later in the session?*

### 1. Ward — the act — fails CLOSED, always

Ward rules on what the pending call *does*. A dangerous act allowed is not recoverable at the next
event or at Stop: the write landed, the credential left, the host key was accepted. There is no
later moment at which Ward gets a second chance, so there is no fail-open that is merely a delay.

Ward fails closed on malformed input, on a check that raises, and on a shim that cannot start.

### 2. Makoto and Keel — the statement, the sequence — fail OPEN on carriage, CLOSED on decision

Both judge things that remain judgeable later. An unevaluated claim can be caught at the next
claim or at Stop; an unrecorded obligation is reconciled at the terminal. A missed evaluation costs
coverage of one event, not the session.

- **Carriage failure** — the hook could not be reached at all: no interpreter, no plugin root,
  unreadable stdin, a locked database. Fails **OPEN**. Carriage that blocks is worse than carriage
  that is absent: a broken install that denies every tool call is uninstalled within the hour, and
  an uninstalled gate has zero coverage.
- **Decision failure** — the machinery ran and a decision could not be computed for an event the
  plugin owns. Fails **CLOSED**, via the event's own deny/block wire. A gate that cannot decide has
  not decided, and reporting success by default is the failure the whole loop exists to refuse.

### 3. A fail-open is never silent — and "loud" means the user, not a log file

This is the part that was written down and still not true in practice.

Hook stderr on exit 0 goes to the **debug log only**. Not the transcript, not the user, not the
model. So "loud-allow + stderr" was loud to nobody: a skipped check was indistinguishable, from
every seat, from a clean pass. That is how 30 fail-opens in one day went unnoticed.

Every fail-open must therefore emit a `systemMessage` — the universal hook-output field that is
actually surfaced — saying the call was allowed **without being checked**. The direction is
unchanged. Only the visibility is.

### 4. A repaired payload is not a fail-open

An event whose bytes had to be repaired but which was then **evaluated normally** is recorded as
`repair`, never as a fault or a loud-allow. Conflating the two inflates the count of unevaluated
calls, and that count is the one number this policy needs to stay honest.

### 5. A deny must never rest on a false fact

Ward's byte case was fail-*closed*, so by direction alone it was correct. It was still a bug: the
reason given ("introduced Python fragment cannot be parsed independently") was false, and an agent
cannot act on a false reason. It rewrites code that was never the problem, the byte survives every
rewrite, and the loop does not heal.

Failing closed licenses refusing. It does not license explaining the refusal wrongly.

## How this is audited, not merely documented

Each plugin writes `failed_closed: true|false` on every fault row in its own log
(`dispatch_errors.jsonl` for Makoto, `decisions.jsonl` for Ward and Keel). The table above is
therefore checkable against the record rather than against these paragraphs — a plugin that drifts
from its row leaves the evidence itself.

Every row also carries `plugin`, `session_id` and `tool_name`, and every deny reason is prefixed
with the emitting plugin's name. All three register PreToolUse and the host shows the user a reason
but never a source; without the prefix, "which plugin blocked this?" is answerable only by guessing
from wording, and after the fact not at all.

## Check ownership

One check, one owner. Where two plugins could plausibly cover the same ground, the row below says
who does — and the other one does not implement it.

| Concern | Owner | Explicitly not |
|---|---|---|
| WebFetch URL provenance (is this URL fabricated?) | **Makoto** — `content.unsourced_webfetch` | Ward. Ward's writ is the act itself; it treats `WebFetch`/`WebSearch`/`mcp__*` as world-reaching tools for its outbound-secret check and inspects nothing about URL provenance. |
| Weakened TLS / JWT / host-key verification, protected-path writes, outbound secrets | **Ward** | Makoto. |
| Obligation ordering (cheap call before costly call) | **Keel** | Both. |

Ward carries no URL-provenance check and is not to acquire one. If a future check genuinely needs
to live in two plugins, it does not go in either until this table says which one owns it.
