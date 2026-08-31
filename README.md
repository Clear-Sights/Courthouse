# Courthouse

The bench: a plugin marketplace. It states only the facts it owns and links the rest.

**One bench, three judges.[^m-judge-count]** Courthouse is the plugin marketplace for the three
Clear-Sights guard engines. They split one taxonomy — **act, sequence,
statement** — and share nothing else: each installs alone, each is a pure
`stdlib` Python hook, and none inherits or implies the others' coverage.

| Engine | Judges | One line | Repo |
|---|---|---|---|
| **Ward** | the pending **act** | nothing outright bad happens | [Clear-Sights/Ward](https://github.com/Clear-Sights/Ward) |
| **Keel** | the **sequence** | a session neither capsizes nor gets lost | [Clear-Sights/Keel](https://github.com/Clear-Sights/Keel) |
| **Makoto** | the **statement** | words aren't empty | [Clear-Sights/Makoto](https://github.com/Clear-Sights/Makoto) |

- **Ward** is stateless: an ordered table of exact denials over the one
  pending tool call — `verify=False`, JWT `alg=none`, auto-added host keys,
  secrets in outbound URLs, shell-startup writes — denied with a citation and a
  retry hint *before* the call executes.
- **Keel** is stateful: a costly call (push, force-push, "done") is denied
  until the cheap call that licenses it (`git status`, `git fetch`) is on an
  obligation ledger; the *same* call then runs. Open demands block at Stop.
  It also ships the positive half: for each denied moment, what to build so the
  guard's outcome arrives with nobody running anything and the deny never fires.
- **Makoto** is retrospective: every claim the agent makes is checked against
  its own logged record — "tests pass", "I pushed it", "it's running" — and a
  claim with no matching evidence blocks instead of warns.

## Start from the failure you know

| Failure | Engine |
|---|---|
| Claude turned a red test green by disabling TLS verification. | **Ward** denies the act before it executes. |
| Claude pushed over work it never fetched. | **Keel** denies the push until the fetch is on record. |
| Claude said the tests pass; they had never been run. | **Makoto** blocks the claim against the session's own record. |

## Install

```console
$ claude plugin marketplace add Clear-Sights/Courthouse
$ claude plugin install ward@courthouse
$ claude plugin install keel@courthouse
$ claude plugin install makoto@courthouse
```

Install any subset — the three verdicts[^m-judge-count] are independent.

The manifest lists four entries[^m-plugin-count]: the judges above, plus demo mode, which is
bench tooling and rules on nothing.

## The shared trust boundary

All three engines[^m-judge-count] run inside the boundary of the very process they constrain: each is a hook fed
by the agent's own event stream, and intent is unobservable from outside that boundary, so they
judge only what crosses it — acts, sequences, and statements. A policy whose behavior stays inside
the check surface passes, whoever or whatever drives it. They constrain capability, not intent.

Why three engines[^m-judge-count] and not four: act/sequence/statement is a partition of what an external judge
can observe, not a growing feature list. From outside the process there is nothing else to rule
on — a single pending event is an act, an ordering of events is a sequence, and text emitted about
them is a statement — so a candidate fourth engine would either judge one of those three surfaces[^m-judge-count]
(and belong to an existing bench seat) or claim to judge intent, which no observer at this
boundary can see. Three judges[^m-judge-count] exhaust the observable.

## When a judge's own machinery breaks

The three judges[^m-judge-count] share one hook edge, so "what happens when a check cannot run?" is a bench-wide
question, not three private ones — and it was answered three different ways until one input made
all three answer at once. A single non-UTF-8 byte in a hook payload got Makoto to allow the call
unchecked, Ward to deny a benign file citing a parse failure that was not real, and the sequence
judge — then shipping as Gyroscope — to abstain in silence.

The settled policy is **[docs/FAIL-DIRECTION.md](docs/FAIL-DIRECTION.md)**, and its rule is that
fail direction follows *recoverability*, not plugin taste: Ward rules on the act, which cannot be
un-done at the next event, so it fails closed on everything; Makoto and Keel rule on things
still judgeable later, so they fail open on carriage and closed on decision. No fail-open is
silent — each emits a `systemMessage` saying the call was allowed without being checked, because
hook stderr on a successful exit reaches the debug log and nobody else.

That document also carries the **check-ownership table**: one check, one owner, and the sibling
that does not own it does not implement it.

## Demo mode: see what the bench is doing

The judges run as hooks inside the process they constrain, so when they work you see nothing —
a hook that allows a call is indistinguishable from a hook that was never installed. That is
fine for a guard and bad for a storefront: what is worth seeing — that the bench is live,
and what it caught — is exactly what the host never shows.

Demo mode is that window, and it is a **mode**, not a scripted tour. Switch it on and keep
working; every time a judge actually fires, you see it.

```console
$ /demo on
$ /demo            # what the bench has been doing
```

Only what came back **positive** appears — a deny, a Stop-time block, a fault, or an
obligation Keel raised. Checks that
passed are deliberately absent: Ward and Keel both refuse to log allowed calls, having each measured that
policy and found it overwhelmingly noise (the figure is published in their own READMEs, which
own it), and a window narrating every allowed call is one nobody watches long enough to see a
real deny. Nothing is simulated: it reads the records the engines already write for their own
reasons, so what it prints is what happened.

The engines are read through every record each one writes, which is not the same number of
records for each. Ward writes `decisions.jsonl`. Keel writes that **and** `obligations.jsonl`,
because Keel is a keel: half its job is refusing an act, and the other half is demanding one, and
only the first half lands in `decisions.jsonl`. Reading the refusals alone reported an engine that
had raised obligations and denied nothing as *"ran, nothing fired"* — silence printed as a fact
about an engine that had been working. Demands are counted in their own lane, never folded into
the refusal count: an obligation still open and one already discharged are different states, and
one number moving for both would hide the distinction the ledger exists to keep. Makoto writes
`audit.jsonl`, one row per finding-producing dispatch carrying which checks fired, the exit code,
and the findings themselves — so it names the rule *and* the ruling where the siblings name the
denial alone. All three log only what fired, each having measured that recording silent passes
floods the log to overwhelming noise, so an empty log means nothing fired rather than nothing
was watched.

Demo mode is the bench's own tooling and **not a fourth judge**: it rules on nothing, denies
nothing, and cannot change a verdict. The partition argued above is unaffected — it observes
the judges, it does not join them.

## Evidence

Each engine ships a corpus-replay eval you can run from its repository root
with nothing but the standard library — `python3 eval/replay.py` — replaying
recorded sessions through the real dispatcher. Each engine's own README publishes its
session counts, and each harness exits nonzero unless every session meets its expectation.
Those runs are replays of authored
fixtures through the real dispatchers — they prove each dispatcher fires where its fixtures say it
should, not that a live session behaves differently for having the hook installed; live-session
effect on agent behavior is unmeasured (Keel's own README says the same: "Built and
mechanism-verified is not live-model measured").

## Plugin descriptions

The plugin descriptions in [.claude-plugin/marketplace.json](.claude-plugin/marketplace.json) are
copies of each engine's current self-description. On any disagreement between this storefront and
an engine's own README, the engine's README wins — the storefront is synced from the merchandise,
never the reverse.

## License

The marketplace manifest in this repository is Apache-2.0 — see
[LICENSE](LICENSE). Each engine is licensed in its own repository
(all three Apache-2.0).

[^m-judge-count]: The judges on the bench — marketplace entries that rule on something, counted by `python3 -c 'import json; print(sum(1 for p in json.load(open(".claude-plugin/marketplace.json"))["plugins"] if "bench-tooling" not in (p.get("tags") or [])))'`. Bench tooling is tagged out by name, so adding a tool cannot quietly restate this number as a claim about judges.
[^m-plugin-count]: Every entry in the marketplace manifest, judges and bench tooling alike, counted by `python3 -c 'import json; print(len(json.load(open(".claude-plugin/marketplace.json"))["plugins"]))'`.
