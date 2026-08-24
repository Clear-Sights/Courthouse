#!/usr/bin/env python3
"""Validate the Courthouse marketplace manifest using stdlib and git only.

Validation has three outcomes: PASS, FAIL, and NOT-EVALUABLE. A failed process
probe is NOT-EVALUABLE because it supplied no evidence about what it inspected.
"""

from __future__ import annotations

import contextlib
import dataclasses
import enum
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import traceback
from collections.abc import Callable, Iterator, Mapping
from typing import Any, ContextManager


ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = ROOT / ".claude-plugin" / "marketplace.json"

# Exhausting this bound means the remote pin was not evaluated.
LS_REMOTE_TIMEOUT_SECONDS = 120
# Exhausting this bound means the pinned repository tree was not evaluated.
CLONE_TIMEOUT_SECONDS = 300

VERSION_TOKEN = re.compile(r"\d+(?:\.\d+)*(?:[-+][0-9A-Za-z.-]+)?")
SHA = re.compile(r"[0-9a-f]{40}")


class Outcome(enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUABLE = "NOT-EVALUABLE"


@dataclasses.dataclass(frozen=True)
class CheckResult:
    outcome: Outcome
    message: str


@dataclasses.dataclass(frozen=True)
class ProbeResult:
    """The observable result of a process probe and, for clone, its tree."""

    returncode: int | None
    stdout: str | bytes | None = ""
    stderr: str | bytes | None = ""
    tree: pathlib.Path | None = None
    timed_out_after: float | None = None


RemoteProbe = Callable[[str, str], ProbeResult]
TreeProbe = Callable[[str, str], ContextManager[ProbeResult]]


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def stderr_tail(value: str | bytes | None, limit: int = 500) -> str:
    text = _as_text(value).strip()
    if not text:
        return "<empty>"
    return text[-limit:].replace("\n", " | ")


def _timeout_result(exc: subprocess.TimeoutExpired, fallback: float) -> ProbeResult:
    timeout = exc.timeout if exc.timeout is not None else fallback
    return ProbeResult(
        returncode=None,
        stdout=exc.stdout,
        stderr=exc.stderr,
        timed_out_after=timeout,
    )


def _probe_problem(name: str, operation: str, probe: ProbeResult) -> CheckResult:
    if probe.timed_out_after is not None:
        status = f"exit status unavailable (timed out after {probe.timed_out_after}s)"
    else:
        status = f"exit status {probe.returncode}"
    return CheckResult(
        Outcome.NOT_EVALUABLE,
        f"{name}: {operation} could not run successfully: {status}; "
        f"stderr tail: {stderr_tail(probe.stderr)}",
    )


def _result(ok: bool, message: str) -> CheckResult:
    return CheckResult(Outcome.PASS if ok else Outcome.FAIL, message)


def remote_url(source: Mapping[str, Any]) -> str | None:
    """Return the repository a consumer fetches, for each supported shape."""

    if source.get("source") == "github":
        repo = source.get("repo")
        return f"https://github.com/{repo}" if isinstance(repo, str) and repo else None
    url = source.get("url")
    return url if isinstance(url, str) and url else None


def normalize_repository(url: str) -> str:
    normalized = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", url.strip())
    normalized = normalized.rstrip("/")
    normalized = re.sub(r"\.git$", "", normalized, flags=re.IGNORECASE)
    return normalized.casefold()


def version_matches_ref(version: str, ref: str) -> bool:
    tokens = VERSION_TOKEN.findall(ref)
    return len(tokens) == 1 and tokens[0] == version


def _resolved_sha(stdout: str | bytes | None, ref: str) -> str | None:
    refs: dict[str, str] = {}
    for line in _as_text(stdout).splitlines():
        fields = line.split("\t", 1)
        if len(fields) == 2:
            refs[fields[1]] = fields[0]

    # Tags are tried first and peeled because an annotated tag's own object id
    # is not the commit id. refs/heads remains a cheap fallback because a future
    # release may use a release branch even though today's three pins are tags.
    return (
        refs.get(f"refs/tags/{ref}^{{}}")
        or refs.get(f"refs/tags/{ref}")
        or refs.get(f"refs/heads/{ref}")
    )


def _evaluate_remote_pin(
    name: str,
    url: str,
    ref: str,
    sha: str,
    probe_remote: RemoteProbe,
) -> CheckResult:
    try:
        probe = probe_remote(url, ref)
    except subprocess.TimeoutExpired as exc:
        probe = _timeout_result(exc, LS_REMOTE_TIMEOUT_SECONDS)

    if probe.returncode != 0:
        return _probe_problem(name, "git ls-remote probe", probe)

    resolved = _resolved_sha(probe.stdout, ref)
    return _result(
        resolved == sha,
        f"{name}: {ref} on remote resolves to pinned sha (got {resolved})",
    )


def _evaluate_tree(
    plugin: Mapping[str, Any],
    name: str,
    source: Mapping[str, Any],
    url: str,
    ref: str,
    probe_tree: TreeProbe,
) -> list[CheckResult]:
    try:
        manager = probe_tree(url, ref)
        with manager as probe:
            if probe.returncode != 0:
                return [_probe_problem(name, "git clone probe", probe)]
            if probe.tree is None:
                return [
                    CheckResult(
                        Outcome.NOT_EVALUABLE,
                        f"{name}: git clone probe returned exit status 0 but no "
                        f"materialized tree; stderr tail: {stderr_tail(probe.stderr)}",
                    )
                ]

            where = source.get("path", "")
            where = where if isinstance(where, str) else ""
            manifest = probe.tree / where / ".claude-plugin" / "plugin.json"
            present = manifest.is_file()
            results = [
                _result(
                    present,
                    f"{name}: plugin manifest present at '{where or '.'}' in {ref}",
                )
            ]
            if not present:
                return results

            entry_version = plugin.get("version")
            if not isinstance(entry_version, str) or not entry_version:
                return results

            try:
                installed = json.loads(manifest.read_text(encoding="utf-8"))
                declared = installed.get("version") if isinstance(installed, dict) else None
            except (OSError, UnicodeError, json.JSONDecodeError):
                declared = None
            results.append(
                _result(
                    declared == entry_version,
                    f"{name}: plugin at {ref} declares {declared!r}, "
                    f"entry says {entry_version!r}",
                )
            )
            return results
    except subprocess.TimeoutExpired as exc:
        probe = _timeout_result(exc, CLONE_TIMEOUT_SECONDS)
        return [_probe_problem(name, "git clone probe", probe)]


def validate_manifest(
    marketplace: Mapping[str, Any],
    probe_remote: RemoteProbe,
    probe_tree: TreeProbe,
) -> list[CheckResult]:
    """Return every verdict without printing or selecting a process exit code."""

    results = [
        _result(marketplace.get("name") == "courthouse", "marketplace name is 'courthouse'"),
        _result(
            isinstance(marketplace.get("owner"), dict)
            and bool(marketplace["owner"].get("url")),
            "owner present",
        ),
    ]

    plugins_value = marketplace.get("plugins")
    plugins = plugins_value if isinstance(plugins_value, list) else []
    results.append(_result(isinstance(plugins_value, list), "plugins is a list"))
    if not isinstance(plugins_value, list):
        return results

    # There is deliberately no fixed plugin-count check. Retiring it gives up
    # its useful 3 -> 2 plain-deletion signal, but it never caught substitution
    # and becomes false as soon as the marketplace legitimately grows. Detecting
    # an entry that disappears between commits requires a ratchet against the
    # previous committed manifest, which is deliberately outside this unit.
    names = [plugin.get("name") if isinstance(plugin, dict) else None for plugin in plugins]
    nonempty_names = all(isinstance(name, str) and bool(name.strip()) for name in names)
    results.append(_result(nonempty_names, "every plugin name is non-empty"))
    comparable_names = [name for name in names if isinstance(name, str) and name.strip()]
    results.append(
        _result(
            len(comparable_names) == len(set(comparable_names)),
            "plugin names are unique",
        )
    )

    for index, plugin_value in enumerate(plugins):
        if not isinstance(plugin_value, dict):
            results.append(_result(False, f"plugin #{index + 1} is an object"))
            continue
        plugin = plugin_value
        raw_name = plugin.get("name")
        name = raw_name if isinstance(raw_name, str) and raw_name else f"<unnamed #{index + 1}>"

        for field in ("description", "license", "homepage", "version"):
            results.append(_result(bool(plugin.get(field)), f"{name}: has {field}"))

        source_value = plugin.get("source")
        source = source_value if isinstance(source_value, dict) else {}
        url = remote_url(source)
        results.append(_result(bool(url), f"{name}: source identifies an install repository"))

        homepage = plugin.get("homepage")
        if url and isinstance(homepage, str) and homepage:
            # The github source kind has `repo` and no `url`; for that shape the
            # comparison uses the GitHub URL derived by remote_url(). Thus it is
            # neither an unhandled KeyError nor a vacuous pass.
            results.append(
                _result(
                    normalize_repository(url) == normalize_repository(homepage),
                    f"{name}: install source and homepage name the same repository",
                )
            )

        ref = source.get("ref")
        sha = source.get("sha")
        valid_ref = isinstance(ref, str) and bool(ref)
        valid_sha = isinstance(sha, str) and SHA.fullmatch(sha) is not None
        results.append(_result(valid_ref, f"{name}: source pinned to a ref"))
        results.append(_result(valid_sha, f"{name}: source pinned to a 40-hex sha"))

        if valid_ref and isinstance(plugin.get("version"), str) and plugin.get("version"):
            # `gyroscope` shipped version 0.1.0 against ref v1.0.0 for the whole
            # v1 series. Every other check read those fields independently, so
            # the marketplace version used for pinning and upgrades was wrong.
            results.append(
                _result(
                    version_matches_ref(plugin["version"], ref),
                    f"{name}: ref {ref!r} contains exactly declared version "
                    f"{plugin['version']!r}",
                )
            )

        if not (url and valid_ref and valid_sha):
            continue

        results.append(_evaluate_remote_pin(name, url, ref, sha, probe_remote))

        # Fields in this repository can agree while disagreeing with what is
        # installed. Fetching the pinned tree binds the entry to the consumer's
        # tree. Both defects this catches shipped: entries named versions their
        # plugin.json did not declare, and ward/makoto moved the manifest under
        # `plugin/` without the marketplace path following it.
        results.extend(_evaluate_tree(plugin, name, source, url, ref, probe_tree))

    return results


def real_remote_probe(url: str, ref: str) -> ProbeResult:
    try:
        completed = subprocess.run(
            [
                "git",
                "ls-remote",
                url,
                f"refs/tags/{ref}",
                f"refs/tags/{ref}^{{}}",
                f"refs/heads/{ref}",
            ],
            capture_output=True,
            text=True,
            timeout=LS_REMOTE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return _timeout_result(exc, LS_REMOTE_TIMEOUT_SECONDS)
    return ProbeResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


@contextlib.contextmanager
def real_tree_probe(url: str, ref: str) -> Iterator[ProbeResult]:
    with tempfile.TemporaryDirectory() as temporary_directory:
        try:
            completed = subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", ref, url, temporary_directory],
                capture_output=True,
                text=True,
                timeout=CLONE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            yield _timeout_result(exc, CLONE_TIMEOUT_SECONDS)
            return
        yield ProbeResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            tree=pathlib.Path(temporary_directory),
        )


# The status a run reports when the validator itself broke before it could rule. It is separate
# from 1 because an uncaught exception exits 1 on its own, and 1 already means "a check
# disagreed" -- reporting a crash as a disagreement is the same lie this file exists to refuse,
# one layer out: nothing was checked, so nothing may be reported about the manifest.
EXIT_INTERNAL_ERROR = 3

# One writer for what each status means. These sentences used to live in a `case` block in
# .github/workflows/ci.yml, where no test could reach them and only the exit-0 branch had ever
# been observed running. Here the suite pins every branch.
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


def print_report(results: list[CheckResult]) -> None:
    for result in results:
        print(f"{result.outcome.value:<15} {result.message}")
    counts = {outcome: 0 for outcome in Outcome}
    for result in results:
        counts[result.outcome] += 1
    print(
        f"\n{counts[Outcome.PASS]} passed, {counts[Outcome.FAIL]} failed, "
        f"{counts[Outcome.NOT_EVALUABLE]} not-evaluable"
    )


def main() -> int:
    try:
        marketplace = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        results = [CheckResult(Outcome.FAIL, f"marketplace manifest is readable JSON: {exc}")]
    else:
        if not isinstance(marketplace, dict):
            results = [CheckResult(Outcome.FAIL, "marketplace manifest is a JSON object")]
        else:
            results = validate_manifest(marketplace, real_remote_probe, real_tree_probe)
    print_report(results)
    status = exit_code(results)
    print(VERDICTS[status])
    return status


def cli(run: Callable[[], int] = main) -> int:
    """Run `run`, and give a validator that broke its own status rather than a check's.

    `run` is injected for the same reason the probes are: the crash path is a branch like any
    other, and a branch no test can reach is a branch nobody has seen work.
    """
    try:
        return run()
    except Exception:  # noqa: BLE001 -- the traceback is printed, never swallowed
        traceback.print_exc()
        print(VERDICTS[EXIT_INTERNAL_ERROR])
        return EXIT_INTERNAL_ERROR


if __name__ == "__main__":
    sys.exit(cli())
