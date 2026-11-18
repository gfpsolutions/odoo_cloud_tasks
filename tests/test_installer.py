import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"
needs_bash_and_curl = pytest.mark.skipif(
    not (shutil.which("bash") and shutil.which("curl")), reason="needs bash and curl")


def listed_files():
    block = re.search(r"^FILES=\((.*?)^\)", INSTALL.read_text(), re.S | re.M).group(1)
    return sorted(line.strip() for line in block.splitlines() if line.strip() and not line.strip().startswith("#"))


def runtime_files():
    scripts = [
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "scripts").rglob("*.py")
        if "__pycache__" not in p.parts
    ]
    return sorted(scripts + [".claude/skills/odoo/SKILL.md", "cloud/claude-settings.json"])


def install(tmp_path, base_url):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"allow": ["Bash(ls *)"]}}))
    dest = tmp_path / "opt" / "odoo_cloud_tasks"
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "ODOO_CLOUD_TASKS_BASE_URL": base_url,
        "ODOO_CLOUD_TASKS_DEST": str(dest),
    }
    result = subprocess.run(
        ["bash", str(INSTALL), "example-owner/odoo_cloud_tasks", "v9.9.9"],
        env=env, capture_output=True, text=True, timeout=120)
    return result, home, dest


def test_installer_lists_every_runtime_file():
    assert listed_files() == runtime_files()


@needs_bash_and_curl
def test_installer_sets_up_the_toolkit_and_claude_files(tmp_path):
    result, home, dest = install(tmp_path, ROOT.as_uri())
    assert result.returncode == 0, result.stderr
    assert "installed in" in result.stdout

    claude_md = (home / ".claude" / "CLAUDE.md").read_text()
    assert claude_md.startswith("<!-- odoo_cloud_tasks v9.9.9")
    assert f"python3 {dest}/scripts/odoo.py check" in claude_md
    assert "python3 scripts/odoo.py" not in claude_md
    assert "name: odoo" not in claude_md

    settings = json.loads((home / ".claude" / "settings.json").read_text())
    assert settings["permissions"]["allow"][0] == "Bash(ls *)"
    assert f"Bash(python3 {dest}/scripts/odoo.py *)" in settings["permissions"]["allow"]
    assert {"Bash(printenv *)", "Read(//proc/**)", "Bash(git push *)"} <= set(settings["permissions"]["deny"])

    version = subprocess.run([sys.executable, str(dest / "scripts" / "odoo.py"), "--version"],
                             capture_output=True, text=True)
    assert version.stdout.startswith("odoo_cloud_tasks ")


@needs_bash_and_curl
def test_installer_fails_and_installs_nothing_when_a_file_is_missing(tmp_path):
    partial = tmp_path / "partial"
    shutil.copytree(ROOT / "scripts", partial / "scripts")
    result, home, dest = install(tmp_path, partial.as_uri())
    assert result.returncode != 0
    assert not dest.exists()
    assert not (home / ".claude" / "CLAUDE.md").exists()
