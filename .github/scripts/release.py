"""Release stable FIScH version bumps after the existing 4.1.0 release.

The default invocation previews the plan without network calls or changes.
Publishing uses the Actions token and checkout credentials; no extra key is needed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASELINE_TAG = "4.1.0"
STABLE_VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
DEVELOPMENT_VERSION = re.compile(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+|\.dev\d+)")


@dataclass(frozen=True)
class Release:
    version: str
    commit: str
    previous: str


def git(root: Path, *arguments: str) -> str:
    """Pass Git arguments directly, never through a shell."""
    return subprocess.check_output(["git", *arguments], cwd=root, text=True).strip()


def version_key(version: str) -> tuple[int, ...]:
    if not STABLE_VERSION.fullmatch(version):
        raise ValueError(f"Expected a stable X.Y.Z version, got {version!r}.")
    return tuple(int(part) for part in version.split("."))


def project_version(root: Path, commit: str) -> str:
    return tomllib.loads(git(root, "show", f"{commit}:pyproject.toml"))["project"]["version"]


def tag_commit(root: Path, tag: str) -> str | None:
    result = subprocess.run(["git", "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"],
                            cwd=root, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def plan_releases(root: Path, baseline: str = BASELINE_TAG, head: str = "HEAD") -> list[Release]:
    """Find exact bump commits on main's first-parent history, including batched pushes."""
    version_key(baseline)
    start = tag_commit(root, baseline)
    if start is None or project_version(root, start) != baseline:
        raise ValueError(f"Baseline tag {baseline} is missing or its package version does not match.")
    git(root, "merge-base", "--is-ancestor", start, head)
    commits = git(root, "rev-list", "--first-parent", "--reverse", f"{start}..{head}", "--", "pyproject.toml")
    releases: list[Release] = []
    previous = baseline
    for commit in commits.splitlines():
        old = project_version(root, f"{commit}^1")
        new = project_version(root, commit)
        if new == old:
            continue
        if DEVELOPMENT_VERSION.fullmatch(new):
            continue
        if version_key(new) <= version_key(previous):
            raise ValueError(f"Version must increase: {previous} -> {new} at {commit[:8]}.")
        old_base = re.match(r"\d+\.\d+\.\d+", old)
        if old_base is None or version_key(new) < version_key(old_base.group()):
            raise ValueError(f"Version decreased: {old} -> {new} at {commit[:8]}.")
        lock = tomllib.loads(git(root, "show", f"{commit}:uv.lock"))
        locked = [package["version"] for package in lock["package"] if package["name"] == "fisch"]
        if locked != [new]:
            raise ValueError(f"uv.lock must also declare FIScH {new} at {commit[:8]}; run uv lock before committing the bump.")
        existing = tag_commit(root, new)
        if existing is not None and existing != commit:
            raise ValueError(f"Tag {new} already points to a different commit; published tags will not be moved.")
        releases.append(Release(new, commit, previous))
        previous = new
    return releases


def commit_notes(root: Path, release: Release, repository: str) -> str:
    """Include direct commits, which GitHub's PR-based generated notes can omit."""
    lines = git(root, "log", "--first-parent", "--reverse", "--format=%H%x00%s",
                f"{release.previous}..{release.commit}").splitlines()
    notes = [f"Changes since {release.previous}.", "", "## Commit summary", ""]
    for line in lines[:50]:
        sha, subject = line.split("\0", 1)
        # Keep commit subjects literal rather than interpreting embedded HTML/Markdown.
        subject = re.sub(r"([\\`*_{}\[\]<>])", r"\\\1", subject)
        notes.append(f"- {subject} ([{sha[:7]}](https://github.com/{repository}/commit/{sha}))")
    if len(lines) > 50:
        notes.append(f"- Plus {len(lines) - 50} additional commits; see the full comparison below.")
    notes.extend(["", f"[Full comparison](https://github.com/{repository}/compare/{release.previous}...{release.version})"])
    return "\n".join(notes)


class GitHub:
    def __init__(self, repository: str, token: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Expected an owner/repository name.")
        self.repository = repository
        self.token = token

    def request(self, method: str, path: str, data: dict | None = None,
                *, missing_ok: bool = False) -> dict | None:
        """Treat only a real 404 as missing; authentication/network errors must fail."""
        request = Request(f"https://api.github.com/repos/{self.repository}/{path}",
                          method=method,
                          data=json.dumps(data).encode() if data is not None else None,
                          headers={"Authorization": f"Bearer {self.token}",
                                   "Accept": "application/vnd.github+json",
                                   "Content-Type": "application/json",
                                   "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code == 404 and missing_ok:
                return None
            raise RuntimeError(f"GitHub {method} {path} failed with HTTP {error.code}.") from error


def publish_release(root: Path, release: Release, github: GitHub) -> None:
    """Publish once, preserving existing tags, edited notes, and newer Latest releases."""
    existing_tag = tag_commit(root, release.version)
    if existing_tag is not None and existing_tag != release.commit:
        raise ValueError(f"Tag {release.version} points to a different commit.")
    existing_release = github.request("GET", f"releases/tags/{release.version}", missing_ok=True)
    if existing_release is not None:
        if existing_tag is None or existing_release.get("draft") or existing_release.get("prerelease"):
            raise ValueError(f"Release {release.version} already exists but needs manual review.")
        print(f"Keeping existing release {release.version}.")
        return
    if existing_tag is None:
        git(root, "-c", "user.name=github-actions[bot]",
            "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "tag", "-a", release.version, release.commit, "-m", f"FIScH {release.version}")
    # Also push an existing matching tag, to recover from an interrupted local tag/push.
    git(root, "push", "origin", f"refs/tags/{release.version}")
    generated = github.request("POST", "releases/generate-notes", {
        "tag_name": release.version, "previous_tag_name": release.previous,
    })
    assert generated is not None
    latest = github.request("GET", "releases/latest", missing_ok=True)
    latest_tag = latest["tag_name"] if latest else None
    make_latest = latest_tag is None or (STABLE_VERSION.fullmatch(latest_tag) is not None
                                         and version_key(release.version) > version_key(latest_tag))
    notes = commit_notes(root, release, github.repository)
    if generated.get("body"):
        notes += "\n\n" + generated["body"]
    published = github.request("POST", "releases", {
        "tag_name": release.version, "name": f"FIScH {release.version}", "body": notes,
        "draft": False, "prerelease": False, "make_latest": "true" if make_latest else "false",
    })
    assert published is not None
    print(f"Published {published['html_url']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true", help="Create tags and releases; default is a dry run.")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    releases = plan_releases(root)
    repository = os.environ.get("GITHUB_REPOSITORY", "BennyGinger/fisch")
    if not releases:
        print("No new stable FIScH version bumps to release.")
        return
    github = GitHub(repository, os.environ["GH_TOKEN"]) if arguments.publish else None
    for release in releases:
        print(f"FIScH {release.version}: {release.commit} (previous release: {release.previous})")
        if github is None:
            print(commit_notes(root, release, repository))
        else:
            publish_release(root, release, github)


if __name__ == "__main__":
    main()
