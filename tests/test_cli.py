import csv
import io
import json
from pathlib import Path

import pytest

from fake_odoo import KEY, FakeOdoo, OdooFault
from odoo_client import cli
from odoo_client import client as client_module
from odoo_client.safety import BLOCKED_MODELS

COMMANDS = ["check", "guide", "models", "fields", "search", "count", "group", "read", "period"]


@pytest.mark.parametrize("argv", [["--help"]] + [[command, "--help"] for command in COMMANDS])
def test_help_is_available_for_every_command(argv, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(argv)
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: odoo.py")
    if argv[0] != "--help":
        assert len(out.splitlines()) > 3


def test_missing_configuration_names_the_variable_and_the_claude_environment(run):
    code, out, err = run(["check"], FakeOdoo())
    assert code == 1 and out == ""
    assert "ODOO_URL is not set" in err
    assert "Claude cloud environment" in err


def test_all_needs_an_output_file(run, jsonrpc_env):
    odoo = FakeOdoo()
    code, out, err = run(["search", "res.partner", "--all"], odoo)
    assert code == 1
    assert "--all needs --csv" in err
    assert odoo.requests == []


@pytest.mark.parametrize("path", ["report.csv", "out", "out/../report.csv", "/tmp/report.csv"])
def test_output_files_outside_out_are_rejected(run, jsonrpc_env, path):
    odoo = FakeOdoo()
    code, out, err = run(["search", "res.partner", "--csv", path], odoo)
    assert code == 1
    assert "inside out/" in err
    assert odoo.requests == []


def test_all_pages_through_records_up_to_the_cap(run, jsonrpc_env, monkeypatch):
    monkeypatch.setattr(client_module, "PAGE_SIZE", 2)
    monkeypatch.setattr(client_module, "HARD_CAP", 5)
    odoo = FakeOdoo()
    odoo.records["res.partner"] = [{"id": i, "name": f"Partner {i}"} for i in range(1, 8)]
    odoo.counts.pop("res.partner")
    code, out, err = run(["search", "res.partner", "--fields", "name", "--all", "--csv", "out/partners.csv"], odoo)
    assert code == 0, err
    data = json.loads(out)
    assert data["total_matching"] == 7 and data["returned"] == 5
    assert data["capped"] is True and "first 5 of 7" in data["warnings"][0]
    assert "warning:" in err
    assert data["file"] == "out/partners.csv" and "records" not in data
    assert len(data["sample"]) == 5
    pages = [(c["offset"], c["limit"], c["order"]) for c in odoo.calls_to("search_read")]
    assert pages == [(0, 2, "id"), (2, 2, "id"), (4, 1, "id")]
    rows = list(csv.DictReader(io.StringIO(Path("out/partners.csv").read_text(encoding="utf-8-sig"))))
    assert [row["name"] for row in rows] == [f"Partner {i}" for i in range(1, 6)]


def test_csv_flattens_many2one_and_neutralizes_formulas(run, jsonrpc_env):
    odoo = FakeOdoo()
    odoo.records["account.move"] = [{
        "id": 1, "name": '=HYPERLINK("http://example.com")', "partner_id": [3, "Azure Interior"],
        "amount_total_signed": -5.0, "is_move_sent": True,
    }]
    fields = "name,partner_id,amount_total_signed,is_move_sent"
    code, out, err = run(["search", "account.move", "--fields", fields, "--csv", "out/moves.csv"], odoo)
    assert code == 0, err
    raw = Path("out/moves.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    row = next(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    assert row["name"].startswith("'=")
    assert row["partner_id"] == "Azure Interior" and row["partner_id.id"] == "3"
    assert row["amount_total_signed"] == "-5.0"
    assert row["is_move_sent"] == "true"


def test_csv_escapes_final_text_after_flattening(run, jsonrpc_env):
    odoo = FakeOdoo()
    odoo.records["res.partner"] = [{
        "id": 1, "tags": ["=1+1", "second"], "contact": [7, "  +10"],
        "@label": "regular text", "balance": -10,
    }]
    path = Path("out/partners.csv")
    code, _, err = run(["read", "res.partner", "--ids", "1", "--csv", str(path)], odoo)
    assert code == 0, err
    with path.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["tags"] == "'=1+1;second"
    assert row["contact"] == "'  +10"
    assert row["'@label"] == "regular text"
    assert row["balance"] == "-10"


def test_group_can_be_written_to_json(run, jsonrpc_env):
    odoo = FakeOdoo()
    odoo.groups[("account.move", "read_group")] = [{"partner_id": [3, "Azure Interior"], "__count": 4}]
    code, out, err = run(["group", "account.move", "--groupby", "partner_id", "--json", "out/groups.json"], odoo)
    assert code == 0, err
    data = json.loads(out)
    assert data["group_count"] == 1 and data["file"] == "out/groups.json"
    saved = json.loads(Path("out/groups.json").read_text(encoding="utf-8"))
    assert saved == [{"partner_id": {"id": 3, "name": "Azure Interior"}, "__count": 4}]


def test_fields_lists_selection_options(run, jsonrpc_env):
    odoo = FakeOdoo()
    code, out, err = run(["fields", "account.move", "--filter", "stat"], odoo)
    assert code == 0, err
    data = json.loads(out)
    assert data["fields"] == [{
        "name": "state", "label": "Status", "type": "selection", "required": True,
        "options": [["draft", "Draft"], ["posted", "Posted"], ["cancel", "Cancelled"]],
    }]
    code, out, err = run(["fields", "account.move", "--filter", "payment"], odoo)
    assert json.loads(out)["fields"][0]["stored"] is False


def test_models_hides_blocked_models(run, jsonrpc_env):
    odoo = FakeOdoo()
    odoo.records["ir.model"] = [
        {"id": 1, "model": "sale.order", "name": "Sales Order"},
        {"id": 2, "model": "ir.config_parameter", "name": "System Parameter"},
    ]
    code, out, err = run(["models", "--filter", "o"], odoo)
    assert code == 0, err
    assert json.loads(out)["models"] == [{"model": "sale.order", "name": "Sales Order"}]
    domain = odoo.calls_to("search_read")[-1]["domain"]
    assert domain == [
        ["transient", "=", False], "|", ["model", "ilike", "o"], ["name", "ilike", "o"],
        ["model", "not in", sorted(BLOCKED_MODELS)],
    ]


def test_blocked_models_never_reach_odoo(run, jsonrpc_env):
    odoo = FakeOdoo()
    code, out, err = run(["search", "ir.config_parameter", "--fields", "key,value"], odoo)
    assert code == 1
    assert "always blocked" in err
    assert not any(r["body"]["params"]["method"] == "execute_kw" for r in odoo.requests)


def test_allowed_models_restrict_queries_but_not_the_check(run, jsonrpc_env, monkeypatch):
    monkeypatch.setenv("ODOO_ALLOWED_MODELS", "sale.order, res.partner")
    odoo = FakeOdoo()
    code, out, err = run(["count", "account.move"], odoo)
    assert code == 1 and "not in ODOO_ALLOWED_MODELS" in err
    code, out, err = run(["count", "sale.order"], odoo)
    assert code == 0, err
    code, out, err = run(["check"], odoo)
    assert code == 0, err
    assert json.loads(out)["model_restriction"] == ["sale.order", "res.partner"]


@pytest.mark.parametrize("domain, message", [
    ("[[state = posted]]", "not valid JSON"),
    ('[["state", "equals", "posted"]]', "unsupported operator"),
    ('["|", ["state", "=", "draft"]]', "two conditions"),
])
def test_domains_are_validated_before_any_call(run, jsonrpc_env, domain, message):
    odoo = FakeOdoo()
    code, out, err = run(["count", "account.move", "--domain", domain], odoo)
    assert code == 1 and message in err
    assert odoo.requests == []


def test_guide_lists_customizations_and_marks_unreadable_sections(run, jsonrpc_env):
    odoo = FakeOdoo()
    odoo.records["ir.module.module"] = [
        {"id": 1, "name": "sale", "shortdesc": "Sales", "author": "Odoo S.A."},
        {"id": 2, "name": "acme_sale_ext", "shortdesc": "Acme Sales Extensions", "author": "GFP Solutions"},
    ]
    odoo.records["ir.model.fields"] = [
        {"id": 1, "model": "sale.order", "name": "x_studio_region", "field_description": "Region",
         "ttype": "selection", "relation": False},
        {"id": 2, "model": "ir.config_parameter", "name": "x_hidden", "field_description": "Hidden",
         "ttype": "char", "relation": False},
    ]
    odoo.faults[("ir.model", "search_read")] = OdooFault(
        "odoo.exceptions.AccessError", "You are not allowed to access 'Models' (ir.model) records.")
    code, out, err = run(["guide"], odoo)
    assert code == 0, err
    data = json.loads(out)
    assert data["major_version"] == 18
    assert data["non_standard_modules"] == [
        {"module": "acme_sale_ext", "name": "Acme Sales Extensions", "author": "GFP Solutions"}]
    assert data["custom_fields_by_model"] == {
        "sale.order": [{"field": "x_studio_region", "label": "Region", "type": "selection"}]}
    assert "not allowed" in data["custom_models"]["unavailable"]


def test_read_returns_normalized_records(run, jsonrpc_env):
    odoo = FakeOdoo()
    odoo.records["account.move"] = [
        {"id": 1, "name": "INV/1", "partner_id": [3, "Azure Interior"]},
        {"id": 2, "name": "INV/2", "partner_id": False},
    ]
    code, out, err = run(["read", "account.move", "--ids", "2", "--fields", "name,partner_id"], odoo)
    assert code == 0, err
    assert json.loads(out)["records"] == [{"id": 2, "name": "INV/2", "partner_id": None}]


def test_stdout_never_contains_the_key(run, jsonrpc_env):
    odoo = FakeOdoo()
    odoo.records["account.move"] = [{"id": 1, "name": "INV/1", "narration": f"someone pasted {KEY} here"}]
    code, out, err = run(["search", "account.move", "--fields", "name,narration"], odoo)
    assert code == 0, err
    assert KEY not in out and "[REDACTED]" in out


@pytest.mark.parametrize("file_format", ["csv", "json"])
def test_exports_redact_keys_in_records_and_nested_fields(run, jsonrpc_env, file_format):
    odoo = FakeOdoo()
    odoo.records["account.move"] = [{
        "id": 1,
        "narration": f"pasted: {KEY}",
        "details": {"items": [KEY], KEY: "value"},
    }]
    path = Path(f"out/report.{file_format}")
    code, out, err = run(["search", "account.move", f"--{file_format}", str(path)], odoo)
    assert code == 0, err
    raw = path.read_text(encoding="utf-8-sig")
    assert KEY not in raw and KEY not in out
    expected = {"items": ["[REDACTED]"], "[REDACTED]": "value"}
    assert json.loads(out)["sample"][0]["details"] == expected
    if file_format == "csv":
        record = next(csv.DictReader(io.StringIO(raw)))
        assert json.loads(record["details"]) == expected
    else:
        record = json.loads(raw)[0]
        assert record["details"] == expected
    assert record["narration"] == "pasted: [REDACTED]"
