#!/usr/bin/env python3
"""Join every number published in repository READMEs to its measurement.

Named residue, so the gap is an absence somebody chose rather than one nobody noticed:

Not all evidence is a command. Courthouse's own README asserted that hook stderr on exit 0 reaches
only the debug log -- a claim about Claude Code's hook contract, which no command in this
repository can recompute. The first ledger written here answered that by pointing the anchor at
`python3 eval/validate.py; echo $?`, which resolves, agrees, and measures something else entirely.
A checker that demands a command for every claim teaches authors to invent one, and an invented
command is worse than a missing anchor because it passes. `MEASURED.tsv` needs a second evidence
shape -- a citation, dated and named -- before claims of that kind can be anchored honestly.
Until it has one, such claims are reworded to drop the number rather than given a false command.

A resolving anchor is not yet a relevant one. This unit checks that a claim's number equals its
ledger row's value; nothing here checks that the row measures the thing the sentence is about.
Both defects above were caught by reading, which is exactly the method this estate distrusts.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import pathlib
import re
import sys
from collections import Counter

from outcomes import CheckResult, Outcome, VERDICTS, cli, exit_code


HEADER = ("CLASS", "SURFACE", "LINE", "KIND-OR-RULE", "NUMERATOR",
          "DENOMINATOR", "ANCHOR", "FINDING", "TEXT")
EXCLUSION_RULES = ("generated-block", "source-fence", "footnote-definition", "url",
                   "date", "version", "identifier", "ordered-list-marker")
FINDING_TYPES = ("UNANCHORED", "UNRESOLVED", "MISMATCH", "ORPHAN",
                 "DUPLICATE-KEY", "EMPTY-COMMAND", "TIER-ABSENT",
                 "TIER-UNDECLARED", "EFFICACY-UNDECLARED", "FOREIGN-EVIDENCE",
                 "RECORD-SELLS-INSTALL")
NUMBER = r"\d+(?:[.,]\d+)*%?"
NUMBER_RE = re.compile(NUMBER)
RATIO_RE = re.compile(rf"(?<![\w.-])({NUMBER})(?:\s*/\s*|\s+(?:of|out\s+of)\s+)({NUMBER})(?!\w)", re.I)
ANCHOR_RE = re.compile(r"\[\^m-([a-z0-9][a-z0-9-]*)\]", re.I)
FOOTNOTE_DEFINITION_RE = re.compile(r"^\s*\[\^[^\]]+\]:")
URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s)>]+")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
VERSION_RE = re.compile(r"(?<![A-Za-z0-9_.])v?\d+\.\d+(?:\.\d+)*(?![A-Za-z0-9_.%-])", re.I)
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*([^\s`]*)")
SOURCE_LANGUAGES = {"python", "json", "yaml", "bash", "sh", "diff", "js", "ts"}
WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "dozen": 12, "hundred": 100,
}
IRREGULAR_PLURALS = {"people", "men", "women", "children", "teeth", "feet", "mice", "geese", "data", "criteria", "analyses", "indices"}
WORD_RE = re.compile(r"\b(" + "|".join(WORDS) + r")\s+([A-Za-z][A-Za-z'-]*)", re.I)


@dataclasses.dataclass
class Row:
    klass: str
    surface: str
    line: int | str
    kind: str
    numerator: str
    denominator: str = "-"
    anchor: str = "-"
    finding: str = "-"
    text: str = "-"
    start: int = -1
    end: int = -1

    def fields(self) -> tuple[str, ...]:
        values = (self.klass, self.surface, str(self.line), self.kind, self.numerator,
                  self.denominator, self.anchor, self.finding, self.text)
        return tuple(value if value != "" else "-" for value in values)


@dataclasses.dataclass
class LedgerRow:
    key: str
    value: str
    denominator: str
    command: str
    subject: str
    line: int
    text: str


@dataclasses.dataclass
class TierRow:
    repo: str
    tier: str
    declaration: str
    line: int
    text: str


@dataclasses.dataclass
class Report:
    rows: list[Row] = dataclasses.field(default_factory=list)
    results: list[CheckResult] = dataclasses.field(default_factory=list)
    informational: list[str] = dataclasses.field(default_factory=list)


def _covered(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < other_end and end > other_start for other_start, other_end in spans)


def _plural(noun: str) -> bool:
    folded = noun.casefold()
    return folded in IRREGULAR_PLURALS or (folded.endswith("s") and not folded.endswith("ss"))


def _identifier(line: str, start: int) -> bool:
    if start and line[start - 1].isalpha():
        return True
    return (start >= 2 and line[start - 1] in "-_" and line[start - 2].isalpha())


def _exclusion(line: str, start: int, end: int, *, generated: bool,
               source_fence: bool) -> str | None:
    if generated:
        return "generated-block"
    if source_fence:
        return "source-fence"
    if FOOTNOTE_DEFINITION_RE.match(line):
        return "footnote-definition"
    if any(start >= match.start() and end <= match.end() for match in URL_RE.finditer(line)):
        return "url"
    if any(start >= match.start() and end <= match.end() for match in DATE_RE.finditer(line)):
        return "date"
    if any(start >= match.start() and end <= match.end() for match in VERSION_RE.finditer(line)):
        return "version"
    if _identifier(line, start):
        return "identifier"
    marker = re.match(r"^\s*\d+\.\s", line)
    if marker and start >= marker.start() and end <= marker.end():
        return "ordered-list-marker"
    return None


def scan_text(text: str, surface: str) -> list[Row]:
    rows: list[Row] = []
    generated = False
    fence_marker: str | None = None
    source_fence = False
    for line_number, line in enumerate(text.splitlines(), 1):
        if "<!-- BEGIN GENERATED" in line:
            generated = True

        fence = FENCE_RE.match(line)
        was_in_fence = fence_marker is not None
        closes_fence = False
        line_source_fence = source_fence
        if fence:
            marker, info = fence.groups()
            if not was_in_fence:
                fence_marker = marker[0]
                source_fence = info.casefold() in SOURCE_LANGUAGES
                line_source_fence = source_fence
            elif marker[0] == fence_marker and not info:
                line_source_fence = source_fence
                closes_fence = True

        consumed: list[tuple[int, int]] = []
        line_rows: list[Row] = []
        for match in RATIO_RE.finditer(line):
            rule = _exclusion(line, match.start(), match.end(), generated=generated,
                              source_fence=line_source_fence)
            if rule:
                for group in (1, 2):
                    start, end = match.span(group)
                    line_rows.append(Row("EXCLUDED", surface, line_number, rule,
                                         match.group(group), text=line, start=start, end=end))
            else:
                line_rows.append(Row("CLAIM", surface, line_number, "ratio", match.group(1),
                                     match.group(2), text=line, start=match.start(), end=match.end()))
            consumed.append(match.span())

        for match in NUMBER_RE.finditer(line):
            if _covered(match.start(), match.end(), consumed):
                continue
            rule = _exclusion(line, match.start(), match.end(), generated=generated,
                              source_fence=line_source_fence)
            if rule:
                line_rows.append(Row("EXCLUDED", surface, line_number, rule, match.group(),
                                     text=line, start=match.start(), end=match.end()))
            else:
                line_rows.append(Row("CLAIM", surface, line_number, "bare", match.group(),
                                     text=line, start=match.start(), end=match.end()))

        for match in WORD_RE.finditer(line):
            if _plural(match.group(2)):
                rule = _exclusion(line, match.start(), match.end(), generated=generated,
                                  source_fence=line_source_fence)
                if rule:
                    line_rows.append(Row("EXCLUDED", surface, line_number, rule,
                                         match.group(1), text=line, start=match.start(),
                                         end=match.end()))
                else:
                    line_rows.append(Row("CLAIM", surface, line_number, "word-cardinal",
                                         str(WORDS[match.group(1).casefold()]), text=line,
                                         start=match.start(), end=match.end()))

        claims = sorted((row for row in line_rows if row.klass == "CLAIM"), key=lambda row: row.start)
        anchors = list(ANCHOR_RE.finditer(line))
        for index, claim in enumerate(claims):
            window_end = claims[index + 1].start if index + 1 < len(claims) else len(line)
            anchor = next((match for match in anchors
                           if claim.end <= match.start() < window_end), None)
            if anchor:
                claim.anchor = anchor.group(1).casefold()
        rows.extend(sorted(line_rows, key=lambda row: (row.start, row.klass)))

        if closes_fence:
            fence_marker = None
            source_fence = False
        if "<!-- END GENERATED" in line:
            generated = False
    return rows


def read_ledger(path: pathlib.Path) -> tuple[list[LedgerRow] | None, str | None]:
    if not path.exists():
        return [], None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return None, str(exc)
    meaningful = [(number, line) for number, line in enumerate(lines, 1)
                  if line.strip() and not line.lstrip().startswith("#")]
    if not meaningful:
        return None, "missing header"
    try:
        parsed_header = next(csv.reader([meaningful[0][1]], delimiter="\t"))
    except csv.Error as exc:
        return None, str(exc)
    if parsed_header != ["KEY", "VALUE", "DENOMINATOR", "COMMAND", "SUBJECT"]:
        return None, "header must be KEY, VALUE, DENOMINATOR, COMMAND, SUBJECT"
    rows: list[LedgerRow] = []
    for line_number, line in meaningful[1:]:
        try:
            fields = next(csv.reader([line], delimiter="\t"))
        except csv.Error as exc:
            return None, f"line {line_number}: {exc}"
        if len(fields) != 5 or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", fields[0]):
            return None, f"line {line_number}: expected five fields and a valid KEY"
        rows.append(LedgerRow(*fields, line_number, line))
    return rows, None


def read_tiers(path: pathlib.Path) -> tuple[list[TierRow] | None, str | None]:
    if not path.exists():
        return None, "file does not exist"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return None, str(exc)
    meaningful = [(number, line) for number, line in enumerate(lines, 1)
                  if line.strip() and not line.lstrip().startswith("#")]
    if not meaningful:
        return None, "missing rows"
    rows: list[TierRow] = []
    seen: set[str] = set()
    for line_number, line in meaningful:
        try:
            fields = next(csv.reader([line], delimiter="\t"))
        except csv.Error as exc:
            return None, f"line {line_number}: {exc}"
        if (len(fields) != 3 or not fields[0] or fields[1] not in {"SHIPPED", "BENCH", "RECORD"}
                or not fields[2]):
            return None, f"line {line_number}: expected REPO, a valid TIER, and LINE"
        key = fields[0].casefold()
        if key in seen:
            return None, f"line {line_number}: duplicate REPO"
        seen.add(key)
        rows.append(TierRow(*fields, line_number, line))
    return rows, None


def _tier_for(repository: pathlib.Path, tiers: list[TierRow]) -> TierRow | None:
    # REPO names are matched case-insensitively because the checked-out directory names use
    # lowercase for Ward and Makoto. Keel is the one declared checkout alias in TIERS.tsv.
    names = {repository.name.casefold()}
    if repository.name.casefold() == "gyroscope":
        names.add("keel")
    return next((row for row in tiers if row.repo.casefold() in names), None)


def _tier_finding(report: Report, surface: str, line: int, tier: str,
                  finding: str, text: str) -> None:
    report.rows.append(Row("TIER", surface, line, tier, "-", finding=finding, text=text))
    report.results.append(CheckResult(Outcome.FAIL, finding))


def inspect_repository(repository: pathlib.Path, tiers: list[TierRow] | None = None,
                       tiers_path: pathlib.Path | None = None) -> Report:
    report = Report()
    readme = repository / "README.md"
    surface = str(readme)
    if not readme.exists():
        report.informational.append(f"INFO\t{repository}: no root README.md")
        return report
    try:
        text = readme.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        report.informational.append(f"NOT-EVALUABLE\t{surface}: {exc}")
        report.results.append(CheckResult(Outcome.NOT_EVALUABLE, surface))
        return report
    report.rows.extend(scan_text(text, surface))

    ledger_path = repository / "MEASURED.tsv"
    ledger, error = read_ledger(ledger_path)
    if error is not None:
        report.informational.append(f"NOT-EVALUABLE\t{ledger_path}: {error}")
        report.results.append(CheckResult(Outcome.NOT_EVALUABLE, str(ledger_path)))
        return report
    assert ledger is not None
    by_key: dict[str, list[LedgerRow]] = {}
    for entry in ledger:
        by_key.setdefault(entry.key, []).append(entry)

    cited: set[str] = set()
    for claim in (row for row in report.rows if row.klass == "CLAIM"):
        if claim.anchor == "-":
            claim.finding = "UNANCHORED"
        elif claim.anchor not in by_key:
            claim.finding = "UNRESOLVED"
        else:
            cited.add(claim.anchor)
            entry = by_key[claim.anchor][0]
            if entry.value != claim.numerator or entry.denominator != claim.denominator:
                claim.finding = "MISMATCH"
        if claim.finding != "-":
            report.results.append(CheckResult(Outcome.FAIL, claim.finding))

    for entry in ledger:
        findings: list[str] = []
        if len(by_key[entry.key]) > 1:
            findings.append("DUPLICATE-KEY")
        if not entry.command.strip():
            findings.append("EMPTY-COMMAND")
        if entry.key not in cited:
            findings.append("ORPHAN")
        for finding in findings:
            report.rows.append(Row("LEDGER", str(ledger_path), entry.line, "row", entry.value,
                                   entry.denominator, entry.key, finding, entry.text))
            report.results.append(CheckResult(Outcome.FAIL, finding))

    if tiers is not None:
        tier_path = tiers_path or pathlib.Path(__file__).with_name("TIERS.tsv")
        declaration = _tier_for(repository, tiers)
        if declaration is None:
            _tier_finding(report, str(tier_path), 1, "-", "TIER-UNDECLARED",
                          f"{repository.name}: no declaration")
            return report
        if declaration.declaration not in text:
            _tier_finding(report, surface, 1, declaration.tier, "TIER-ABSENT",
                          declaration.declaration)
        if (declaration.tier == "SHIPPED" and
                "its effect on a live session's outcome is unmeasured" not in text):
            _tier_finding(report, surface, 1, declaration.tier, "EFFICACY-UNDECLARED",
                          "its effect on a live session's outcome is unmeasured")
        for entry in ledger:
            if "../" in entry.command.replace("\\", "/"):
                # The surface is the ledger, not the README. entry.line indexes MEASURED.tsv, so
                # naming the README here sent a reader to whatever text happened to occupy that
                # line number in a different file -- a finding nobody could act on.
                _tier_finding(report, str(ledger_path), entry.line, declaration.tier,
                              "FOREIGN-EVIDENCE", entry.command)
        if declaration.tier == "RECORD":
            for line_number, line in enumerate(text.splitlines(), 1):
                if "claude plugin install" in line:
                    _tier_finding(report, surface, line_number, declaration.tier,
                                  "RECORD-SELLS-INSTALL", line)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    targets = parser.add_mutually_exclusive_group(required=True)
    targets.add_argument("--repo", type=pathlib.Path)
    targets.add_argument("--estate", type=pathlib.Path)
    parser.add_argument("--claims-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.repo is not None:
        repositories = [arguments.repo.resolve()]
    else:
        estate = arguments.estate.resolve()
        repositories = sorted((path for path in estate.iterdir() if path.is_dir() and
                               (path / ".git").exists()), key=lambda path: path.name.casefold())

    tiers_path = pathlib.Path(__file__).with_name("TIERS.tsv")
    tiers, tiers_error = read_tiers(tiers_path)
    combined = Report()
    if tiers_error is not None:
        combined.informational.append(f"NOT-EVALUABLE\t{tiers_path}: {tiers_error}")
        combined.results.append(CheckResult(Outcome.NOT_EVALUABLE, str(tiers_path)))
    for repository in repositories:
        report = inspect_repository(repository, tiers, tiers_path)
        combined.rows.extend(report.rows)
        combined.results.extend(report.results)
        combined.informational.extend(report.informational)
    for message in combined.informational:
        print(message, file=sys.stderr)

    print("\t".join(HEADER))
    visible = [row for row in combined.rows if not arguments.claims_only or row.klass != "EXCLUDED"]
    for row in visible:
        print("\t".join(row.fields()))

    claims = sum(row.klass == "CLAIM" for row in combined.rows)
    finding_counts = Counter(row.finding for row in combined.rows if row.finding in FINDING_TYPES)
    exclusion_counts = Counter(row.kind for row in combined.rows if row.klass == "EXCLUDED")
    not_evaluable = sum(result.outcome is Outcome.NOT_EVALUABLE for result in combined.results)
    parts = [f"claims={claims}"]
    parts.extend(f"{finding}={finding_counts[finding]}" for finding in FINDING_TYPES)
    parts.extend(f"{rule}={exclusion_counts[rule]}" for rule in EXCLUSION_RULES)
    parts.append(f"not-evaluable={not_evaluable}")
    print("SUMMARY\t" + "\t".join(parts))
    status = exit_code(combined.results)
    print(VERDICTS[status])
    return status


if __name__ == "__main__":
    sys.exit(cli(main))
