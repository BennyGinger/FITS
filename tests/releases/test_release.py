"""Exercise release planning and publishing with local Git repositories and a fake API."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError


SCRIPT = Path(__file__).resolve().parents[2] / ".github/scripts/release.py"
spec = importlib.util.spec_from_file_location("proc_release", SCRIPT)
assert spec is not None and spec.loader is not None
release = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = release
spec.loader.exec_module(release)


class FakeGitHub:
    repository = "example/FIScH"

    def __init__(self):
        self.releases = {}
        self.latest = None
        self.calls = []
        self.fail_publish = False

    def request(self, method, path, data=None, *, missing_ok=False):
        self.calls.append((method, path, data))
        if method == "GET" and path.startswith("releases/tags/"):
            return self.releases.get(path.removeprefix("releases/tags/"))
        if method == "GET" and path == "releases/latest":
            return {"tag_name": self.latest} if self.latest else None
        if path == "releases/generate-notes":
            return {"body": "## GitHub release notes\n\nA merged pull request."}
        if method == "POST" and path == "releases":
            if self.fail_publish:
                self.fail_publish = False
                raise RuntimeError("Temporary publishing failure")
            saved = {**data, "html_url": f"https://github.com/example/FIScH/releases/tag/{data['tag_name']}"}
            self.releases[data["tag_name"]] = saved
            if data["make_latest"] == "true":
                self.latest = data["tag_name"]
            return saved
        raise AssertionError((method, path))


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        directory = Path(self.temporary.name)
        self.root = directory / "checkout"
        self.root.mkdir()
        self.remote = directory / "remote.git"
        self.git("init", "-q", "--initial-branch=main")
        self.git("config", "user.name", "Release Test")
        self.git("config", "user.email", "test@example.org")
        subprocess.run(["git", "init", "--bare", "-q", str(self.remote)], check=True)
        self.git("remote", "add", "origin", str(self.remote))
        self.baseline = self.commit_version("1.0.0")
        self.git("tag", "1.0.0")

    def git(self, *arguments):
        return release.git(self.root, *arguments)

    def commit_version(self, version, *, locked=None):
        (self.root / "pyproject.toml").write_text(f'[project]\nname = "fisch"\nversion = "{version}"\n')
        (self.root / "uv.lock").write_text(f'[[package]]\nname = "fisch"\nversion = "{locked or version}"\n')
        self.git("add", "pyproject.toml", "uv.lock")
        self.git("commit", "-qm", f"Release {version}")
        return self.git("rev-parse", "HEAD")

    def commit_work(self, message="Improve previews"):
        (self.root / "work.txt").write_text(message)
        self.git("add", "work.txt")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def plan(self):
        return release.plan_releases(self.root, "1.0.0")

    def test_ordinary_commits_and_same_version_metadata_do_not_release(self):
        self.commit_work()
        with (self.root / "pyproject.toml").open("a") as file:
            file.write('description = "Improved documentation"\n')
        self.git("add", "pyproject.toml")
        self.git("commit", "-qm", "Update project description")
        self.assertEqual(self.plan(), [])

    def test_tags_exact_bump_commit_even_when_push_has_later_work(self):
        bump = self.commit_version("1.1.0")
        later = self.commit_work()
        planned, = self.plan()
        self.assertEqual(planned, release.Release("1.1.0", bump, "1.0.0"))
        self.assertNotEqual(planned.commit, later)

    def test_multiple_bumps_are_ordered_and_keep_previous_release(self):
        first = self.commit_version("1.1.0")
        second = self.commit_version("1.2.0")
        self.assertEqual(self.plan(), [release.Release("1.1.0", first, "1.0.0"),
                                      release.Release("1.2.0", second, "1.1.0")])

    def test_merge_releases_main_commit_introducing_the_version(self):
        self.git("checkout", "-qb", "feature")
        self.commit_version("1.1.0")
        self.git("checkout", "-q", "main")
        self.commit_work()
        self.git("merge", "--no-ff", "-qm", "Merge version bump", "feature")
        self.assertEqual(self.plan()[0].commit, self.git("rev-parse", "HEAD"))

    def test_development_versions_wait_for_final_release(self):
        self.commit_version("1.1.0.dev0")
        self.assertEqual(self.plan(), [])
        final = self.commit_version("1.1.0")
        self.assertEqual(self.plan(), [release.Release("1.1.0", final, "1.0.0")])

    def test_prereleases_are_not_published(self):
        for version in ("1.1.0a1", "1.1.0b1", "1.1.0rc1"):
            self.commit_version(version)
        self.assertEqual(self.plan(), [])

    def test_decreasing_or_reused_version_fails(self):
        self.commit_version("0.9.0")
        with self.assertRaisesRegex(ValueError, "increase"):
            self.plan()

    def test_lockfile_must_match_at_the_bump_commit(self):
        self.commit_version("1.1.0", locked="1.0.0")
        with self.assertRaisesRegex(ValueError, "uv.lock"):
            self.plan()

    def test_existing_tag_must_point_to_the_bump_commit(self):
        self.commit_version("1.1.0")
        self.git("tag", "1.1.0", self.baseline)
        with self.assertRaisesRegex(ValueError, "different commit"):
            self.plan()
        self.assertEqual(release.tag_commit(self.root, "1.1.0"), self.baseline)

    def test_baseline_is_required_and_must_be_an_ancestor(self):
        with self.assertRaisesRegex(ValueError, "Baseline"):
            release.plan_releases(self.root, "9.0.0")
        self.git("checkout", "--orphan", "unrelated")
        self.git("commit", "-qm", "Unrelated history")
        with self.assertRaises(subprocess.CalledProcessError):
            self.plan()

    def test_direct_commits_appear_in_notes(self):
        work = self.commit_work("Fix [preview] <labels>")
        self.commit_version("1.1.0")
        notes = release.commit_notes(self.root, self.plan()[0], "example/FIScH")
        self.assertIn(r"Fix \[preview\] \<labels\>", notes)
        self.assertIn(work, notes)
        self.assertIn("compare/1.0.0...1.1.0", notes)

    def test_publish_creates_annotated_tag_and_generated_notes(self):
        commit = self.commit_version("1.1.0")
        github = FakeGitHub()
        release.publish_release(self.root, self.plan()[0], github)
        self.assertEqual(self.git("cat-file", "-t", "refs/tags/1.1.0"), "tag")
        remote_commit = subprocess.check_output([
            "git", "--git-dir", str(self.remote), "rev-parse", "1.1.0^{commit}"], text=True).strip()
        self.assertEqual(remote_commit, commit)
        saved = github.releases["1.1.0"]
        self.assertEqual(saved["name"], "FIScH 1.1.0")
        self.assertFalse(saved["draft"])
        self.assertFalse(saved["prerelease"])
        self.assertIn("Commit summary", saved["body"])
        self.assertIn("GitHub release notes", saved["body"])

    def test_retry_preserves_existing_release_and_edited_notes(self):
        self.commit_version("1.1.0")
        github = FakeGitHub()
        planned, = self.plan()
        release.publish_release(self.root, planned, github)
        github.releases["1.1.0"]["body"] = "Manually edited notes"
        github.calls.clear()
        release.publish_release(self.root, planned, github)
        self.assertEqual(github.releases["1.1.0"]["body"], "Manually edited notes")
        self.assertFalse(any(method == "POST" for method, _, _ in github.calls))

    def test_retry_after_tag_push_finishes_missing_release(self):
        self.commit_version("1.1.0")
        github = FakeGitHub()
        github.fail_publish = True
        with self.assertRaisesRegex(RuntimeError, "Temporary"):
            release.publish_release(self.root, self.plan()[0], github)
        first_tag = self.git("rev-parse", "refs/tags/1.1.0")
        release.publish_release(self.root, self.plan()[0], github)
        self.assertEqual(self.git("rev-parse", "refs/tags/1.1.0"), first_tag)
        self.assertIn("1.1.0", github.releases)

    def test_older_release_does_not_replace_newer_latest(self):
        self.commit_version("1.1.0")
        github = FakeGitHub()
        github.latest = "2.0.0"
        release.publish_release(self.root, self.plan()[0], github)
        self.assertEqual(github.releases["1.1.0"]["make_latest"], "false")
        self.assertEqual(github.latest, "2.0.0")

    def test_existing_draft_is_not_silently_published(self):
        self.commit_version("1.1.0")
        self.git("tag", "1.1.0")
        github = FakeGitHub()
        github.releases["1.1.0"] = {"draft": True}
        with self.assertRaisesRegex(ValueError, "manual review"):
            release.publish_release(self.root, self.plan()[0], github)

    def test_only_404_is_treated_as_missing(self):
        github = release.GitHub("example/FIScH", "test-token")
        for status in (401, 403, 500):
            error = HTTPError("https://api.github.com", status, "Failure", {}, None)
            with patch.object(release, "urlopen", side_effect=error):
                with self.assertRaisesRegex(RuntimeError, str(status)):
                    github.request("GET", "releases/latest", missing_ok=True)
        error = HTTPError("https://api.github.com", 404, "Missing", {}, None)
        with patch.object(release, "urlopen", side_effect=error):
            self.assertIsNone(github.request("GET", "releases/latest", missing_ok=True))


if __name__ == "__main__":
    unittest.main()
