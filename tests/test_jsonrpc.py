"""Odoo 18 over /jsonrpc, with the key in an environment variable."""
import json

import pytest

from fake_odoo import KEY, FakeOdoo, OdooFault
from odoo_client.client import OdooClient
from odoo_client.config import load_config
from odoo_client.errors import SafetyError

INVOICE = {
    "id": 1,
    "name": "INV/2026/0001",
    "partner_id": [3, "Azure Interior"],
    "invoice_date": "2026-10-03",
    "invoice_origin": False,
    "is_move_sent": False,
    "amount_total_signed": 1200.0,
}


def rpc_bodies(odoo, method):
    return [r["body"]["params"] for r in odoo.requests if r["body"]["params"]["method"] == method]


def test_check_reports_the_connection_without_the_key(run, jsonrpc_env):
    odoo = FakeOdoo()
    code, out, err = run(["check"], odoo)
    assert code == 0, err
    data = json.loads(out)
    assert data["protocol"] == "jsonrpc"
    assert data["auth_mode"] == "environment variable"
    assert data["server_version"] == "18.0+e"
    assert data["database"] == "example-db"
    assert data["user"] == {"id": 7, "name": "Claude Reports", "login": "bot@example.com"}
    assert data["companies"] == [{"id": 1, "name": "Example Co"}, {"id": 2, "name": "Example Spain"}]
    assert data["test"] == {"model": "res.partner", "search_count": 42}
    assert "warnings" not in data
    assert KEY not in out and KEY not in err


def test_authenticates_once_and_queries_all_companies(run, jsonrpc_env):
    odoo = FakeOdoo()
    odoo.counts["account.move"] = 5
    code, out, err = run(["count", "account.move", "--domain", '[["state", "=", "posted"]]'], odoo)
    assert code == 0, err
    assert json.loads(out)["count"] == 5
    assert len(rpc_bodies(odoo, "authenticate")) == 1
    count_call = odoo.calls_to("search_count")[0]
    assert count_call["domain"] == [["state", "=", "posted"]]
    assert count_call["context"] == {"tz": "Europe/Paris", "lang": "fr_FR", "allowed_company_ids": [1, 2]}


@pytest.mark.parametrize("method", ["create", "write", "unlink", "copy", "action_post", "message_post", "_read_group"])
def test_write_methods_never_reach_odoo(jsonrpc_env, method):
    odoo = FakeOdoo()
    client = OdooClient.from_config(load_config(), opener=odoo)
    with pytest.raises(SafetyError, match="read-only"):
        client.backend.call("account.move", method, [[1]], {})
    assert odoo.requests == []


def test_context_get_is_allowed(jsonrpc_env):
    odoo = FakeOdoo()
    client = OdooClient.from_config(load_config(), opener=odoo)
    assert client.backend.call("res.users", "context_get")["uid"] == 7


def test_rejected_login_does_not_echo_the_key(run, jsonrpc_env, monkeypatch):
    monkeypatch.setenv("ODOO_API_KEY", "wrong-fake-key-value")
    code, out, err = run(["check"], FakeOdoo())
    assert code == 1
    assert "Odoo rejected the login" in err
    assert "wrong-fake-key-value" not in err and out == ""


def test_odoo_error_text_is_scrubbed_and_traceback_dropped(run, jsonrpc_env):
    odoo = FakeOdoo()
    odoo.faults[("account.move", "search_count")] = OdooFault(
        "odoo.exceptions.UserError", f"Invalid domain near {KEY}", debug=f"Traceback (most recent call last): {KEY}")
    code, out, err = run(["count", "account.move"], odoo)
    assert code == 1
    assert "Odoo error [UserError]: Invalid domain near [REDACTED]" in err
    assert KEY not in err and "Traceback" not in err


def test_hex_shaped_key_is_scrubbed(run, jsonrpc_env, monkeypatch):
    hex_key = "ab12" * 10
    monkeypatch.setenv("ODOO_API_KEY", hex_key)
    odoo = FakeOdoo(key=hex_key)
    odoo.faults[("account.move", "search_count")] = OdooFault("odoo.exceptions.UserError", f"echo {hex_key}")
    code, out, err = run(["count", "account.move"], odoo)
    assert code == 1 and hex_key not in err


def test_unexpected_errors_print_no_traceback_or_key(run, jsonrpc_env):
    odoo = FakeOdoo()
    odoo.plan = [RuntimeError(f"boom with {KEY}")]
    code, out, err = run(["check"], odoo)
    assert code == 1
    assert "Unexpected error (RuntimeError)" in err
    assert KEY not in err and "Traceback" not in err


def test_access_errors_explain_the_rights(run, jsonrpc_env):
    odoo = FakeOdoo()
    odoo.faults[("hr.leave", "search_count")] = OdooFault(
        "odoo.exceptions.AccessError", "You are not allowed to access 'Time Off'.")
    code, out, err = run(["count", "hr.leave"], odoo)
    assert code == 1
    assert "[AccessError]" in err and "access rights" in err


def test_search_normalizes_many2one_and_empty_values(run, jsonrpc_env):
    odoo = FakeOdoo()
    odoo.records["account.move"] = [INVOICE]
    fields = "name,partner_id,invoice_date,invoice_origin,is_move_sent,amount_total_signed"
    code, out, err = run(["search", "account.move", "--fields", fields], odoo)
    assert code == 0, err
    data = json.loads(out)
    assert data["total_matching"] == 1 and data["returned"] == 1 and data["more_available"] is False
    record = data["records"][0]
    assert record["partner_id"] == {"id": 3, "name": "Azure Interior"}
    assert record["invoice_origin"] is None
    assert record["is_move_sent"] is False
    search = odoo.calls_to("search_read")[0]
    assert search["fields"] == fields.split(",") and search["limit"] == 200


def test_group_uses_read_group_and_normalizes(run, jsonrpc_env):
    odoo = FakeOdoo()
    odoo.groups[("account.move", "read_group")] = [
        {"partner_id": [3, "Azure Interior"], "invoice_date:month": "octobre 2026", "amount_residual_signed": 1250.0,
         "__count": 2, "__range": {"invoice_date:month": {"from": "2026-10-01", "to": "2026-11-01"}}, "__domain": []},
        {"partner_id": False, "invoice_date:month": False, "amount_residual_signed": 80.0, "__count": 1,
         "__range": {"invoice_date:month": False}, "__domain": []},
    ]
    code, out, err = run([
        "group", "account.move", "--groupby", "partner_id,invoice_date:month",
        "--aggregates", "amount_residual_signed:sum", "--order", "amount_residual_signed:sum desc",
    ], odoo)
    assert code == 0, err
    groups = json.loads(out)["groups"]
    assert groups[0] == {
        "partner_id": {"id": 3, "name": "Azure Interior"},
        "invoice_date:month": {"start": "2026-10-01", "label": "octobre 2026"},
        "amount_residual_signed:sum": 1250.0,
        "__count": 2,
    }
    assert groups[1]["partner_id"] is None and groups[1]["invoice_date:month"] is None
    call = odoo.calls_to("read_group")[0]
    assert call["fields"] == ["amount_residual_signed:sum"]
    assert call["groupby"] == ["partner_id", "invoice_date:month"]
    assert call["lazy"] is False
    assert call["orderby"] == "amount_residual_signed desc"


def test_date_group_without_granularity_means_month(run, jsonrpc_env):
    odoo = FakeOdoo()
    code, out, err = run(["group", "account.move", "--groupby", "invoice_date"], odoo)
    assert code == 0, err
    assert json.loads(out)["groupby"] == ["invoice_date:month"]
    assert odoo.calls_to("read_group")[0]["groupby"] == ["invoice_date:month"]


def test_check_recommends_json2_on_odoo_19(run, jsonrpc_env):
    code, out, err = run(["check"], FakeOdoo(version="19.0"))
    assert code == 0, err
    assert "switch to ODOO_PROTOCOL=json2" in json.loads(out)["warnings"][0]
