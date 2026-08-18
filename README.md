# Tribunal

**One bench, three judges.** Tribunal is the plugin marketplace for the three
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

## Install

```console
$ claude plugin marketplace add Clear-Sights/Tribunal
$ claude plugin install ward@tribunal
$ claude plugin install gyroscope@tribunal
$ claude plugin install makoto@tribunal
```

Install any subset — the three verdicts are independent.

## Evidence

Each engine ships a corpus-replay eval you can run from its repository root
with nothing but the standard library — `python3 eval/replay.py` — replaying
recorded sessions through the real dispatcher: Ward 6/6, Gyroscope 5/5,
Makoto 5/5. Exit 0 iff every session meets its expectation.

## License

The marketplace manifest in this repository is Apache-2.0 — see
[LICENSE](LICENSE). Each engine is licensed in its own repository
(all three Apache-2.0).
