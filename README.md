# Courthouse

**One bench, three judges.** Courthouse is the plugin marketplace for the three
Clear-Sights guard engines. They split one taxonomy — **act, sequence,
statement** — and share nothing else: each installs alone, each is a pure
`stdlib` Python hook, and none inherits or implies the others' coverage.

| Engine | Judges | One line | Repo |
|---|---|---|---|
| **Ward** | the pending **act** | nothing outright bad happens | [Clear-Sights/Ward](https://github.com/Clear-Sights/Ward) |
| **Gyroscope** | the **sequence** | a session neither capsizes nor gets lost | [Clear-Sights/Gyroscope](https://github.com/Clear-Sights/Gyroscope) |
| **Makoto** | the **statement** | words aren't empty | [Clear-Sights/Makoto](https://github.com/Clear-Sights/Makoto) |

- **Ward** is stateless: an ordered 11-row table of exact denials over the one
  pending tool call — `verify=False`, JWT `alg=none`, auto-added host keys,
  secrets in outbound URLs, shell-startup writes — denied with a citation and a
  retry hint *before* the call executes.
- **Gyroscope** is stateful: a costly call (push, force-push, "done") is denied
  until the cheap call that licenses it (`git status`, `git fetch`) is on an
  obligation ledger; the *same* call then runs. Open demands block at Stop.
- **Makoto** is retrospective: every claim the agent makes is checked against
  its own logged record — "tests pass", "I pushed it", "it's running" — and a
  claim with no matching evidence blocks instead of warns.

## Start from the failure you know

| Failure | Engine |
|---|---|
| Claude turned a red test green by disabling TLS verification. | **Ward** denies the act before it executes. |
| Claude pushed over work it never fetched. | **Gyroscope** denies the push until the fetch is on record. |
| Claude said the tests pass; they had never been run. | **Makoto** blocks the claim against the session's own record. |

## Install

```console
$ claude plugin marketplace add Clear-Sights/Courthouse
$ claude plugin install ward@courthouse
$ claude plugin install gyroscope@courthouse
$ claude plugin install makoto@courthouse
```

Install any subset — the three verdicts are independent.

## The shared trust boundary

All three engines run inside the boundary of the very process they constrain: each is a hook fed
by the agent's own event stream, and intent is unobservable from outside that boundary, so they
judge only what crosses it — acts, sequences, and statements. A policy whose behavior stays inside
the check surface passes, whoever or whatever drives it. They constrain capability, not intent.

Why three engines and not four: act/sequence/statement is a partition of what an external judge
can observe, not a growing feature list. From outside the process there is nothing else to rule
on — a single pending event is an act, an ordering of events is a sequence, and text emitted about
them is a statement — so a candidate fourth engine would either judge one of those three surfaces
(and belong to an existing bench seat) or claim to judge intent, which no observer at this
boundary can see. Three judges exhaust the observable.

## Evidence

Each engine ships a corpus-replay eval you can run from its repository root
with nothing but the standard library — `python3 eval/replay.py` — replaying
recorded sessions through the real dispatcher: Ward 6/6, Gyroscope 5/5,
Makoto 5/5. Exit 0 iff every session meets its expectation. Those counts are replays of authored
fixtures through the real dispatchers — they prove each dispatcher fires where its fixtures say it
should, not that a live session behaves differently for having the hook installed; live-session
effect on agent behavior is unmeasured (Gyroscope's own SKILL.md says the same: "Built and
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
