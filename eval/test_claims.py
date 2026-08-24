import contextlib
import io
import pathlib
import tempfile
import unittest
from unittest import mock

import claims


class ClaimScannerTests(unittest.TestCase):
    def scan(self, text):
        return claims.scan_text(text, "README.md")

    def classes(self, text):
        return [(row.klass, row.kind, row.numerator) for row in self.scan(text)]

    def test_identifier_excludes_letter_digit(self):
        self.assertIn(("EXCLUDED", "identifier", "3"), self.classes("python3"))

    def test_identifier_does_not_swallow_count_modifier(self):
        self.assertIn(("CLAIM", "bare", "11"), self.classes("11-row table"))

    def test_source_fence_excludes_source(self):
        self.assertIn(("EXCLUDED", "source-fence", "24"), self.classes("```python\nx = 24\n```"))

    def test_console_fence_scans_output(self):
        rows = self.classes("```console\nDIAGNOSTIC_COVERAGE=31.58% proven=24 total=76\n```")
        self.assertEqual(3, sum(row[0] == "CLAIM" for row in rows))

    def test_generated_block_excludes_and_outside_scans(self):
        rows = self.classes("before 1\n<!-- BEGIN GENERATED -->\n2\n<!-- END GENERATED -->\nafter 3")
        self.assertIn(("EXCLUDED", "generated-block", "2"), rows)
        self.assertIn(("CLAIM", "bare", "3"), rows)

    def test_footnote_definition_excludes_but_reference_does_not_hide_prior_claim(self):
        rows = self.scan("24 clauses[^m-count]\n[^m-count]: v2.0.2 at /x on 2026-08-24")
        self.assertEqual("count", next(row.anchor for row in rows if row.klass == "CLAIM"))
        self.assertTrue(all(row.klass == "EXCLUDED" for row in rows[1:]))

    def test_url_excludes_target_but_scans_image_alt(self):
        rows = self.classes("![dispatches 105 checks](https://x/gate-105_checks.svg)")
        self.assertIn(("CLAIM", "bare", "105"), rows)
        self.assertIn(("EXCLUDED", "url", "105"), rows)

    def test_date_excludes_date_but_not_plain_year(self):
        rows = self.classes("2026-08-24 and 2026")
        self.assertEqual(3, sum(row[1] == "date" for row in rows))
        self.assertIn(("CLAIM", "bare", "2026"), rows)

    def test_version_excludes_version_but_not_percent(self):
        rows = self.classes("v1.1.0 and Apache-2.0 and 31.58%")
        self.assertEqual(2, sum(row[1] == "version" for row in rows))
        self.assertIn(("CLAIM", "bare", "31.58%"), rows)

    def test_ordered_marker_excluded_but_leading_count_scanned(self):
        self.assertIn(("EXCLUDED", "ordered-list-marker", "2"), self.classes("2. item"))
        self.assertIn(("CLAIM", "bare", "15"), self.classes("15 pre-checks block"))

    def test_inline_zero_is_claim(self):
        self.assertIn(("CLAIM", "bare", "0"), self.classes("`clauses: 0` is a gate"))

    def test_inline_exit_two_is_claim(self):
        self.assertIn(("CLAIM", "bare", "2"), self.classes("exit `2` means unknown"))

    def test_ratio_is_one_claim(self):
        rows = [row for row in self.scan("Ward 6/6[^m-ward]") if row.klass == "CLAIM"]
        self.assertEqual([("ratio", "6", "6", "ward")],
                         [(row.kind, row.numerator, row.denominator, row.anchor) for row in rows])

    def test_two_claims_bind_separate_anchors(self):
        rows = [row for row in self.scan("6[^m-six] and 5[^m-five]") if row.klass == "CLAIM"]
        self.assertEqual(["six", "five"], [row.anchor for row in rows])

    def test_word_cardinal_plural_is_claim(self):
        self.assertIn(("CLAIM", "word-cardinal", "3"), self.classes("Three clauses"))

    def test_word_cardinal_singular_and_one_are_silent(self):
        self.assertEqual([], self.classes("one door and three clause"))


class RepositoryFindingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.temporary.name)
        (self.repo / "README.md").write_text("", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, readme, rows=(), verify_evidence=False):
        (self.repo / "README.md").write_text(readme, encoding="utf-8")
        if rows is not None:
            ledger = "KEY\tVALUE\tDENOMINATOR\tCOMMAND\tSUBJECT\n" + "\n".join(rows)
            (self.repo / "MEASURED.tsv").write_text(ledger + "\n", encoding="utf-8")
        return claims.inspect_repository(self.repo, verify_evidence=verify_evidence)

    def findings(self, report):
        return [row.finding for row in report.rows if row.finding != "-"]

    def test_agreeing_anchor_has_no_finding(self):
        self.assertEqual([], self.findings(self.write("5 checks[^m-k]", ["k\t5\t-\tcount\tchecks"])))

    def test_unanchored_only(self):
        self.assertEqual(["UNANCHORED"], self.findings(self.write("5 checks", [])))

    def test_unresolved_only(self):
        self.assertEqual(["UNRESOLVED"], self.findings(self.write("5 checks[^m-k]", [])))

    def test_value_mismatch_only(self):
        self.assertEqual(["MISMATCH"], self.findings(self.write("5 checks[^m-k]", ["k\t6\t-\tcount\tchecks"])))

    def test_denominator_mismatch_only(self):
        self.assertEqual(["MISMATCH"], self.findings(self.write("5/6[^m-k]", ["k\t5\t7\tcount\tchecks"])))

    def test_orphan_only(self):
        self.assertEqual(["ORPHAN"], self.findings(self.write("no numbers", ["k\t5\t-\tcount\tchecks"])))

    def test_duplicate_only(self):
        report = self.write("5 checks[^m-k]", ["k\t5\t-\tcount\tchecks", "k\t5\t-\tcount\tchecks"])
        self.assertEqual(["DUPLICATE-KEY", "DUPLICATE-KEY"], self.findings(report))

    def test_empty_command_only(self):
        self.assertEqual(["EMPTY-COMMAND"], self.findings(self.write("5 checks[^m-k]", ["k\t5\t-\t\tchecks"])))

    def test_verified_ledger_value_has_no_finding(self):
        report = self.write("5[^m-k]", ["k\t5\t-\tprintf 5\tthing"], verify_evidence=True)
        self.assertEqual([], self.findings(report))

    def test_wrong_ledger_value_names_surface_and_line(self):
        report = self.write("5[^m-k]", ["k\t5\t-\tprintf 6\tthing"], verify_evidence=True)
        rows = [row for row in report.rows if row.finding == "LEDGER-UNVERIFIED"]
        self.assertEqual(1, len(rows))
        self.assertEqual((str(self.repo / "MEASURED.tsv"), 2), (rows[0].surface, rows[0].line))

    def test_nonzero_evidence_is_not_evaluable_not_mismatch(self):
        report = self.write("5[^m-k]", ["k\t5\t-\tsh -c 'exit 7'\tthing"],
                            verify_evidence=True)
        self.assertNotIn("LEDGER-UNVERIFIED", self.findings(report))
        self.assertEqual([claims.Outcome.NOT_EVALUABLE],
                         [result.outcome for result in report.results])
        self.assertIn("status 7", report.informational[0])

    def test_timed_out_evidence_is_not_evaluable_not_mismatch(self):
        with mock.patch.object(claims, "EVIDENCE_TIMEOUT_SECONDS", 0.01):
            report = self.write("5[^m-k]", ["k\t5\t-\tpython3 -c 'import time; time.sleep(1)'\tthing"],
                                verify_evidence=True)
        self.assertNotIn("LEDGER-UNVERIFIED", self.findings(report))
        self.assertEqual([claims.Outcome.NOT_EVALUABLE],
                         [result.outcome for result in report.results])
        self.assertIn("timed out", report.informational[0])

    def test_without_verify_flag_does_not_execute_command(self):
        with mock.patch.object(claims.subprocess, "run",
                               side_effect=AssertionError("evidence command executed")):
            report = self.write("5[^m-k]", ["k\t5\t-\tsh -c 'exit 99'\tthing"])
        self.assertEqual([], self.findings(report))

    def test_evidence_exit_contract_all_states(self):
        passing = self.write("5[^m-k]", ["k\t5\t-\tprintf 5\tthing"], True)
        failing = self.write("5[^m-k]", ["k\t5\t-\tprintf 6\tthing"], True)
        unknown = self.write("5[^m-k]", ["k\t5\t-\tsh -c 'exit 7'\tthing"], True)
        self.assertEqual([0, 1, 2],
                         [claims.exit_code(report.results)
                          for report in (passing, failing, unknown)])

    def test_invalid_readme_encoding_is_not_evaluable(self):
        (self.repo / "README.md").write_bytes(b"\xff 5")
        report = claims.inspect_repository(self.repo)
        self.assertEqual([claims.Outcome.NOT_EVALUABLE], [result.outcome for result in report.results])
        self.assertFalse(report.rows)

    def test_invalid_ledger_is_not_evaluable_without_unresolved(self):
        report = self.write("5 checks[^m-k]", None)
        (self.repo / "MEASURED.tsv").write_text("bad header\n", encoding="utf-8")
        report = claims.inspect_repository(self.repo)
        self.assertEqual([claims.Outcome.NOT_EVALUABLE], [result.outcome for result in report.results])
        self.assertNotIn("UNRESOLVED", self.findings(report))

    def test_all_excluded_exits_zero_and_rows_remain(self):
        report = self.write("python3 v2.0.2 2026-08-24", [])
        self.assertEqual(0, claims.exit_code(report.results))
        self.assertTrue(report.rows)
        self.assertTrue(all(row.klass == "EXCLUDED" for row in report.rows))

    def test_exit_contract_all_states(self):
        passing = self.write("5[^m-k]", ["k\t5\t-\tcount\tthing"])
        failing = self.write("5", [])
        (self.repo / "README.md").write_bytes(b"\xff")
        unknown = claims.inspect_repository(self.repo)
        self.assertEqual([0, 1, 2], [claims.exit_code(value.results) for value in (passing, failing, unknown)])


class TierFindingTests(unittest.TestCase):
    SHIPPED_LINE = ("Shipped plugin — installable and versioned. The dispatcher is replay-tested "
                    "against authored sessions; its effect on a live session's outcome is unmeasured.")
    RECORD_LINE = ("A development record, not a product. Runnable from a checkout, never published "
                   "as one; its numbers are evidence about how the shipped work was built.")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.temporary.name) / "Ward"
        self.repo.mkdir()
        self.tiers_path = pathlib.Path(self.temporary.name) / "TIERS.tsv"

    def tearDown(self):
        self.temporary.cleanup()

    def inspect(self, readme, tier="SHIPPED", declaration=None, command=None):
        declaration = declaration or (self.SHIPPED_LINE if tier == "SHIPPED" else self.RECORD_LINE)
        (self.repo / "README.md").write_text(readme, encoding="utf-8")
        ledger_row = "" if command is None else f"k\t5\t-\t{command}\tthing\n"
        (self.repo / "MEASURED.tsv").write_text(
            "KEY\tVALUE\tDENOMINATOR\tCOMMAND\tSUBJECT\n" + ledger_row, encoding="utf-8")
        tiers = [claims.TierRow("Ward", tier, declaration, 2,
                                f"Ward\t{tier}\t{declaration}")]
        return claims.inspect_repository(self.repo, tiers, self.tiers_path)

    @staticmethod
    def tier_findings(report):
        return [row.finding for row in report.rows if row.klass == "TIER"]

    def test_tier_absent_fires_and_verbatim_line_is_silent(self):
        self.assertIn("TIER-ABSENT", self.tier_findings(self.inspect("no declaration")))
        self.assertNotIn("TIER-ABSENT", self.tier_findings(self.inspect(self.SHIPPED_LINE)))

    def test_tier_paraphrase_is_still_absent(self):
        report = self.inspect("Shipped, versioned, and live-session outcomes are unmeasured.")
        self.assertIn("TIER-ABSENT", self.tier_findings(report))

    def test_tier_undeclared_fires(self):
        (self.repo / "README.md").write_text("text", encoding="utf-8")
        (self.repo / "MEASURED.tsv").write_text(
            "KEY\tVALUE\tDENOMINATOR\tCOMMAND\tSUBJECT\n", encoding="utf-8")
        report = claims.inspect_repository(self.repo, [], self.tiers_path)
        self.assertEqual(["TIER-UNDECLARED"], self.tier_findings(report))

    def test_shipped_efficacy_literal_fires_and_is_silent(self):
        missing = self.inspect("no efficacy declaration")
        present = self.inspect("its effect on a live session's outcome is unmeasured")
        self.assertIn("EFFICACY-UNDECLARED", self.tier_findings(missing))
        self.assertNotIn("EFFICACY-UNDECLARED", self.tier_findings(present))

    def test_record_does_not_owe_efficacy_literal(self):
        self.assertNotIn("EFFICACY-UNDECLARED",
                         self.tier_findings(self.inspect(self.RECORD_LINE, "RECORD")))

    def test_foreign_evidence_fires_and_in_repo_command_is_silent(self):
        foreign = self.inspect(self.SHIPPED_LINE, command="python3 ../Ward/eval.py")
        local = self.inspect(self.SHIPPED_LINE, command="python3 eval/replay.py")
        self.assertIn("FOREIGN-EVIDENCE", self.tier_findings(foreign))
        self.assertNotIn("FOREIGN-EVIDENCE", self.tier_findings(local))

    def test_foreign_evidence_names_the_ledger_it_read_not_the_readme(self):
        # entry.line indexes MEASURED.tsv, so a README surface pointed the reader at whatever
        # sat on that line of the wrong file. The row must name the file it was computed from.
        report = self.inspect(self.SHIPPED_LINE, command="python3 ../Ward/eval.py")
        row = next(r for r in report.rows if r.finding == "FOREIGN-EVIDENCE")
        self.assertEqual(row.surface, str(self.repo / "MEASURED.tsv"))
        self.assertEqual(row.line, 2)

    def test_record_install_fires_but_shipped_install_is_silent(self):
        record = self.inspect(self.RECORD_LINE + "\nclaude plugin install thing", "RECORD")
        shipped = self.inspect(self.SHIPPED_LINE + "\nclaude plugin install thing", "SHIPPED")
        self.assertIn("RECORD-SELLS-INSTALL", self.tier_findings(record))
        self.assertNotIn("RECORD-SELLS-INSTALL", self.tier_findings(shipped))

    def test_tiers_parser_rejects_bad_file(self):
        self.tiers_path.write_text("bad header\n", encoding="utf-8")
        tiers, error = claims.read_tiers(self.tiers_path)
        self.assertIsNone(tiers)
        self.assertIsNotNone(error)

    def test_unparseable_tiers_is_not_evaluable_with_no_tier_findings(self):
        (self.repo / "README.md").write_text("text", encoding="utf-8")
        with mock.patch.object(claims, "read_tiers", return_value=(None, "bad header")), \
                mock.patch.object(claims, "build_parser") as parser:
            parser.return_value.parse_args.return_value = type(
                "Arguments", (), {"repo": self.repo, "estate": None, "claims_only": False,
                                   "verify_evidence": False})()
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
                status = claims.main([])
        self.assertEqual(2, status)
        self.assertNotIn("\tTIER\t", stdout.getvalue())

    def test_tier_exit_contract_all_states(self):
        passing = self.inspect(self.SHIPPED_LINE)
        failing = self.inspect("missing")
        unknown = claims.Report(results=[claims.CheckResult(claims.Outcome.NOT_EVALUABLE, "tiers")])
        self.assertEqual([0, 1, 2],
                         [claims.exit_code(report.results) for report in (passing, failing, unknown)])


class CliTests(unittest.TestCase):
    def test_target_is_required_and_mutually_exclusive(self):
        parser = claims.build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args([])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["--repo", ".", "--estate", "."])

    def test_verify_evidence_is_rejected_with_estate(self):
        parser = claims.build_parser()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["--estate", ".", "--verify-evidence"])

    def test_courthouse_is_fully_measured(self):
        report = claims.inspect_repository(pathlib.Path(__file__).resolve().parent.parent)
        self.assertFalse(report.results, report.results)


if __name__ == "__main__":
    unittest.main()
