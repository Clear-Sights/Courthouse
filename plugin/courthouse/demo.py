#!/usr/bin/env python3
"""Demo mode: show what each judge on the bench is DOING, as it does it.

WHY THIS EXISTS. Three guard engines run as hooks inside the agent's own process. When they work,
nothing appears: a hook that allows a call is indistinguishable from a hook that is not installed,
and the two things a shopper most wants to see -- that the bench is live, and what it caught --
are precisely the two the host never shows. Courthouse sells three judges nobody can watch.

Demo mode is that missing window. It is a MODE, not a scripted tour: switch it on and keep
working, and every time a judge actually fires you see it. Nothing is simulated and nothing is
re-enacted -- this reads the records the engines already write for their own reasons, so what it
prints is what happened.

WHAT COUNTS AS "DOING SOMETHING", AND WHAT DELIBERATELY DOES NOT. Only rows where a check came
back POSITIVE: a deny, a Stop-time block, a fault. Not the checks that passed. Ward and Keel both
already refuse to log allowed calls -- a sibling measured that policy at 99%+ noise -- and this
follows them, because a demo that narrates every allowed Bash call is a demo nobody watches long
enough to see a real deny.

THE ONE ASYMMETRY, STATED RATHER THAN SMOOTHED. Ward and Keel each write `decisions.jsonl`, a
plugin-attributed record with a session row for liveness and one row per refusal. Makoto writes
no such journal; its `events` table proves it SAW an event but records no verdict, so "Makoto
blocked nothing" is not a fact this tool can establish. It is therefore reported NOT-OBSERVABLE
and never as clean -- absence of a record is not a record of absence, which is the same law the
two journals were built to satisfy. Fixing that belongs in Makoto, not here.

FAILURE POSTURE: observability, never policy. This tool reads; it never writes to an engine's
state and never influences a verdict. An unreadable journal is reported as unreadable and cannot
turn into silence.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import pathlib
import sqlite3
import sys

# A check "comes back positive" when it fired -- these are the row kinds that mean the judge
# acted. `session` is liveness, not action, and is read separately; there is no allowed-call row
# to exclude because neither journal writes one.
POSITIVE_KINDS = ("deny", "block", "fault")

VERDICT_EXIT = {"PASS": 0, "FAIL": 1, "NOT-EVALUABLE": 2}


@dataclasses.dataclass(frozen=True)
class Activity:
    """One thing a judge did, normalised across three differently-shaped records."""

    plugin: str
    kind: str
    ts: str
    session_id: str
    tool_name: str
    subject: str

    def line(self) -> str:
        where = f" {self.tool_name}" if self.tool_name else ""
        return f"[{self.ts}] {self.plugin}.{self.kind}{where}  {self.subject}"


def state_root() -> pathlib.Path:
    """Where the engines keep their state. One override, so the self-test can point elsewhere."""
    env = os.environ.get("COURTHOUSE_STATE_ROOT")
    return pathlib.Path(env) if env else pathlib.Path.home() / ".claude"


def mode_file(root: pathlib.Path | None = None) -> pathlib.Path:
    return (root or state_root()) / "courthouse_state" / "demo-mode"


def mode_is_on(root: pathlib.Path | None = None) -> bool:
    return mode_file(root).is_file()


def set_mode(on: bool, root: pathlib.Path | None = None) -> bool:
    path = mode_file(root)
    if on:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("on\n", encoding="utf-8")
        # BASELINE ON SWITCH-ON. Whoever enables the mode wants to watch what happens NEXT, not
        # to be handed the whole back catalogue -- this bench's own journal holds 582 rows. The
        # cursor is set to now so the first thing shown is the first thing that fires.
        unseen(root, advance=True)
    elif path.is_file():
        path.unlink()
    return mode_is_on(root)


def _journal_rows(path: pathlib.Path) -> tuple[list[dict], str | None]:
    """Every parseable row of a `decisions.jsonl`, plus why it could not be read at all.

    A malformed LINE is skipped -- one truncated append (a killed hook mid-write) must not blind
    the whole window. A missing or unreadable FILE is a stated reason, never an empty list, so
    "no journal" can never be rendered as "nothing happened".
    """
    if not path.is_file():
        return [], f"no journal at {path}"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], f"unreadable journal at {path}: {exc}"
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows, None


def _describe(row: dict) -> str:
    """The one line a viewer reads. Prefer the engine's own words over anything invented here."""
    for key in ("reason", "detail", "message"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    if row.get("kind") == "block":
        return f"stop blocked: {row.get('unreconciled', '?')} unreconciled"
    return row.get("check_id") or row.get("clause") or row.get("kind", "")


def read_journal(plugin: str, root: pathlib.Path) -> tuple[list[Activity], bool, str | None]:
    """(what this engine did, whether it proved it ran, why it could not be read).

    Liveness is read from the `session` row both engines write on first sight of a session. It is
    reported separately from activity for the reason both journals give in their own docstrings:
    an empty log is otherwise ambiguous between a clean session and a plugin that never fired.
    """
    rows, unreadable = _journal_rows(root / f"{plugin}_state" / "decisions.jsonl")
    if unreadable:
        return [], False, unreadable
    live = any(row.get("kind") == "session" for row in rows)
    acted = [
        Activity(
            plugin=str(row.get("plugin") or plugin),
            kind=str(row.get("kind")),
            ts=str(row.get("ts") or ""),
            session_id=str(row.get("session_id") or ""),
            tool_name=str(row.get("tool_name") or ""),
            subject=_describe(row),
        )
        for row in rows
        if row.get("kind") in POSITIVE_KINDS
    ]
    return acted, live, None


def read_makoto(root: pathlib.Path) -> tuple[list[Activity], bool, str | None]:
    """Makoto's liveness only, and an explicit refusal to speak about its verdicts.

    Its `events` table records that an event was SEEN. No column carries the ruling, so a query
    over it can establish that Makoto ran and cannot establish that it allowed anything. Returning
    an empty activity list with `unobservable` set is the honest shape: the caller must not be
    able to mistake this for a clean bill.
    """
    path = root / "makoto_state" / "makoto.record.db"
    if not path.is_file():
        return [], False, f"no record at {path}"
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            seen = connection.execute("select count(*) from events").fetchone()[0]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return [], False, f"unreadable record at {path}: {exc}"
    return [], bool(seen), ("makoto records events seen, not verdicts reached: whether it "
                            "blocked anything is NOT OBSERVABLE from its own state")


ENGINES = ("ward", "keel", "makoto")


def survey(root: pathlib.Path | None = None) -> dict:
    """What every judge on the bench has done, with each engine's observability stated.

    `evaluated` counts ENGINES INSPECTED, not activity found, so a bench where nothing happened
    still has a real denominator. An engine whose record could not be read is `not_evaluable` --
    it is never folded into the quiet majority.
    """
    root = root or state_root()
    engines, findings, not_evaluable = {}, [], 0
    for name in ENGINES:
        if name == "makoto":
            acted, live, note = read_makoto(root)
        else:
            acted, live, note = read_journal(name, root)
        # An engine is observable when its record could be read AND that record carries verdicts.
        # Makoto is live-but-verdictless, so it fails the second test while passing the first;
        # counting it as `passed` because it ran is how a denominator comes to disagree with the
        # very page it prints -- observed here as `not-observable=1` under two NOT OBSERVABLE
        # lines. Whatever the render calls unobservable is what this counts.
        blind = bool(note)
        not_evaluable += blind
        engines[name] = {
            "live": live,
            "acted": [dataclasses.asdict(a) for a in acted],
            "observable": not blind,
            "note": note,
        }
        if blind:
            findings.append({"kind": "unobservable", "subject": name, "detail": note})
    total = sum(len(engine["acted"]) for engine in engines.values())
    return {
        "tool": "courthouse-demo", "subject": str(root),
        "verdict": "NOT-EVALUABLE" if not_evaluable else "PASS",
        "evaluated": len(ENGINES),
        "passed": len(ENGINES) - not_evaluable,
        "failed": 0,
        "not_evaluable": not_evaluable,
        "findings": findings,
        "engines": engines,
        "fired": total,
        "mode": "on" if mode_is_on(root) else "off",
    }


UNOBSERVABLE = "NOT OBSERVABLE"


def engine_state(engine: dict) -> str:
    """The one phrase describing an engine, named once so nothing can disagree with it.

    The render and the denominator each used to decide "is this engine observable?" for
    themselves, and they diverged: makoto printed NOT OBSERVABLE while being counted among the
    observable. One question gets one answer here, and `--self-test` compares the page with the
    count on every run.
    """
    if not engine["observable"]:
        return UNOBSERVABLE
    if not engine["live"]:
        return "no session row: not seen running"
    if engine["acted"]:
        return f"{len(engine['acted'])} fired"
    return "ran, nothing fired"


def render(report: dict) -> str:
    """The bench, as a viewer sees it. Every engine appears, including the silent ones."""
    lines = [f"COURTHOUSE DEMO MODE [{report['mode']}] -- what the bench is doing", ""]
    for name in ENGINES:
        engine = report["engines"][name]
        acted = engine["acted"]
        lines.append(f"{name:<8} {engine_state(engine)}")
        if engine["note"] and not acted:
            lines.append(f"         ^ {engine['note']}")
        for row in acted[-5:]:
            lines.append("         " + Activity(**row).line()[:160])
    lines += ["", f"DENOMINATOR subject=bench engines={report['evaluated']} "
                  f"observable={report['passed']} not-observable={report['not_evaluable']} "
                  f"fired={report['fired']}"]
    return "\n".join(lines)


def cursor_file(root: pathlib.Path) -> pathlib.Path:
    return root / "courthouse_state" / "demo-cursor.json"


def unseen(root: pathlib.Path | None = None, advance: bool = True) -> list[Activity]:
    """Only what has fired since the last look, so a live mode repeats nothing.

    The cursor is a per-engine count of positive rows already shown. Both journals are
    append-only, so a count is a valid cursor and survives concurrent writers; a count that
    exceeds what the file now holds (a rotated or truncated journal) resets to the end rather
    than replaying the whole history at someone mid-session.

    Never raises. This runs on the hook edge, where an exception would be a demo feature taking
    the session down with it.
    """
    root = root or state_root()
    try:
        path = cursor_file(root)
        try:
            seen = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(seen, dict):
                seen = {}
        except (OSError, ValueError):
            seen = {}
        fresh, moved = [], {}
        for name in ENGINES:
            acted = read_makoto(root)[0] if name == "makoto" else read_journal(name, root)[0]
            already = seen.get(name)
            already = already if isinstance(already, int) and 0 <= already <= len(acted) else len(acted)
            fresh.extend(acted[already:])
            moved[name] = len(acted)
        # Written whenever the cursor MOVED, not only when something fresh was found: the
        # switch-on baseline finds nothing by definition, and skipping the write there left no
        # cursor at all, so the next look baselined again and the mode never showed anything.
        if advance and moved != seen:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(moved), encoding="utf-8")
        return fresh
    except Exception:  # noqa: BLE001 -- observability must never break the session
        return []


def self_test() -> int:
    """Plant each defect this tool exists to avoid, and require it to be caught.

    The cell that matters most is the LAST one: a bench where nothing is installed must not
    render the same as a bench that ran clean. That is the whole claim of the module.
    """
    import tempfile

    passed = failed = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if ok:
            passed += 1
            print(f"PASS {name}")
        else:
            failed += 1
            print(f"FAIL {name} :: {detail}")

    def write(root: pathlib.Path, plugin: str, *rows: dict) -> None:
        path = root / f"{plugin}_state"
        path.mkdir(parents=True, exist_ok=True)
        with (path / "decisions.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    session = {"kind": "session", "plugin": "ward", "ts": "T0", "session_id": "s"}
    deny = {"kind": "deny", "plugin": "ward", "ts": "T1", "session_id": "s",
            "tool_name": "Write", "reason": "Denied (cert verification disabled)"}

    with tempfile.TemporaryDirectory(prefix="courthouse-demo-") as name:
        root = pathlib.Path(name)

        # NON-VACUITY FIRST. Every cell below reads this structure; if the reader returned nothing
        # for a journal that plainly has a deny in it, the rest would pass over an empty list.
        write(root, "ward", session, deny)
        acted, live, note = read_journal("ward", root)
        check("a planted deny is read back, with liveness",
              len(acted) == 1 and acted[0].kind == "deny" and live and note is None,
              f"{acted} live={live} note={note}")
        check("the engine's own words are what the viewer sees",
              "cert verification disabled" in acted[0].subject, acted[0].subject)

        # A PASSING CHECK IS NOT ACTIVITY. The whole point of the mode is that it stays quiet
        # until something fires; a row kind outside POSITIVE_KINDS must not surface.
        write(root, "ward", session)
        acted, live, _ = read_journal("ward", root)
        check("PLANT liveness with no deny is 'ran, nothing fired', not activity",
              acted == [] and live, f"{acted} live={live}")

        # A TRUNCATED APPEND MUST NOT BLIND THE WINDOW.
        path = root / "ward_state" / "decisions.jsonl"
        path.write_text(json.dumps(session) + "\n{\"kind\": \"de\n" + json.dumps(deny) + "\n",
                        encoding="utf-8")
        acted, live, note = read_journal("ward", root)
        check("PLANT a half-written row is skipped, not fatal",
              len(acted) == 1 and live and note is None, f"{acted} note={note}")

        # ABSENCE IS NEVER A PASS. This is the cell the module exists for.
        empty = pathlib.Path(name) / "bare"
        empty.mkdir()
        report = survey(empty)
        check("PLANT an uninstalled bench is NOT-EVALUABLE, never a clean PASS",
              report["verdict"] == "NOT-EVALUABLE" and report["not_evaluable"] == 3
              and report["evaluated"] == 3,
              json.dumps({k: report[k] for k in ("verdict", "evaluated", "not_evaluable")}))
        check("PLANT an uninstalled bench does not render as a quiet one",
              "NOT OBSERVABLE" in render(report) and "ran, nothing fired" not in render(report))

        # MAKOTO IS NEVER REPORTED CLEAN. Its record carries no verdict, so a caller must not be
        # able to read silence from it as an all-clear.
        makoto = root / "makoto_state"
        makoto.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(makoto / "makoto.record.db")
        connection.execute("create table events (id integer primary key)")
        connection.execute("insert into events values (1)")
        connection.commit()
        connection.close()
        acted, live, note = read_makoto(root)
        check("makoto proves liveness but is explicitly NOT OBSERVABLE for verdicts",
              live and acted == [] and note is not None and "NOT OBSERVABLE" in note.upper(),
              f"live={live} note={note}")
        check("and the bench render says so rather than calling it clean",
              "NOT OBSERVABLE" in render(survey(root)))

        # THE MODE TOGGLES, AND THE TOGGLE IS WHAT THE REPORT READS.
        check("mode is off until switched on", not mode_is_on(root))
        check("PLANT switching the mode on is observable in the report",
              set_mode(True, root) and survey(root)["mode"] == "on")
        check("and switching it off returns it", not set_mode(False, root)
              and survey(root)["mode"] == "off")

        # THE DENOMINATOR MUST AGREE WITH THE PAGE IT PRINTS. Caught live: makoto rendered
        # NOT OBSERVABLE while being counted among the observable, because the render keyed on
        # the engine's name and the count keyed on whether its record could be opened. Two
        # predicates for one question is how a count comes to contradict its own output.
        for label, fixture in (("mixed bench", root), ("bare bench", empty)):
            report = survey(fixture)
            shown = sum(engine_state(engine) == UNOBSERVABLE
                        for engine in report["engines"].values())
            check(f"the denominator agrees with the rendered page ({label})",
                  shown == report["not_evaluable"],
                  f"rendered {shown} but counted {report['not_evaluable']}")

        # THE MODE MUST NOT REPEAT ITSELF. A window that reprints the same deny on every event
        # is one people switch off, and then it catches nothing.
        write(root, "ward", session, deny)
        set_mode(True, root)
        check("switching the mode on baselines: history is not dumped at the viewer",
              unseen(root) == [])
        write(root, "ward", session, deny, dict(deny, ts="T2", reason="Denied (second)"))
        second = unseen(root)
        check("PLANT one new deny shows exactly that one",
              len(second) == 1 and "second" in second[0].subject, str(second))
        # A TRUNCATED JOURNAL MUST NOT REPLAY HISTORY AT SOMEONE MID-SESSION.
        write(root, "ward", session)
        check("PLANT a rotated journal resets instead of replaying", unseen(root) == [])

    # THE HOOK EDGE, DRIVEN AS THE HOST DRIVES IT. Everything above tests the reader; this
    # tests the thing that actually ships -- `hooks/dispatch.sh`, as a subprocess, over a real
    # state directory. The reader being right does not make the hook wired.
    import subprocess
    import tempfile

    dispatcher = pathlib.Path(__file__).resolve().parent.parent / "hooks" / "dispatch.sh"

    def drive(root: pathlib.Path) -> dict:
        environment = dict(os.environ, COURTHOUSE_STATE_ROOT=str(root))
        done = subprocess.run(["bash", str(dispatcher)], input="{}", text=True,
                              capture_output=True, env=environment)
        assert done.returncode == 0, f"the hook must always exit 0, got {done.returncode}"
        return json.loads(done.stdout or "{}")

    with tempfile.TemporaryDirectory(prefix="courthouse-hook-") as name:
        root = pathlib.Path(name)
        write(root, "ward", session)
        check("the hook is silent while the mode is off", drive(root) == {})
        set_mode(True, root)
        check("PLANT mode on but nothing fired is still silent", drive(root) == {})
        write(root, "ward", session, deny)
        spoken = drive(root)
        check("PLANT a deny reaches the user as a systemMessage",
              "cert verification disabled" in spoken.get("systemMessage", ""), str(spoken))
        check("PLANT the same deny is not repeated on the next event", drive(root) == {})
        set_mode(False, root)
        write(root, "ward", session, deny, dict(deny, ts="T9", reason="Denied (later)"))
        check("PLANT switching off silences it again", drive(root) == {})

    print(f"DENOMINATOR subject=courthouse-demo-selftest checks={passed + failed} "
          f"passed={passed} failed={failed}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--on", action="store_true", help="switch demo mode on")
    parser.add_argument("--off", action="store_true", help="switch demo mode off")
    parser.add_argument("--json", action="store_true", help="the shared verdict envelope")
    parser.add_argument("--self-test", action="store_true",
                        help="plant each defect and require it to be caught")
    arguments = parser.parse_args(argv)
    if arguments.self_test:
        return self_test()
    if arguments.on or arguments.off:
        set_mode(arguments.on)
    report = survey()
    if arguments.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(render(report))
    return VERDICT_EXIT[report["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
