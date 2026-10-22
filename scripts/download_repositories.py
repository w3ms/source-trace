"""Select managed public GitHub repositories and build verified source archives."""

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile


ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")
REPOSITORY = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9-]*/[a-zA-Z0-9_.-]+\Z")
SCHEDULE_ANCHOR = date(2026, 10, 22)
SCHEDULE_INTERVAL_DAYS = 5
SCHEDULE_TIMEZONE = timezone(timedelta(hours=8))


def schedule_due(now=None):
    """Run every five local days, including across month/year boundaries."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Schedule timestamps must have a timezone")
    days = (now.astimezone(SCHEDULE_TIMEZONE).date() - SCHEDULE_ANCHOR).days
    return days >= 0 and days % SCHEDULE_INTERVAL_DAYS == 0


def select_for_event(registry, event_name, selection="all", ref="", now=None):
    due = event_name != "schedule" or schedule_due(now)
    matrix = select(registry, selection, ref) if due else {"include": []}
    return due, matrix


def git(*args, cwd=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_LFS_SKIP_SMUDGE="1")
    return subprocess.check_output(
        ["git", "-c", "protocol.file.allow=never", "-c", "protocol.ext.allow=never", *args],
        cwd=cwd, env=env, text=True,
    ).strip()


def validate_entry(identifier, entry):
    if not isinstance(identifier, str) or not ID.fullmatch(identifier) or identifier.lower() == "all":
        raise ValueError("Repository IDs must be 1-64 letters, digits, underscores or hyphens; 'all' is reserved")
    if not isinstance(entry, dict) or set(entry) - {"repository", "ref"}:
        raise ValueError("Each repository must contain only 'repository' and optional 'ref'")
    repository = entry.get("repository", "")
    if not isinstance(repository, str) or not REPOSITORY.fullmatch(repository):
        raise ValueError("repository must be a GitHub owner/repository name")
    if repository.split("/")[1] in (".", ".."):
        raise ValueError("Invalid repository name")
    ref = entry.get("ref", "")
    if not isinstance(ref, str):
        raise ValueError("ref must be a branch/tag string or empty for the default branch")
    if ref:
        if ref.startswith("-") or any(c in ref for c in "\r\n"):
            raise ValueError("Invalid branch or tag")
        git("check-ref-format", "refs/heads/" + ref)


def load_registry(path):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate configuration key: " + key)
            result[key] = value
        return result

    registry = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    if not isinstance(registry, dict) or not registry:
        raise ValueError("repositories.json must be a non-empty object")
    for identifier, entry in registry.items():
        validate_entry(identifier, entry)
    return registry


def select(registry, selection, ref=""):
    if not selection.strip():
        raise ValueError("Choose at least one repository ID or 'all'")
    identifiers = list(registry) if selection.strip().lower() == "all" else list(
        dict.fromkeys(item.strip() for item in selection.split(","))
    )
    if len(identifiers) > 256:
        raise ValueError("GitHub allows at most 256 matrix jobs per run; select a smaller batch")
    result = []
    for identifier in identifiers:
        if identifier not in registry:
            raise ValueError("Unknown repository ID: " + identifier)
        entry = dict(registry[identifier])
        if ref:
            entry["ref"] = ref
        validate_entry(identifier, entry)
        result.append({"id": identifier, "repository": entry["repository"], "ref": entry.get("ref", "")})
    return {"include": result}


def package(entry, output, full_history=False, submodules=True, include_lfs=False):
    identifier = entry["id"]
    validate_entry(identifier, {key: entry[key] for key in ("repository", "ref") if key in entry})
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="repository-download-") as directory:
        source = Path(directory) / identifier
        options = ["--single-branch"]
        if entry.get("ref"):
            options += ["--branch", entry["ref"]]
        if not full_history:
            options += ["--depth", "1"]
        git("clone", *options, "--", "https://github.com/" + entry["repository"] + ".git", str(source))
        if submodules:
            git("submodule", "update", "--init", "--recursive", cwd=source)
        if include_lfs:
            git("lfs", "fetch", "--all", cwd=source)
            git("lfs", "checkout", cwd=source)
            if submodules:
                git("submodule", "foreach", "--recursive", "git lfs fetch --all && git lfs checkout", cwd=source)
        git("fsck", "--full", cwd=source)
        if submodules:
            git("submodule", "foreach", "--recursive", "git fsck --full", cwd=source)
        commit = git("rev-parse", "HEAD", cwd=source)
        archive = output / (identifier + ".tar.gz")
        with tarfile.open(archive, "w:gz", dereference=False) as bundle:
            bundle.add(source, arcname=identifier)
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.getmember(identifier + "/.git/HEAD")
            bundle.getmember(identifier + "/.git/config")
        digest = hashlib.sha256()
        with archive.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        (output / "COMMIT.txt").write_text(commit + "\n", encoding="utf-8")
        (output / "SHA256SUMS.txt").write_text(digest.hexdigest() + "  " + archive.name + "\n", encoding="utf-8")
        metadata = dict(entry, commit=commit, full_history=full_history, submodules=submodules, include_lfs=include_lfs)
        (output / "SOURCE.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "select", "package"])
    parser.add_argument("--config", default="repositories.json")
    parser.add_argument("--output", default="output")
    args = parser.parse_args()
    if args.command == "validate":
        print("Validated {} repositories".format(len(load_registry(args.config))))
    elif args.command == "select":
        due, matrix = select_for_event(
            load_registry(args.config), os.environ.get("GITHUB_EVENT_NAME", ""),
            os.environ.get("REPOSITORIES", "all"), os.environ.get("REF_OVERRIDE", ""),
        )
        encoded = json.dumps(matrix, separators=(",", ":"))
        print(encoded)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
                stream.write("matrix=" + encoded + "\n")
                stream.write("should_run=" + str(due).lower() + "\n")
        if not due:
            print("Skipping downloads: today is between the scheduled five-day dates")
    else:
        package(
            json.loads(os.environ["REPOSITORY_ENTRY"]), args.output,
            full_history=os.environ.get("FULL_HISTORY") == "true",
            submodules=os.environ.get("SUBMODULES", "true") == "true",
            include_lfs=os.environ.get("INCLUDE_LFS") == "true",
        )


if __name__ == "__main__":
    main()
