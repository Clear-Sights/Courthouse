#!/usr/bin/env python3
"""Mutation-calibrate ``claims.py`` without ever planting in a real checkout.

Every plant gets a private temporary estate containing a copy of Courthouse's README and
ledger.  Only that disposable estate is mutated; this program accepts no planting target and
therefore cannot point at a real checkout.  The real evaluator and its real TIERS.tsv are used.
"""

from __future__ import annotations

import dataclasses
import pathlib
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence

from outcomes import CheckResult, Outcome, VERDICTS, cli, exit_code


ROOT = pathlib.Path(__file__).resolve().parent.parent
CLAIMS = pathlib.Path(__file__).resolve().with_name("claims.py")
TIERS = pathlib.Path(__file__).resolve().with_name("TIERS.tsv")
POLARITY_FIRES = "expect-fires"
POLARITY_SILENT = "expect-silent"
HEADER = ("CLASS", "ID", "POLARITY", "EXPECTED-FINDING", "EXPECTED-SURFACE",
          "OBSERVED", "REVERT", "OUTCOME", "DETAIL")


@dataclasses.dataclass(frozen=True)
class EngineRun:
    status: int
    findings: frozenset[tuple[str, str, str]]
    stdout: str = ""
    stderr: str = ""


Mutation = Callable[[pathlib.Path], Callable[[], None]]


@dataclasses.dataclass(frozen=True)
class Plant:
    id: str
    mutate: Mutation
    polarity: str
    expected_finding: str | None = None
    expected_surface: str | None = None
    expected_status: int | None = None


@dataclasses.dataclass(frozen=True)
class PlantResult:
    plant: Plant
    outcome: Outcome
    observed: bool
    restored: bool
    detail: str


@dataclasses.dataclass(frozen=True)
class Residue:
    id: str
    join: str
    reason: str


RESIDUE = (
    Residue("K-1", "emission -> sink", "claims.py cannot observe Keel dispatcher delivery"),
    Residue("K-2", "one contract, two spellings", "claims.py cannot observe Keel's import contract"),
    Residue("S-1", "occasion -> surface", "claims.py cannot observe Swale trigger polarity"),
    Residue("M-1", "certification -> subject", "claims.py cannot observe Makoto cross-repo skips"),
    Residue("P-1", "mutation -> reversal", "claims.py cannot observe restoration after SIGKILL"),
)


def _rewrite(path: pathlib.Path, transform: Callable[[str], str]) -> Callable[[], None]:
    before = path.read_text(encoding="utf-8")
    after = transform(before)
    path.write_text(after, encoding="utf-8")

    def revert() -> None:
        path.write_text(before, encoding="utf-8")

    return revert


def _append(relative: str, text: str) -> Mutation:
    return lambda estate: _rewrite(estate / relative, lambda value: value + text)


def _replace(relative: str, old: str, new: str) -> Mutation:
    def mutate(estate: pathlib.Path) -> Callable[[], None]:
        def transform(value: str) -> str:
            if value.count(old) != 1:
                raise ValueError(f"expected exactly one occurrence of {old!r}")
            return value.replace(old, new, 1)
        return _rewrite(estate / relative, transform)
    return mutate


def _add_repository(name: str, readme: str, ledger: str | None = None) -> Mutation:
    def mutate(estate: pathlib.Path) -> Callable[[], None]:
        repository = estate / name
        repository.mkdir()
        (repository / ".git").mkdir()
        (repository / "README.md").write_text(readme, encoding="utf-8")
        if ledger is not None:
            (repository / "MEASURED.tsv").write_text(ledger, encoding="utf-8")

        def revert() -> None:
            shutil.rmtree(repository)

        return revert
    return mutate


LEDGER_HEADER = "KEY\tVALUE\tDENOMINATOR\tCOMMAND\tSUBJECT\n"
BENCH_LINE = "The bench: a plugin marketplace. It states only the facts it owns and links the rest."
SHIPPED_LINE = ("Shipped plugin — installable and versioned. The dispatcher is replay-tested "
                "against authored sessions; its effect on a live session's outcome is unmeasured.")


PLANTS = (
    Plant("unanchored", _append("courthouse/README.md", "\nCalibration observes 917 claims.\n"),
          POLARITY_FIRES, "UNANCHORED", "courthouse/README.md"),
    Plant("unresolved", _append("courthouse/README.md", "\nCalibration observes 918 claims[^m-no-such-key].\n"),
          POLARITY_FIRES, "UNRESOLVED", "courthouse/README.md"),
    Plant("mismatch", _replace("courthouse/MEASURED.tsv", "plugin-count\t3\t", "plugin-count\t4\t"),
          POLARITY_FIRES, "MISMATCH", "courthouse/README.md"),
    Plant("orphan", _append("courthouse/MEASURED.tsv", "calibration-orphan\t919\t-\tprobe\tcalibration\n"),
          POLARITY_FIRES, "ORPHAN", "courthouse/MEASURED.tsv"),
    Plant("duplicate-key", _append("courthouse/MEASURED.tsv", "plugin-count\t3\t-\tprobe\tduplicate\n"),
          POLARITY_FIRES, "DUPLICATE-KEY", "courthouse/MEASURED.tsv"),
    Plant("empty-command", lambda estate: _compound(
        _append("courthouse/MEASURED.tsv", "calibration-empty\t920\t-\t\tcalibration\n"),
        _append("courthouse/README.md", "\nCalibration observes 920 claims[^m-calibration-empty].\n"))(estate),
          POLARITY_FIRES, "EMPTY-COMMAND", "courthouse/MEASURED.tsv"),
    Plant("tier-absent", _replace("courthouse/README.md", BENCH_LINE, ""),
          POLARITY_FIRES, "TIER-ABSENT", "courthouse/README.md"),
    Plant("tier-paraphrase", _replace("courthouse/README.md", BENCH_LINE,
          "The marketplace bench states its own facts and links facts owned elsewhere."),
          POLARITY_FIRES, "TIER-ABSENT", "courthouse/README.md"),
    Plant("tier-undeclared", _add_repository("unlisted-repo", "No measured claims.\n", LEDGER_HEADER),
          POLARITY_FIRES, "TIER-UNDECLARED", str(TIERS)),
    Plant("foreign-evidence", _replace("courthouse/MEASURED.tsv", "python3 -c", "python3 ../ward/probe.py #"),
          POLARITY_FIRES, "FOREIGN-EVIDENCE", "courthouse/MEASURED.tsv"),
    Plant("record-sells-install", _add_repository("Swale", "claude plugin install swale\n", LEDGER_HEADER),
          POLARITY_FIRES, "RECORD-SELLS-INSTALL", "Swale/README.md"),
    Plant("efficacy-undeclared", _add_repository("Ward", "No measured claims.\n", LEDGER_HEADER),
          POLARITY_FIRES, "EFFICACY-UNDECLARED", "Ward/README.md"),
    Plant("efficacy-negative", _add_repository("Ward", SHIPPED_LINE + "\n", LEDGER_HEADER),
          POLARITY_SILENT, "EFFICACY-UNDECLARED", "Ward/README.md"),
    Plant("unparseable-ledger", _replace("courthouse/MEASURED.tsv", "KEY\tVALUE", "BROKEN\tVALUE"),
          POLARITY_SILENT, expected_status=2),
)


def _compound(*mutations: Mutation) -> Mutation:
    def mutate(estate: pathlib.Path) -> Callable[[], None]:
        reverts: list[Callable[[], None]] = []
        try:
            for operation in mutations:
                reverts.append(operation(estate))
        except Exception:
            for revert in reversed(reverts):
                revert()
            raise

        def revert() -> None:
            for operation in reversed(reverts):
                operation()
        return revert
    return mutate


def seed_estate(estate: pathlib.Path) -> None:
    repository = estate / "courthouse"
    repository.mkdir()
    (repository / ".git").mkdir()
    shutil.copyfile(ROOT / "README.md", repository / "README.md")
    shutil.copyfile(ROOT / "MEASURED.tsv", repository / "MEASURED.tsv")


def run_engine(estate: pathlib.Path) -> EngineRun:
    completed = subprocess.run(
        [sys.executable, str(CLAIMS), "--estate", str(estate)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    findings: set[tuple[str, str, str]] = set()
    lines = completed.stdout.splitlines()
    if lines and lines[0].split("\t")[:4] == ["CLASS", "SURFACE", "LINE", "KIND-OR-RULE"]:
        for line in lines[1:]:
            fields = line.split("\t")
            # Ledger TEXT is the original tab-separated row, so those output records contain
            # more than HEADER's nine fields.  The three fields used here precede that payload.
            if (len(fields) >= 9 and fields[0] in {"CLAIM", "LEDGER", "TIER"}
                    and fields[7] != "-"):
                findings.add((fields[7], fields[1], fields[2]))
    return EngineRun(completed.returncode, frozenset(findings), completed.stdout, completed.stderr)


def _surface(estate: pathlib.Path, declared: str | None) -> str | None:
    if declared is None:
        return None
    path = pathlib.Path(declared)
    return str(path if path.is_absolute() else estate / path)


def exercise(plant: Plant, engine: Callable[[pathlib.Path], EngineRun] = run_engine) -> PlantResult:
    with tempfile.TemporaryDirectory(prefix="courthouse-calibrate-") as temporary:
        estate = pathlib.Path(temporary)
        seed_estate(estate)
        try:
            baseline = engine(estate)
            if baseline.status not in (0, 1, 2):
                return PlantResult(plant, Outcome.NOT_EVALUABLE, False, False,
                                   f"baseline engine exited {baseline.status}")
            revert = plant.mutate(estate)
            planted = engine(estate)
            expected_surface = _surface(estate, plant.expected_surface)
            matching = {row for row in planted.findings - baseline.findings
                        if row[0] == plant.expected_finding and row[1] == expected_surface}
            if plant.expected_status is not None:
                observed = (planted.status == plant.expected_status and not planted.findings)
            elif plant.polarity == POLARITY_FIRES:
                observed = bool(matching)
            else:
                observed = not any(row[0] == plant.expected_finding and
                                   row[1] == expected_surface for row in planted.findings)
            revert()
            restored_run = engine(estate)
            restored = (restored_run.status == baseline.status and
                        restored_run.findings == baseline.findings)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return PlantResult(plant, Outcome.NOT_EVALUABLE, False, False, str(exc))
    outcome = Outcome.PASS if observed and restored else Outcome.FAIL
    details = []
    if not observed:
        details.append(f"declared observation absent (engine exit {planted.status})")
    if not restored:
        details.append("revert did not restore baseline findings and exit")
    return PlantResult(plant, outcome, observed, restored, "; ".join(details) or "declared behavior observed")


def run_battery(plants: Sequence[Plant] = PLANTS,
                engine: Callable[[pathlib.Path], EngineRun] = run_engine,
                residues: Sequence[Residue] = RESIDUE) -> tuple[int, list[PlantResult]]:
    results = [exercise(plant, engine) for plant in plants]
    checks = [CheckResult(result.outcome, result.plant.id) for result in results]
    return exit_code(checks), results


def _field(value: object | None) -> str:
    return "-" if value is None or value == "" else str(value).replace("\t", " ").replace("\n", " ")


def main() -> int:
    status, results = run_battery(PLANTS)
    print("\t".join(HEADER))
    for result in results:
        plant = result.plant
        print("\t".join(map(_field, ("PLANT", plant.id, plant.polarity, plant.expected_finding,
                                      plant.expected_surface, "yes" if result.observed else "no",
                                      "restored" if result.restored else "not-restored",
                                      result.outcome.value, result.detail))))
    for residue in RESIDUE:
        print("\t".join(map(_field, ("RESIDUE", residue.id, "-", "-", "-", "-", "-",
                                      "UNCOVERED", f"{residue.join}: {residue.reason}"))))
    covered = len(results)
    uncovered = len(RESIDUE)
    print("\t".join(map(_field, ("SUMMARY", "-", "-", "-", "-", "-", "-",
                                  VERDICTS[status],
                                  f"covered={covered} uncovered={uncovered} plants={covered}"))))
    return status


if __name__ == "__main__":
    sys.exit(cli(main))
