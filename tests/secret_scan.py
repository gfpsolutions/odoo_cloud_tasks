#!/usr/bin/env python3
"""Fails when a file that would be committed contains an Odoo API key, an Odoo
address, a database name or a login.

    python3 tests/secret_scan.py            # tracked and new (not ignored) files
    python3 tests/secret_scan.py --staged   # what the next commit contains (pre-commit hook)

Reports only file and line, never the matched text.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]

HEX_KEY = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{40}(?![0-9A-Fa-f])")
URL = re.compile(r"https?://[^\s<>\"'`)\]]*")
CHECKED = r"ODOO_(?:API_KEY|LOGIN|URL|DB)"
ASSIGNMENTS = (
    re.compile(rf"\b({CHECKED})\s*=\s*[\"']?([^\s\"'#]*)"),
    re.compile(rf"[\"']({CHECKED})[\"']\s*:\s*[\"']([^\"']*)[\"']"),
    re.compile(rf"setenv\(\s*[\"']({CHECKED})[\"']\s*,\s*[\"']([^\"']*)[\"']"),
)
# Documentation and placeholder hosts only. Subdomains of odoo.com are client databases.
DOC_HOSTS = {"odoo.com", "www.odoo.com", "claude.ai", "code.claude.com", "docs.claude.com", "raw.githubusercontent.com"}
PLACEHOLDER_DOMAINS = ("example.com", "example.org", "example.net")
PLACEHOLDER_WORDS = ("example", "fake", "placeholder", "dummy")
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "out"}


def host_allowed(host: str) -> bool:
    host = host.lower().rstrip(".")
    if host in DOC_HOSTS:
        return True
    return any(host == domain or host.endswith("." + domain) for domain in PLACEHOLDER_DOMAINS)


def is_placeholder(value: str) -> bool:
    value = value.strip().lower()
    return not value or value[0] in "<${" or "<" in value or any(word in value for word in PLACEHOLDER_WORDS)


def problems(text: str) -> list:
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        if HEX_KEY.search(line):
            found.append((number, "40-character hex string (the format of Odoo API keys)"))
        for url in URL.findall(line):
            try:
                host = urlsplit(url).hostname or ""
            except ValueError:
                host = ""
            if host and not host_allowed(host):
                found.append((number, f"URL with a non-placeholder host ({host})"))
        for pattern in ASSIGNMENTS:
            for match in pattern.finditer(line):
                if not is_placeholder(match.group(2)):
                    found.append((number, f"real-looking value for {match.group(1)}"))
    return found


def _git(*args) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True).stdout


def candidate_files(staged: bool):
    """Yields (relative path, text) for every file that would be committed."""
    try:
        listing = _git("ls-files", "-z", "--cached", *(() if staged else ("--others", "--exclude-standard")))
        paths = [p for p in listing.decode("utf-8").split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        staged = False
        paths = [
            p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
            if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(ROOT).parts)
        ]
    for path in paths:
        try:
            raw = _git("show", f":{path}") if staged else (ROOT / path).read_bytes()
        except (OSError, subprocess.CalledProcessError):
            continue
        try:
            yield path, raw.decode("utf-8")
        except UnicodeDecodeError:
            continue


def scan(staged: bool = False) -> list:
    return [f"{path}:{number}: {why}" for path, text in candidate_files(staged) for number, why in problems(text)]


def main(argv=None) -> int:
    report = scan(staged="--staged" in (sys.argv[1:] if argv is None else argv))
    if not report:
        return 0
    print("Possible secret or client-specific value in files to be committed:", file=sys.stderr)
    for line in report:
        print(f"  {line}", file=sys.stderr)
    print("Keep real values on the Claude cloud environment; use <placeholders> or example.com in files.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
