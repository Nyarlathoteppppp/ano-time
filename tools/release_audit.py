#!/usr/bin/env python3
"""Check tracked release files for accidental secrets and private artefacts.

This is deliberately a release-time tool, not part of AnoTime's runtime.  It
only reads files Git considers tracked, never reads Keychain or ignored user
configuration, and never prints a matched secret value.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable


SECRET_PATTERNS = {
    "OpenAI-compatible key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "Google API key": re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    "Groq key": re.compile(r"\bgsk_[A-Za-z0-9_-]{20,}\b"),
    "Cerebras key": re.compile(r"\bcsk-[A-Za-z0-9_-]{20,}\b"),
    "Cloudflare token": re.compile(r"\bcfat_[A-Za-z0-9_-]{20,}\b"),
}

PRIVATE_RELEASE_PATHS = {
    "config.ini",
    "provider_profiles.json",
}
PRIVATE_PREFIXES = ("transcripts/", "logs/")
TEXT_SUFFIXES = {
    ".applescript", ".ini", ".json", ".md", ".plist", ".py", ".sh",
    ".swift", ".toml", ".txt", ".yml", ".yaml",
}


@dataclass(frozen=True)
class AuditFinding:
    path: str
    line: int | None
    category: str

    def describe(self) -> str:
        position = f":{self.line}" if self.line is not None else ""
        return f"{self.path}{position}: {self.category}"


def tracked_paths(root: Path) -> list[str]:
    """Return Git-tracked paths without consulting ignored private files."""
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Not a readable Git repository: {root}")
    return [
        item.decode("utf-8", errors="replace")
        for item in result.stdout.split(b"\0")
        if item
    ]


def is_private_release_path(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/")
    return (
        normalized in PRIVATE_RELEASE_PATHS
        or normalized.startswith(PRIVATE_PREFIXES)
    )


def _read_text(path: Path) -> Iterable[str]:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return ()
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ()


def audit_paths(root: Path, relative_paths: Iterable[str]) -> list[AuditFinding]:
    """Audit a supplied tracked-file list; exposed separately for tests."""
    findings: list[AuditFinding] = []
    for relative_path in relative_paths:
        normalized = relative_path.replace("\\", "/")
        if is_private_release_path(normalized):
            findings.append(AuditFinding(normalized, None, "private release file"))
            continue
        for line_number, line in enumerate(_read_text(root / normalized), start=1):
            for category, pattern in SECRET_PATTERNS.items():
                if pattern.search(line):
                    findings.append(AuditFinding(normalized, line_number, category))
    return findings


def audit_repository(root: Path) -> list[AuditFinding]:
    return audit_paths(root, tracked_paths(root))


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    root = Path(arguments[0] if arguments else ".").resolve()
    findings = audit_repository(root)
    if not findings:
        print("Release audit passed: no tracked private files or key-shaped secrets.")
        return 0
    print("Release audit failed. Rotate any exposed key before publishing:")
    for finding in findings:
        print(f"- {finding.describe()}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
