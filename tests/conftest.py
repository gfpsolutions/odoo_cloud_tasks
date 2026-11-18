import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "scripts"))
sys.path.insert(0, str(TESTS))

from fake_odoo import KEY  # noqa: E402
from odoo_client import cli  # noqa: E402

ODOO_VARIABLES = (
    "ODOO_URL", "ODOO_PROTOCOL", "ODOO_DB", "ODOO_LOGIN", "ODOO_API_KEY",
    "ODOO_TIMEOUT", "ODOO_TZ", "ODOO_ALLOWED_MODELS", "CLAUDE_CODE_REMOTE",
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for name in ODOO_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def jsonrpc_env(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://odoo.example.com")
    monkeypatch.setenv("ODOO_PROTOCOL", "jsonrpc")
    monkeypatch.setenv("ODOO_DB", "example-db")
    monkeypatch.setenv("ODOO_LOGIN", "bot@example.com")
    monkeypatch.setenv("ODOO_API_KEY", KEY)


@pytest.fixture
def json2_env(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://odoo.example.com")
    monkeypatch.setenv("ODOO_PROTOCOL", "json2")
    monkeypatch.setenv("ODOO_DB", "example-db")
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")


@pytest.fixture
def run(capsys):
    """Run the CLI against a fake Odoo; returns (exit code, stdout, stderr)."""

    def _run(argv, odoo=None):
        code = cli.main(argv, opener=odoo, sleep=lambda seconds: None)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run
