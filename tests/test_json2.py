"""Odoo 19 over /json/2, with the key as a network secret added by Anthropic's proxy."""
import json

from fake_odoo import KEY, FakeOdoo

GROUP_19 = [{
    "partner_id": [3, "Azure Interior"],
    "invoice_date:month": ["2026-10-01", "octobre 2026"],
    "amount_residual_signed:sum": 1250.0,
    "__count": 2,
    "__extra_domain": [],
}]
GROUP_18_STYLE = [{
    "partner_id": [3, "Azure Interior"],
    "invoice_date:month": "octobre 2026",
    "amount_residual_signed": 1250.0,
    "__count": 2,
    "__range": {"invoice_date:month": {"from": "2026-10-01", "to": "2026-11-01"}},
}]
EXPECTED_GROUP = {
    "partner_id": {"id": 3, "name": "Azure Interior"},
    "invoice_date:month": {"start": "2026-10-01", "label": "octobre 2026"},
    "amount_residual_signed:sum": 1250.0,
    "__count": 2,
}
GROUP_ARGS = [
    "group", "account.move", "--groupby", "partner_id,invoice_date:month",
    "--aggregates", "amount_residual_signed:sum", "--order", "amount_residual_signed:sum desc",
]


def test_cloud_requests_carry_no_authorization_header(run, json2_env):
    odoo = FakeOdoo("json2", version="19.0")
    code, out, err = run(["check"], odoo)
    assert code == 0, err
    data = json.loads(out)
    assert data["auth_mode"] == "network secret, injected by proxy"
    assert data["server_version"] == "19.0"
    assert data["user"]["login"] == "bot@example.com"
    assert odoo.requests, "expected HTTP requests"
    assert all("authorization" not in r["headers"] for r in odoo.requests)
    assert all(r["headers"].get("x-odoo-database") == "example-db" for r in odoo.requests)
    assert "/json/2/res.users/context_get" in [r["path"] for r in odoo.requests]


def test_api_key_is_refused_in_the_cloud(run, json2_env, monkeypatch):
    monkeypatch.setenv("ODOO_API_KEY", KEY)
    odoo = FakeOdoo("json2", version="19.0")
    code, out, err = run(["check"], odoo)
    assert code == 1
    assert "ODOO_API_KEY must not be set for json2" in err
    assert KEY not in err
    assert odoo.requests == []


def test_local_development_sends_the_key_as_bearer(run, json2_env, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE")
    monkeypatch.setenv("ODOO_API_KEY", KEY)
    odoo = FakeOdoo("json2", version="19.0")
    odoo.proxy_injects = False
    code, out, err = run(["check"], odoo)
    assert code == 0, err
    version_headers, = [r["headers"] for r in odoo.requests if r["path"] == "/web/version"]
    assert "authorization" not in version_headers
    assert version_headers["x-odoo-database"] == "example-db"
    api_requests = [r for r in odoo.requests if r["path"].startswith("/json/2/")]
    assert api_requests and all(r["headers"].get("authorization") == f"bearer {KEY}" for r in api_requests)
    assert KEY not in out


def test_401_explains_the_network_secret(run, json2_env):
    odoo = FakeOdoo("json2", version="19.0")
    odoo.proxy_injects = False
    code, out, err = run(["count", "res.partner"], odoo)
    assert code == 1
    assert "HTTP 401" in err
    assert "network secret is missing, expired or not matched to this host" in err
    assert "3 months" in err


def test_methods_get_named_parameters(run, json2_env):
    odoo = FakeOdoo("json2", version="19.0")
    odoo.records["account.move"] = [{"id": 1, "name": "INV/2026/0001", "partner_id": [3, "Azure Interior"]}]
    code, out, err = run([
        "search", "account.move", "--domain", '[["state", "=", "posted"]]', "--fields", "name,partner_id",
        "--limit", "5", "--order", "invoice_date desc",
    ], odoo)
    assert code == 0, err
    assert json.loads(out)["records"][0]["partner_id"] == {"id": 3, "name": "Azure Interior"}
    body = next(r["body"] for r in odoo.requests if r["path"] == "/json/2/account.move/search_read")
    assert body["domain"] == [["state", "=", "posted"]]
    assert body["fields"] == ["name", "partner_id"]
    assert body["limit"] == 5 and body["offset"] == 0
    assert body["order"] == "invoice_date desc"
    assert body["context"]["allowed_company_ids"] == [1, 2]


def test_group_uses_formatted_read_group(run, json2_env):
    odoo = FakeOdoo("json2", version="19.0")
    odoo.groups[("account.move", "formatted_read_group")] = GROUP_19
    code, out, err = run(GROUP_ARGS, odoo)
    assert code == 0, err
    assert json.loads(out)["groups"] == [EXPECTED_GROUP]
    call = odoo.calls_to("formatted_read_group")[0]
    assert call["groupby"] == ["partner_id", "invoice_date:month"]
    assert call["aggregates"] == ["amount_residual_signed:sum", "__count"]
    assert call["order"] == "amount_residual_signed:sum desc"


def test_group_falls_back_to_read_group(run, json2_env):
    odoo = FakeOdoo("json2", version="19.0")
    odoo.missing.add(("account.move", "formatted_read_group"))
    odoo.groups[("account.move", "read_group")] = GROUP_18_STYLE
    code, out, err = run(GROUP_ARGS, odoo)
    assert code == 0, err
    assert json.loads(out)["groups"] == [EXPECTED_GROUP]
    call = odoo.calls_to("read_group")[0]
    assert call["fields"] == ["amount_residual_signed:sum"]
    assert call["lazy"] is False
    assert call["orderby"] == "amount_residual_signed desc"


def test_odoo_18_server_explains_that_json2_needs_19(run, json2_env):
    code, out, err = run(["check"], FakeOdoo("jsonrpc"))
    assert code == 1
    assert "JSON-2 needs Odoo 19 or later" in err


def test_unprocessable_parameters_are_reported(run, json2_env):
    from fake_odoo import OdooFault

    odoo = FakeOdoo("json2", version="19.0")
    odoo.faults[("account.move", "search_count")] = OdooFault(
        "werkzeug.exceptions.UnprocessableEntity", "got an unexpected keyword argument 'foo'", status=422)
    code, out, err = run(["count", "account.move"], odoo)
    assert code == 1
    assert "HTTP 422: UnprocessableEntity: got an unexpected keyword argument 'foo'" in err
