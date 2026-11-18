import os

from secret_scan import ROOT, host_allowed, problems, scan

# Test inputs are assembled at run time so this file doesn't trip the scan itself.
VAR = "ODOO"
HTTPS = "https:" + "//"


def test_no_secrets_committed():
    report = scan()
    assert not report, "\n".join(report)


def test_pre_commit_hook_is_executable():
    assert os.access(ROOT / ".githooks" / "pre-commit", os.X_OK)


def test_scanner_catches_hex_keys():
    assert problems("key: " + "ab12" * 10)
    assert not problems("short hex " + "ab12" * 5)


def test_scanner_allows_only_documentation_and_placeholder_hosts():
    assert problems(f"see {HTTPS}acme.odoo.com/web")
    assert problems(f"see {HTTPS}erp.acme.fr")
    assert not problems(f"see {HTTPS}www.odoo.com/documentation/19.0/")
    assert not problems(f"see {HTTPS}odoo.example.com and {HTTPS}raw.githubusercontent.com/x/y/v1/install.sh")
    assert host_allowed("code.claude.com") and not host_allowed("example.com.attacker.net")


def test_scanner_catches_real_looking_assignments():
    assert problems(f"{VAR}_DB=acme-prod")
    assert problems(f'"{VAR}_LOGIN": "jane@acme.fr"')
    assert problems(f'monkeypatch.setenv("{VAR}_API_KEY", "realkey123")')
    assert not problems(f"{VAR}_URL={HTTPS}<odoo-host>")
    assert not problems(f'"{VAR}_DB": "example-db"')
    assert not problems(f'"{VAR}_API_KEY": ""')
