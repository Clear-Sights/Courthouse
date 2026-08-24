"""Shared outcome and command-line contracts for Courthouse evaluators."""

from __future__ import annotations

import dataclasses
import enum
import traceback
from collections.abc import Callable


class Outcome(enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUABLE = "NOT-EVALUABLE"


@dataclasses.dataclass(frozen=True)
class CheckResult:
    outcome: Outcome
    message: str


EXIT_INTERNAL_ERROR = 3

VERDICTS = {
    0: "Validation passed: every check ran and passed.",
    1: "Validation failed: at least one check disagreed.",
    2: "Validation not evaluable: nothing disagreed, but at least one check could not be run.",
    EXIT_INTERNAL_ERROR: (
        "Validator error: the validator failed before it could rule, so the manifest is "
        "unchecked. The traceback above is the failure, not a finding about the manifest."
    ),
}


def exit_code(results: list[CheckResult]) -> int:
    if any(result.outcome is Outcome.FAIL for result in results):
        return 1
    if any(result.outcome is Outcome.NOT_EVALUABLE for result in results):
        return 2
    return 0


def cli(run: Callable[[], int]) -> int:
    """Give an evaluator crash a status distinct from a disagreeing check."""
    try:
        return run()
    except Exception:  # noqa: BLE001 -- the traceback is printed, never swallowed
        traceback.print_exc()
        print(VERDICTS[EXIT_INTERNAL_ERROR])
        return EXIT_INTERNAL_ERROR
