import contextlib
import io
import pathlib
import unittest
from unittest import mock

import calibrate
import claims


class CalibrationTests(unittest.TestCase):
    def test_plant_ids_are_unique_and_cover_every_declared_finding(self):
        ids = [plant.id for plant in calibrate.PLANTS]
        self.assertEqual(len(ids), len(set(ids)))
        covered = {plant.expected_finding for plant in calibrate.PLANTS if plant.expected_finding}
        self.assertEqual(set(claims.FINDING_TYPES), covered)

    def test_inert_plant_is_a_failure(self):
        inert = calibrate.Plant("inert", lambda estate: lambda: None,
                                calibrate.POLARITY_FIRES, "UNANCHORED",
                                "courthouse/README.md")
        status, results = calibrate.run_battery([inert])
        self.assertEqual(1, status)
        self.assertEqual(calibrate.Outcome.FAIL, results[0].outcome)

    def test_bad_revert_is_a_failure_and_names_the_plant(self):
        def mutation(estate):
            path = estate / "courthouse/README.md"
            path.write_text(path.read_text(encoding="utf-8") + "\n921 claims.\n", encoding="utf-8")
            return lambda: None

        plant = calibrate.Plant("bad-revert", mutation, calibrate.POLARITY_FIRES,
                                "UNANCHORED", "courthouse/README.md")
        status, results = calibrate.run_battery([plant])
        self.assertEqual(1, status)
        self.assertEqual("bad-revert", results[0].plant.id)
        self.assertFalse(results[0].restored)

    def test_wrong_red_is_not_credited(self):
        plant = calibrate.Plant(
            "wrong-red",
            calibrate._append("courthouse/README.md", "\n922 claims.\n"),
            calibrate.POLARITY_FIRES, "UNRESOLVED", "courthouse/README.md")
        status, results = calibrate.run_battery([plant])
        self.assertEqual(1, status)
        self.assertFalse(results[0].observed)

    def test_exit_contract_produces_zero_one_and_two(self):
        passing = mock.Mock(return_value=calibrate.PlantResult(
            mock.Mock(id="pass"), calibrate.Outcome.PASS, True, True, "ok"))
        failing = mock.Mock(return_value=calibrate.PlantResult(
            mock.Mock(id="fail"), calibrate.Outcome.FAIL, False, True, "fail"))
        unknown = mock.Mock(return_value=calibrate.PlantResult(
            mock.Mock(id="unknown"), calibrate.Outcome.NOT_EVALUABLE, False, False, "unknown"))
        plant = calibrate.Plant("p", lambda estate: lambda: None, calibrate.POLARITY_SILENT)
        with mock.patch.object(calibrate, "exercise", passing):
            self.assertEqual(0, calibrate.run_battery([plant])[0])
        with mock.patch.object(calibrate, "exercise", failing):
            self.assertEqual(1, calibrate.run_battery([plant])[0])
        with mock.patch.object(calibrate, "exercise", unknown):
            self.assertEqual(2, calibrate.run_battery([plant])[0])

    def test_residue_rows_do_not_change_exit_status(self):
        with mock.patch.object(calibrate, "PLANTS", ()), \
                mock.patch.object(calibrate, "RESIDUE", calibrate.RESIDUE + (
                    calibrate.Residue("X-1", "a -> b", "invisible"),)):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = calibrate.main()
        self.assertEqual(0, status)
        self.assertIn("RESIDUE\tX-1", stdout.getvalue())

    def test_a_plant_that_never_fired_is_not_counted_as_coverage(self):
        """The summary's `covered` must fall when a plant stops being observed.

        Before this cell, `covered` was `len(results)` -- the plants RUN, not the plants
        SEEN FIRING. A run in which 15 of 19 plants were never observed still printed
        `covered=19`, the same figure as the fully green run, on the same line as
        `Validation failed`. A coverage number that cannot move when coverage is lost is
        the defect this whole file exists to detect, reproduced in its own summary.
        """
        observed = calibrate.PlantResult(
            mock.Mock(id="seen", polarity=calibrate.POLARITY_FIRES, expected_finding="UNANCHORED",
                      expected_surface=None),
            calibrate.Outcome.PASS, True, True, "ok")
        unobserved = calibrate.PlantResult(
            mock.Mock(id="unseen", polarity=calibrate.POLARITY_FIRES, expected_finding="UNANCHORED",
                      expected_surface=None),
            calibrate.Outcome.FAIL, False, True, "declared observation absent")

        def summary_for(results):
            with mock.patch.object(calibrate, "run_battery",
                                   return_value=(0 if all(r.outcome is calibrate.Outcome.PASS
                                                          for r in results) else 1, results)):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    calibrate.main()
            return [line for line in stdout.getvalue().splitlines()
                    if line.startswith("SUMMARY")][0]

        residue = len(calibrate.RESIDUE)
        both_seen = summary_for([observed, observed])
        one_lost = summary_for([observed, unobserved])

        # Non-vacuity first: the green line must actually carry the full count, or the
        # comparison below would pass over a summary that reports nothing at all.
        self.assertIn("covered=2", both_seen)
        self.assertIn("unobserved=0", both_seen)
        self.assertIn(f"uncovered={residue}", both_seen)

        self.assertIn("covered=1", one_lost)
        self.assertIn("unobserved=1", one_lost)
        self.assertIn(f"uncovered={residue + 1}", one_lost)
        self.assertNotEqual(both_seen, one_lost,
                            "the summary did not move when a plant stopped firing")

        # `plants` is the denominator of what RAN and must stay put -- losing coverage must
        # not also shrink the population it is measured against, or the ratio lies twice.
        self.assertIn("plants=2", both_seen)
        self.assertIn("plants=2", one_lost)


if __name__ == "__main__":
    unittest.main()
