import contextlib
import copy
import io
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

import validate


PINNED_SHA = "a" * 40
OTHER_SHA = "b" * 40
AUTH_FAILURE = (
    "fatal: could not read Username for 'https://github.com': "
    "terminal prompts disabled"
)


def valid_marketplace():
    return {
        "name": "courthouse",
        "owner": {"name": "Clear-Sights", "url": "https://github.com/Clear-Sights"},
        "plugins": [
            {
                "name": "example",
                "description": "An example plugin",
                "license": "Apache-2.0",
                "homepage": "https://github.com/Clear-Sights/Example",
                "version": "2.0.2",
                "source": {
                    "source": "git-subdir",
                    "url": "https://github.com/clear-sights/example.git",
                    "path": "plugin",
                    "ref": "v2.0.2",
                    "sha": PINNED_SHA,
                },
            }
        ],
    }


def successful_remote(_url, ref):
    return validate.ProbeResult(
        returncode=0,
        stdout=f"{'c' * 40}\trefs/tags/{ref}\n{PINNED_SHA}\trefs/tags/{ref}^{{}}\n",
    )


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.tree = pathlib.Path(self.temporary_directory.name)
        manifest = self.tree / "plugin" / ".claude-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"version": "2.0.2"}), encoding="utf-8")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def tree_probe(self, returncode=0, stderr="", tree=None):
        materialized = self.tree if tree is None else tree

        @contextlib.contextmanager
        def probe(_url, _ref):
            yield validate.ProbeResult(
                returncode=returncode,
                stderr=stderr,
                tree=materialized,
            )

        return probe

    def run_validation(self, marketplace=None, remote=successful_remote, tree=None):
        return validate.validate_manifest(
            valid_marketplace() if marketplace is None else marketplace,
            remote,
            tree or self.tree_probe(),
        )

    def assert_only(self, results, outcome, text):
        exceptional = [result for result in results if result.outcome is not validate.Outcome.PASS]
        self.assertEqual(1, len(exceptional), exceptional)
        self.assertIs(outcome, exceptional[0].outcome)
        self.assertIn(text, exceptional[0].message)

    def test_valid_manifest_passes_every_check(self):
        results = self.run_validation()
        self.assertTrue(results)
        self.assertTrue(all(result.outcome is validate.Outcome.PASS for result in results))
        self.assertEqual(0, validate.exit_code(results))

    def test_wrong_marketplace_name_is_its_own_failure(self):
        marketplace = valid_marketplace()
        marketplace["name"] = "other"
        self.assert_only(self.run_validation(marketplace), validate.Outcome.FAIL, "marketplace name")

    def test_missing_owner_is_its_own_failure(self):
        marketplace = valid_marketplace()
        marketplace["owner"] = {}
        self.assert_only(self.run_validation(marketplace), validate.Outcome.FAIL, "owner present")

    def test_plugins_must_be_a_list(self):
        marketplace = valid_marketplace()
        marketplace["plugins"] = None
        self.assert_only(self.run_validation(marketplace), validate.Outcome.FAIL, "plugins is a list")

    def test_plugin_name_must_be_nonempty(self):
        marketplace = valid_marketplace()
        marketplace["plugins"][0]["name"] = ""
        self.assert_only(self.run_validation(marketplace), validate.Outcome.FAIL, "name is non-empty")

    def test_plugin_names_must_be_unique(self):
        marketplace = valid_marketplace()
        marketplace["plugins"].append(copy.deepcopy(marketplace["plugins"][0]))
        self.assert_only(self.run_validation(marketplace), validate.Outcome.FAIL, "names are unique")

    def test_description_must_be_present(self):
        marketplace = valid_marketplace()
        marketplace["plugins"][0]["description"] = ""
        self.assert_only(self.run_validation(marketplace), validate.Outcome.FAIL, "has description")

    def test_license_must_be_present(self):
        marketplace = valid_marketplace()
        marketplace["plugins"][0]["license"] = ""
        self.assert_only(self.run_validation(marketplace), validate.Outcome.FAIL, "has license")

    def test_homepage_must_be_present(self):
        marketplace = valid_marketplace()
        marketplace["plugins"][0]["homepage"] = ""
        self.assert_only(self.run_validation(marketplace), validate.Outcome.FAIL, "has homepage")

    def test_version_must_be_present(self):
        marketplace = valid_marketplace()
        marketplace["plugins"][0]["version"] = ""
        self.assert_only(self.run_validation(marketplace), validate.Outcome.FAIL, "has version")

    def test_install_repository_must_be_present(self):
        marketplace = valid_marketplace()
        marketplace["plugins"][0]["source"]["url"] = ""
        self.assert_only(
            self.run_validation(marketplace), validate.Outcome.FAIL, "identifies an install repository"
        )

    def test_ref_must_be_present(self):
        marketplace = valid_marketplace()
        marketplace["plugins"][0]["source"]["ref"] = ""
        self.assert_only(self.run_validation(marketplace), validate.Outcome.FAIL, "pinned to a ref")

    def test_sha_must_be_40_lowercase_hex_characters(self):
        marketplace = valid_marketplace()
        marketplace["plugins"][0]["source"]["sha"] = "xyz"
        self.assert_only(self.run_validation(marketplace), validate.Outcome.FAIL, "40-hex sha")

    def test_source_and_homepage_same_repository_pass(self):
        results = self.run_validation()
        relation = [result for result in results if "same repository" in result.message]
        self.assertEqual([validate.Outcome.PASS], [result.outcome for result in relation])

    def test_source_and_homepage_different_repository_fail(self):
        marketplace = valid_marketplace()
        marketplace["plugins"][0]["source"]["url"] = "https://github.com/fork/Example.git"
        self.assert_only(self.run_validation(marketplace), validate.Outcome.FAIL, "same repository")

    def test_github_source_kind_compares_derived_url(self):
        marketplace = valid_marketplace()
        marketplace["plugins"][0]["source"] = {
            "source": "github",
            "repo": "Clear-Sights/Example",
            "ref": "v2.0.2",
            "sha": PINNED_SHA,
            "path": "plugin",
        }
        results = self.run_validation(marketplace)
        self.assertTrue(all(result.outcome is validate.Outcome.PASS for result in results), results)

    def test_github_source_kind_without_repo_fails_cleanly(self):
        marketplace = valid_marketplace()
        marketplace["plugins"][0]["source"] = {
            "source": "github",
            "ref": "v2.0.2",
            "sha": PINNED_SHA,
            "path": "plugin",
        }
        self.assert_only(
            self.run_validation(marketplace),
            validate.Outcome.FAIL,
            "identifies an install repository",
        )

    def test_version_release_tag_matches(self):
        self.assertTrue(validate.version_matches_ref("2.0.2", "v2.0.2"))

    def test_version_release_path_matches(self):
        self.assertTrue(validate.version_matches_ref("2.0.2", "release/2.0.2"))

    def test_version_substring_does_not_match(self):
        self.assertFalse(validate.version_matches_ref("2.0", "v2.0.2"))

    def test_empty_version_does_not_match(self):
        self.assertFalse(validate.version_matches_ref("", "v2.0.2"))

    def test_release_does_not_match_prerelease_ref(self):
        self.assertFalse(validate.version_matches_ref("2.0.2", "v2.0.2-rc1"))

    def test_prerelease_version_matches_exactly(self):
        self.assertTrue(validate.version_matches_ref("2.5.0-rc.1", "v2.5.0-rc.1"))

    def test_larger_leading_version_does_not_match(self):
        self.assertFalse(validate.version_matches_ref("2.0.2", "v12.0.2"))

    def test_larger_trailing_version_does_not_match(self):
        self.assertFalse(validate.version_matches_ref("2.0.2", "v2.0.20"))

    def test_suffix_swallowed_token_must_equal_version(self):
        self.assertFalse(
            validate.version_matches_ref("1.1.0", "hotfix-2.0.2-backport-of-1.1.0")
        )

    def test_two_version_tokens_are_ambiguous(self):
        self.assertFalse(validate.version_matches_ref("1.0.0", "v1.0.0_v2.0.0"))

    def test_unreachable_remote_is_not_evaluable(self):
        def unreachable(_url, _ref):
            return validate.ProbeResult(returncode=128, stderr=AUTH_FAILURE)

        results = self.run_validation(remote=unreachable)
        self.assert_only(results, validate.Outcome.NOT_EVALUABLE, "exit status 128")
        self.assertIn(AUTH_FAILURE, next(r.message for r in results if r.outcome is validate.Outcome.NOT_EVALUABLE))
        self.assertFalse(any("resolves to pinned sha" in r.message for r in results if r.outcome is validate.Outcome.FAIL))
        self.assertEqual(2, validate.exit_code(results))

    def test_reachable_remote_with_absent_ref_fails(self):
        def absent(_url, _ref):
            return validate.ProbeResult(returncode=0, stdout="")

        results = self.run_validation(remote=absent)
        self.assert_only(results, validate.Outcome.FAIL, "got None")
        self.assertEqual(1, validate.exit_code(results))

    def test_remote_resolving_different_sha_fails(self):
        def different(_url, ref):
            return validate.ProbeResult(returncode=0, stdout=f"{OTHER_SHA}\trefs/tags/{ref}^{{}}\n")

        results = self.run_validation(remote=different)
        self.assert_only(results, validate.Outcome.FAIL, OTHER_SHA)
        self.assertEqual(1, validate.exit_code(results))

    def test_remote_timeout_is_not_evaluable(self):
        def timeout(_url, _ref):
            raise subprocess.TimeoutExpired(["git", "ls-remote"], 120, stderr=AUTH_FAILURE)

        results = self.run_validation(remote=timeout)
        self.assert_only(results, validate.Outcome.NOT_EVALUABLE, "timed out after 120s")
        self.assertEqual(2, validate.exit_code(results))

    def test_clone_nonzero_is_not_evaluable(self):
        results = self.run_validation(tree=self.tree_probe(returncode=128, stderr=AUTH_FAILURE))
        self.assert_only(results, validate.Outcome.NOT_EVALUABLE, "git clone probe")
        self.assertEqual(2, validate.exit_code(results))

    def test_clone_timeout_is_not_evaluable(self):
        def timeout(_url, _ref):
            raise subprocess.TimeoutExpired(["git", "clone"], 300, stderr=AUTH_FAILURE)

        results = self.run_validation(tree=timeout)
        self.assert_only(results, validate.Outcome.NOT_EVALUABLE, "timed out after 300s")
        self.assertEqual(2, validate.exit_code(results))

    def test_missing_plugin_manifest_fails_presence_only(self):
        empty_tree = pathlib.Path(self.temporary_directory.name) / "empty"
        empty_tree.mkdir()
        results = self.run_validation(tree=self.tree_probe(tree=empty_tree))
        self.assert_only(results, validate.Outcome.FAIL, "plugin manifest present")

    def test_installed_version_mismatch_fails(self):
        manifest = self.tree / "plugin" / ".claude-plugin" / "plugin.json"
        manifest.write_text(json.dumps({"version": "9.9.9"}), encoding="utf-8")
        results = self.run_validation()
        self.assert_only(results, validate.Outcome.FAIL, "declares '9.9.9'")

    def test_exit_zero_for_passes_only(self):
        self.assertEqual(0, validate.exit_code([validate.CheckResult(validate.Outcome.PASS, "ok")]))

    def test_exit_one_when_any_check_fails(self):
        results = [
            validate.CheckResult(validate.Outcome.NOT_EVALUABLE, "unknown"),
            validate.CheckResult(validate.Outcome.FAIL, "wrong"),
        ]
        self.assertEqual(1, validate.exit_code(results))

    def test_exit_two_for_not_evaluable_without_failure(self):
        results = [
            validate.CheckResult(validate.Outcome.PASS, "ok"),
            validate.CheckResult(validate.Outcome.NOT_EVALUABLE, "unknown"),
        ]
        self.assertEqual(2, validate.exit_code(results))

    def test_summary_names_all_three_counts_including_zero(self):
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            validate.print_report([validate.CheckResult(validate.Outcome.PASS, "ok")])
        self.assertIn("1 passed, 0 failed, 0 not-evaluable", output.getvalue())


if __name__ == "__main__":
    unittest.main()
