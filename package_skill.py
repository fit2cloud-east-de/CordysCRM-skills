#!/usr/bin/env python3
"""Build the locked Cordys CRM skill release archive."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path


LOCKED_VERSION = "1.2.7"
SKILL_PREFIX = "skills/cordys-crm-f2c/"
ARCHIVE_ROOT = "cordys-crm-f2c/"


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"package error: {message}")


def json_version(path: Path) -> str:
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    version = document.get("version")
    if not isinstance(version, str) or not version:
        fail(f"{path} has no non-empty string version")
    return version


def skill_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^\s*version:\s*["\']([^"\']+)["\']\s*$', text, re.MULTILINE)
    if not match:
        fail(f"{path} has no metadata version")
    return match.group(1)


def tracked_skill_files(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--", f"{SKILL_PREFIX}**"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    files = [line for line in result.stdout.splitlines() if line]
    if not files:
        fail("git returned no tracked skill files")
    unexpected = [item for item in files if not item.startswith(SKILL_PREFIX)]
    if unexpected:
        fail(f"unexpected tracked path: {unexpected[0]}")
    return files


def validate_versions(repo: Path) -> None:
    versions = {
        "skills/cordys-crm-f2c/registry.json": json_version(
            repo / "skills" / "cordys-crm-f2c" / "registry.json"
        ),
        ".workbuddy-plugin/plugin.json": json_version(
            repo / ".workbuddy-plugin" / "plugin.json"
        ),
        "skills/cordys-crm-f2c/SKILL.md": skill_version(
            repo / "skills" / "cordys-crm-f2c" / "SKILL.md"
        ),
    }
    wrong = {path: value for path, value in versions.items() if value != LOCKED_VERSION}
    if wrong:
        details = ", ".join(f"{path}={value}" for path, value in wrong.items())
        fail(
            f"version is locked to {LOCKED_VERSION}; unauthorized version change detected: "
            f"{details}"
        )


def validate_archive(path: Path, expected_count: int) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != expected_count:
            fail(f"archive has {len(names)} entries, expected {expected_count}")
        if len(names) != len(set(names)):
            fail("archive contains duplicate entries")
        if any(not name.startswith(ARCHIVE_ROOT) for name in names):
            fail(f"every archive entry must start with {ARCHIVE_ROOT}")
        forbidden = [
            name
            for name in names
            if name.endswith("/.env")
            or "/Python/" in f"/{name}"
            or "python_install_" in name
            or "__pycache__" in name
            or name.endswith((".pyc", ".pyo"))
        ]
        if forbidden:
            fail(f"archive contains forbidden file: {forbidden[0]}")
        broken = archive.testzip()
        if broken:
            fail(f"archive CRC check failed at {broken}")


def main() -> int:
    if len(sys.argv) != 1:
        fail("this version-locked packager accepts no arguments")

    repo = Path(__file__).resolve().parent
    validate_versions(repo)
    files = tracked_skill_files(repo)
    output = repo.parent / f"cordys-crm-v{LOCKED_VERSION}.zip"

    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for tracked_path in files:
            source = repo / tracked_path
            archive_name = tracked_path[len("skills/") :]
            archive.write(source, archive_name)

    validate_archive(output, len(files))
    print(
        json.dumps(
            {
                "archive": str(output),
                "version": LOCKED_VERSION,
                "files": len(files),
                "root": ARCHIVE_ROOT,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
