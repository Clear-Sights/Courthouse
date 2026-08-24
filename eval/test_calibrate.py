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


if __name__ == "__main__":
    unittest.main()
