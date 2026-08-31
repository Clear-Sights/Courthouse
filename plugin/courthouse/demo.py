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


LEDGER_FILE = "obligations.jsonl"


def _describe_demand(row: dict) -> str:
    """Keel's own words for what it demanded, never a sentence invented here."""
    # The field names are Keel's, read from its `Demand` dataclass (`keel/ledger.py:131-137`:
    # id, session, agent, clause_id, subject, reason), not guessed from this side. A demand row
    # carries NO timestamp -- `_append` adds only `prev` and `hash` -- so `Activity.ts` is empty
    # for a demand, which is a measured absence rather than a field this reader failed to find.
    for key in ("reason", "subject", "clause_id"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return str(row.get("id") or "a demand with no subject")


def read_ledger(root: pathlib.Path) -> tuple[list[Activity], dict, str | None]:
    """Keel's POSITIVE half: what it demanded, what was discharged, what is still open.

    WHY THIS EXISTS. This module read `decisions.jsonl` and nothing else, and `POSITIVE_KINDS`
    names only refusals -- deny, block, fault. But Keel is a keel: half its job is ensuring the
    good outcome arrives, and that half writes `obligations.jsonl`, never `decisions.jsonl`. So a
    Keel that raised fifty demands and denied nothing reported `acted: []`, `observable: true`,
    `verdict: PASS` -- "Keel did nothing" printed as a fact about an engine that had been working
    the whole time. This file states the governing law in its own header ("absence of a record is
    not a record of absence") and then broke it for the same engine, one file over.

    OPENNESS IS SCOPED, and mirroring that is the whole correctness of this function. Keel
    computes open demands PER (session, agent) -- `keel/ledger.py:250-256` skips every row whose
    session or agent differs before subtracting discharges. Computing it globally would let a
    discharge in one session close a demand raised in another, which is the same act reported as
    resolved by evidence from a different run.

    TWO SPELLINGS OF ONE RULE, ACKNOWLEDGED. Keel owns this rule; the honest fix would be to call
    `Ledger.open_ids`, but Courthouse is a separate plugin that cannot import a sibling it does not
    ship. So this is a re-derivation across a trust boundary, and it is pinned rather than trusted:
    the self-test plants rows in the exact shape `keel/ledger.py` appends (`kind` demand/discharge,
    scoped by `session` and `agent`, identified by `id`) and asserts the split, including the
    cross-scope case. If Keel changes the shape, that cell fails rather than this reader silently
    reporting a wrong number.

    ABSENCE IS SILENCE, NOT BLINDNESS. The ledger is written only when a demand is raised -- the
    same only-fires policy `audit.jsonl` follows -- so a MISSING file means nothing was demanded
    and carries no note. Only a file that exists and cannot be READ is a stated reason.
    """
    path = root / "keel_state" / LEDGER_FILE
    # ABSENT and UNREADABLE are different answers and must not share a branch. `is_file()` is
    # false for BOTH a missing journal and a directory sitting where the journal belongs, so
    # testing it alone reported a broken state as "nothing was ever demanded" -- absence
    # manufactured out of a fault, which is the exact defect this lane was added to remove.
    # Caught by the cell below, not by reading this back.
    if not path.exists():
        return [], {"demanded": 0, "discharged": 0, "open": 0, "balanced": True}, None
    if not path.is_file():
        return [], {}, f"ledger path is not a readable file: {path}"
    rows, unreadable = _journal_rows(path)
    if unreadable:
        return [], {}, unreadable

    scopes: dict[tuple, tuple[set, set]] = {}
    demand_rows: dict[tuple, dict] = {}
    for row in rows:
        kind, rid = row.get("kind"), row.get("id")
        if rid is None or kind not in ("demand", "discharge"):
            continue
        scope = (row.get("session"), row.get("agent"))
        opened, closed = scopes.setdefault(scope, (set(), set()))
        if kind == "demand":
            opened.add(rid)
            demand_rows.setdefault((scope, rid), row)  # first row per id wins, as Keel does
        else:
            closed.add(rid)

    open_keys, discharged = [], 0
    for scope, (opened, closed) in scopes.items():
        for rid in opened - closed:
            open_keys.append((scope, rid))
        discharged += len(opened & closed)   # a discharge with no demand closes nothing
    demanded = sum(len(opened) for opened, _ in scopes.values())

    acted = [
        Activity(
            plugin="keel",
            kind="demand",
            ts=str(demand_rows[key].get("ts") or ""),
            session_id=str(demand_rows[key].get("session") or ""),
            tool_name=str(demand_rows[key].get("agent") or ""),
            subject=_describe_demand(demand_rows[key]),
        )
        for key in open_keys if key in demand_rows
    ]
    # CONSERVATION, asserted where it is computed rather than trusted downstream: every demand is
    # either still open or was discharged in its own scope. A count that does not sum is the
    # denominator defect this bench exists to catch, so it is reported, never silently balanced.
    counts = {"demanded": demanded, "discharged": discharged, "open": len(open_keys)}
    counts["balanced"] = demanded == discharged + len(open_keys)
    return acted, counts, None


def read_makoto(root: pathlib.Path) -> tuple[list[Activity], bool, str | None]:
    """(what Makoto did, whether it proved it ran, why it could not be read).

    CORRECTION. This function previously returned an empty activity list and the note "makoto
    records events seen, not verdicts reached ... NOT OBSERVABLE", having consulted only the
    `events` table of makoto.record.db. That was wrong, and wrong in this repository's own worst
    way: it reported a verdict about a subject it had never read.

    Makoto writes `makoto_state/audit.jsonl`, one chain-appended row per Finding-producing
    dispatch, carrying `pattern_fires` (which checks fired), `exit_code` (2 blocking, 0 not) and
    the full findings. Driven for real -- one corpus session through `python -m makoto.dispatch`
    -- it produced exactly one row:

        {"event": "live.pre_tool_use", "pattern_fires": ["content.verifier_exit_masking"],
         "exit_code": 2, "tool_name": "Bash"}

    That is a verdict journal, and a richer one than the siblings': it names the rule AND the
    exit code, where `decisions.jsonl` gives the denial alone. It follows the same only-fires
    policy for the same measured reason (recording silent fires flooded the log to 99%+ noise),
    so an ABSENT file means nothing fired -- exactly as an empty `decisions.jsonl` does. It is
    not evidence of blindness, which is what the old note mistook it for.

    Liveness therefore still comes from the record db, which is written on every event: the
    audit log alone cannot distinguish "ran and stayed silent" from "never ran".
    """
    record = root / "makoto_state" / "makoto.record.db"
    live = False
    if record.is_file():
        try:
            connection = sqlite3.connect(f"file:{record}?mode=ro", uri=True)
            try:
                live = bool(connection.execute("select count(*) from events").fetchone()[0])
            finally:
                connection.close()
        except sqlite3.Error:
            live = False

    rows, unreadable = _journal_rows(root / "makoto_state" / "audit.jsonl")
    if unreadable and not record.is_file():
        return [], False, unreadable

    acted = []
    for row in rows:
        findings = row.get("findings")
        findings = findings if isinstance(findings, list) else []
        fires = row.get("pattern_fires")
        fires = [str(f) for f in fires] if isinstance(fires, list) else []
        # exit_code 2 is Makoto blocking; a finding that did not block is still something it
        # DID, and is reported as a fault rather than folded into the silent majority.
        kind = "block" if row.get("exit_code") == 2 else "fault"
        acted.append(Activity(
            plugin="makoto",
            kind=kind,
            ts=str(row.get("ts") or ""),
            session_id=str(row.get("session_id") or ""),
            tool_name=str(row.get("tool_name") or ""),
            subject=_describe_makoto(findings, fires),
        ))
    return acted, live or bool(rows), None


def _describe_makoto(findings: list, fires: list) -> str:
    """Makoto's own words for what it caught, never a sentence invented here."""
    for finding in findings:
        if isinstance(finding, dict):
            message = finding.get("message")
            if isinstance(message, str) and message.strip():
                return " ".join(message.split())
    return ", ".join(fires) if fires else "a finding with no message"



ENGINES = ("ward", "keel", "makoto")


def engine_activity(name: str, root: pathlib.Path) -> tuple[list[Activity], bool, str | None, dict]:
    """The ONE place that answers "what did this engine do". Called by `survey` and by `unseen`.

    Those two used to each assemble it themselves, which was survivable only while every engine
    had exactly one record. The moment Keel gained a second, a demand counted by the page would
    have been invisible to the cursor -- the mode would print an obligation once and then, on the
    next look, offer it again as fresh, because the two readers disagreed about what had been
    shown. One question, one answer, one function.
    """
    if name == "makoto":
        acted, live, note = read_makoto(root)
        return acted, live, note, {}
    acted, live, note = read_journal(name, root)
    ledger: dict = {}
    if name == "keel":
        # KEEL'S SECOND RECORD. Its positive half writes `obligations.jsonl`, never
        # `decisions.jsonl`, and each record is separately evaluable: an unreadable ledger beside
        # a readable decisions file is NOT a clean engine. Folding both into one note would
        # recreate, one level up, the single-record blindness this lane exists to remove.
        demands, ledger, ledger_note = read_ledger(root)
        acted = acted + demands
        note = "; ".join(n for n in (note, ledger_note) if n) or None
    return acted, live, note, ledger


def survey(root: pathlib.Path | None = None) -> dict:
    """What every judge on the bench has done, with each engine's observability stated.

    `evaluated` counts ENGINES INSPECTED, not activity found, so a bench where nothing happened
    still has a real denominator. An engine whose record could not be read is `not_evaluable` --
    it is never folded into the quiet majority.
    """
    root = root or state_root()
    engines, findings, not_evaluable = {}, [], 0
    for name in ENGINES:
        acted, live, note, ledger = engine_activity(name, root)
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
            "ledger": ledger,
        }
        if blind:
            findings.append({"kind": "unobservable", "subject": name, "detail": note})
    # `fired` KEEPS ITS MEANING: refusals only. An open obligation and a discharged one are
    # different states, and a demand is not a denial -- folding them into one total would make a
    # single number move for two causes needing opposite responses, so the lane is reported
    # beside it and never inside it.
    total = sum(
        sum(1 for row in engine["acted"] if row["kind"] in POSITIVE_KINDS)
        for engine in engines.values()
    )
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
    # REFUSALS AND DEMANDS ARE COUNTED APART. `acted` now carries both, and "3 fired" for an
    # engine that denied nothing and demanded three times would be the one-number conflation this
    # lane was added to remove -- a phrase moving for two causes that need opposite responses.
    fired = sum(1 for row in engine["acted"] if row["kind"] in POSITIVE_KINDS)
    ledger = engine.get("ledger") or {}
    parts = [f"{fired} fired"] if fired else []
    if ledger.get("demanded"):
        parts.append(f"{ledger['demanded']} demanded, {ledger['discharged']} discharged, "
                     f"{ledger['open']} open")
    if not parts:
        return "ran, nothing fired"
    return "; ".join(parts)


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
    ledger = report["engines"]["keel"].get("ledger") or {}
    lines += ["", f"DENOMINATOR subject=bench engines={report['evaluated']} "
                  f"observable={report['passed']} not-observable={report['not_evaluable']} "
                  f"fired={report['fired']} "
                  f"demanded={ledger.get('demanded', 0)} "
                  f"discharged={ledger.get('discharged', 0)} "
                  f"open={ledger.get('open', 0)}"]
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
            acted = engine_activity(name, root)[0]
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

    def check(name: str, ok, detail="") -> None:
        """One cell. `ok` and `detail` may be callables, and then they are evaluated HERE.

        PER-CELL ISOLATION, and it is not decorative. A cell that indexes a structure a planted
        defect leaves empty used to raise, and the raise took the whole self-test down at that
        line -- so eleven later cells, including the four that bind the README's own promise,
        never ran at all and their silence read as "not failing". A plant is supposed to redden
        cells, not delete them. One cell's error must never suppress another cell's verdict, so
        an exception is that cell's FAIL and nothing else's.
        """
        nonlocal passed, failed
        if callable(ok):
            try:
                ok = ok()
            except Exception as exc:  # noqa: BLE001 -- the cell's own failure, isolated to it
                ok, detail = False, f"cell raised: {exc!r}"
        if callable(detail):
            try:
                detail = detail()
            except Exception as exc:  # noqa: BLE001
                detail = f"detail raised: {exc!r}"
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
        # NON-VACUITY: the record alone proves it RAN. Liveness must not depend on a finding,
        # or "ran and stayed silent" would be indistinguishable from "never ran".
        check("makoto proves liveness from its record with no finding present",
              live and acted == [] and note is None, f"live={live} acted={acted} note={note}")

        # PLANT a real audit row, in the shape the dispatcher actually writes. This cell exists
        # because the previous version of this file reported makoto NOT OBSERVABLE without ever
        # reading audit.jsonl -- a verdict about a subject it had not consulted, which is the
        # defect this whole bench is built to catch.
        (makoto / "audit.jsonl").write_text(json.dumps({
            "ts": "2026-08-31T04:36:00Z", "event": "live.pre_tool_use", "hook_kind": "PreToolUse",
            "session_id": "em", "tool_name": "Bash", "exit_code": 2,
            "pattern_fires": ["content.verifier_exit_masking"],
            "findings": [{"pattern_id": "content.verifier_exit_masking", "level": "error",
                          "message": "verifier exit-code masking (|| true)"}],
        }) + "\n", encoding="utf-8")
        acted, live, note = read_makoto(root)
        check("PLANT a makoto block is read from audit.jsonl and named",
              len(acted) == 1 and acted[0].kind == "block"
              and "exit-code masking" in acted[0].subject,
              f"acted={acted}")
        check("and it reaches the rendered page in makoto's own words",
              "exit-code masking" in render(survey(root)))
        # A finding that did NOT block is still something makoto did, and is not folded into
        # the silent majority.
        (makoto / "audit.jsonl").write_text(json.dumps({
            "ts": "2026-08-31T04:37:00Z", "event": "live.stop", "hook_kind": "Stop",
            "session_id": "em", "tool_name": "", "exit_code": 0,
            "pattern_fires": ["content.hollow_test"],
            "findings": [{"pattern_id": "content.hollow_test", "level": "warn",
                          "message": "a test that asserts nothing"}],
        }) + "\n", encoding="utf-8")
        check("a non-blocking makoto finding is reported as a fault, not as silence",
              [a.kind for a in read_makoto(root)[0]] == ["fault"])
        (makoto / "audit.jsonl").unlink()
        check("and an absent audit log is silence, not blindness -- the only-fires policy",
              read_makoto(root) == ([], True, None) or read_makoto(root)[1])

        # ------------------------------------------------------------------------------------
        # KEEL'S POSITIVE HALF. Every cell below plants rows in the exact shape
        # `keel/ledger.py` appends: kind demand/discharge, scoped by (session, agent), keyed by
        # id. If Keel changes that shape these fail, which is the point -- this reader
        # re-derives a rule Keel owns and cannot import, so the pin is the only thing holding
        # the two spellings together.
        def ledger(root: pathlib.Path, *rows: dict) -> None:
            path = root / "keel_state"
            path.mkdir(parents=True, exist_ok=True)
            with (path / LEDGER_FILE).open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")

        def demand(rid, session="s", agent="a", **extra):
            return {"kind": "demand", "id": rid, "session": session, "agent": agent,
                    "clause_id": "T02", "subject": "origin/main",
                    "reason": "a push must be observed landing", **extra}

        def discharge(rid, session="s", agent="a"):
            return {"kind": "discharge", "id": rid, "session": session, "agent": agent,
                    "how": "git ls-remote"}

        # NON-VACUITY FIRST, as everywhere else in this file.
        ledger(root, demand("d1"))
        acted, counts, note = read_ledger(root)
        check("a planted demand is read back as an open obligation",
              len(acted) == 1 and acted[0].kind == "demand" and note is None
              and counts["demanded"] == 1 and counts["open"] == 1,
              f"{acted} {counts} note={note}")
        check("the demand is described in KEEL's words, not this module's",
              "must be observed landing" in acted[0].subject, acted[0].subject)

        ledger(root, demand("d1"), discharge("d1"), demand("d2"))
        acted, counts, _ = read_ledger(root)
        check("PLANT a discharge closes its own demand and only that one",
              counts == {"demanded": 2, "discharged": 1, "open": 1, "balanced": True}
              and [a.subject for a in acted] and len(acted) == 1, str(counts))

        # SCOPE. Keel subtracts discharges only within one (session, agent); a discharge from a
        # different run closing a demand would report an act resolved on another run's evidence.
        ledger(root, demand("d1", session="s1"), discharge("d1", session="s2"))
        _, counts, _ = read_ledger(root)
        check("PLANT a discharge from another SESSION does not close the demand",
              counts["open"] == 1 and counts["discharged"] == 0, str(counts))
        ledger(root, demand("d1", agent="a1"), discharge("d1", agent="a2"))
        _, counts, _ = read_ledger(root)
        check("PLANT a discharge from another AGENT does not close the demand",
              counts["open"] == 1 and counts["discharged"] == 0, str(counts))

        # A discharge with no demand licenses nothing and must not make the counts lie.
        ledger(root, discharge("ghost"))
        _, counts, _ = read_ledger(root)
        check("PLANT a discharge with no demand closes nothing and stays balanced",
              counts == {"demanded": 0, "discharged": 0, "open": 0, "balanced": True}, str(counts))

        # THE CELL THIS WHOLE LANE EXISTS FOR. Before it, this bench read Keel's refusals only,
        # so an engine that demanded and never denied printed "ran, nothing fired" -- silence
        # reported as a fact about an engine that had been working.
        write(root, "keel", dict(session, plugin="keel"))
        ledger(root, demand("d1"), demand("d2"), discharge("d2"))
        report = survey(root)
        state = engine_state(report["engines"]["keel"])
        check("PLANT keel demanding and never denying is NOT 'ran, nothing fired'",
              state != "ran, nothing fired" and "1 open" in state, state)
        check("and the obligation reaches the rendered page in keel's words",
              "must be observed landing" in render(report), state)
        keel_refusals = sum(1 for row in report["engines"]["keel"]["acted"]
                            if row["kind"] in POSITIVE_KINDS)
        check("demands do NOT inflate `fired`, which still counts refusals only",
              lambda: keel_refusals == 0 and report["engines"]["keel"]["ledger"]["open"] == 1,
              lambda: f"refusals={keel_refusals} ledger={report['engines']['keel']['ledger']}")

        # ABSENCE IS SILENCE; UNREADABLE IS A STATED REASON. The ledger is written only when a
        # demand is raised, so a missing file means nothing was demanded -- the same only-fires
        # policy audit.jsonl follows. A file that exists and cannot be read is never silence.
        (root / "keel_state" / LEDGER_FILE).unlink()
        report = survey(root)
        check("an absent ledger beside a live keel is silence, not blindness",
              lambda: report["engines"]["keel"]["observable"]
              and report["engines"]["keel"]["ledger"]["demanded"] == 0,
              lambda: str(report["engines"]["keel"]))
        unreadable = root / "keel_state" / LEDGER_FILE
        unreadable.mkdir()          # a directory where the journal should be: exists, unreadable
        report = survey(root)
        check("PLANT an unreadable ledger is NOT-EVALUABLE, never a clean keel",
              not report["engines"]["keel"]["observable"]
              and report["verdict"] == "NOT-EVALUABLE", str(report["engines"]["keel"]["note"]))
        unreadable.rmdir()

        # ONE OWNER. `survey` and `unseen` must agree about what keel did, or the mode offers an
        # obligation as fresh after having already shown it.
        ledger(root, demand("d1"))
        set_mode(True, root)
        unseen(root)
        ledger(root, demand("d1"), demand("d3"))
        fresh = unseen(root)
        check("PLANT a new obligation is shown once, by the same reader the page uses",
              len(fresh) == 1 and fresh[0].kind == "demand", str(fresh))
        check("and it is not offered again on the next look", unseen(root) == [])
        set_mode(False, root)
        (root / "keel_state" / LEDGER_FILE).unlink()
        import shutil
        shutil.rmtree(root / "keel_state")

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

    # ------------------------------------------------------------------------------------
    # THE README'S CLAIM, BOUND TO A CHECK THAT CAN FAIL. `README.md` publishes "every time a
    # judge actually fires, you see it." That sentence was true of Ward and Makoto and false of
    # Keel for as long as this module read one of Keel's two records, and nothing anywhere would
    # have gone red about it. The declaration below is the list of records this bench claims to
    # read; each one gets a planted positive and must reach the rendered page. Teaching an engine
    # a new record without teaching this reader now means editing this list, in the open.
    READ_RECORDS = {
        ("ward", "decisions.jsonl"): "cert verification disabled",
        ("keel", "decisions.jsonl"): "cert verification disabled",
        ("keel", "obligations.jsonl"): "must be observed landing",
        ("makoto", "audit.jsonl"): "exit-code masking",
    }
    with tempfile.TemporaryDirectory(prefix="courthouse-claim-") as name:
        for (engine, record), expected in READ_RECORDS.items():
            root = pathlib.Path(name) / f"{engine}-{record}"
            state = root / f"{engine}_state"
            state.mkdir(parents=True, exist_ok=True)
            if record == "decisions.jsonl":
                rows = [dict(session, plugin=engine), dict(deny, plugin=engine)]
            elif record == "obligations.jsonl":
                rows = [{"kind": "demand", "id": "d1", "session": "s", "agent": "a",
                         "clause_id": "T02", "subject": "origin/main",
                         "reason": "a push must be observed landing"}]
                (state / "decisions.jsonl").write_text(
                    json.dumps(dict(session, plugin=engine)) + "\n", encoding="utf-8")
            else:
                rows = [{"ts": "T1", "session_id": "s", "tool_name": "Bash", "exit_code": 2,
                         "pattern_fires": ["content.verifier_exit_masking"],
                         "findings": [{"message": "verifier exit-code masking (|| true)"}]}]
            (state / record).write_text(
                "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            check(f"a fire in {engine}/{record} reaches the page the README promises",
                  expected in render(survey(root)), render(survey(root)))

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
