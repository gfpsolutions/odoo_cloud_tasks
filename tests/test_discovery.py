import json

import pytest

from fake_odoo import FakeOdoo


@pytest.fixture(params=["jsonrpc", "json2"])
def restricted_odoo(request, monkeypatch):
    request.getfixturevalue(request.param + "_env")
    monkeypatch.setenv("ODOO_ALLOWED_MODELS", "account.move, ir.config_parameter")
    return FakeOdoo(server=request.param, version="19.0" if request.param == "json2" else "18.0")


@pytest.mark.parametrize("command", [
    ["search", "ir.model", "--fields", "model"],
    ["read", "ir.model.fields", "--ids", "1"],
    ["count", "ir.module.module"],
    ["fields", "ir.model"],
    ["group", "ir.model.fields", "--groupby", "ttype"],
])
def test_ordinary_queries_cannot_use_discovery_exceptions(run, restricted_odoo, command):
    code, out, err = run(command, restricted_odoo)
    assert code == 1 and not out and "not in ODOO_ALLOWED_MODELS" in err
    assert restricted_odoo.requests == []


@pytest.mark.parametrize("command", ["models", "guide"])
def test_discovery_scopes_requests_and_returned_rows(run, restricted_odoo, command):
    odoo = restricted_odoo
    odoo.records["ir.model"] = [
        {"model": "account.move", "name": "Invoice"},
        {"model": "other.model", "name": "Other"},
        {"model": "ir.config_parameter", "name": "Parameters"},
    ]
    odoo.records["ir.model.fields"] = [
        {"model": "account.move", "name": "x_link", "ttype": "many2one", "relation": "other.model"},
        {"model": "other.model", "name": "x_other", "ttype": "char"},
        {"model": "ir.config_parameter", "name": "x_param", "ttype": "char"},
    ]
    code, out, err = run([command], odoo)
    assert code == 0, err
    result = json.loads(out)
    expected = [{"model": "account.move", "name": "Invoice"}]
    searches = {model: params for model, method, params in odoo.calls if method == "search_read"}
    if command == "models":
        assert result["models"] == expected
        assert set(searches) == {"ir.model"}
    else:
        assert result["custom_models"] == expected
        assert result["custom_fields_by_model"] == {
            "account.move": [{"field": "x_link", "label": "", "type": "many2one"}],
        }
        assert "unavailable" in result["non_standard_modules"]
        assert set(searches) == {"ir.model", "ir.model.fields"}
        assert searches["ir.model.fields"]["fields"] == ["model", "name", "field_description", "ttype", "relation"]
    assert searches["ir.model"]["fields"] == ["model", "name"]
    assert all(["model", "in", ["account.move"]] in params["domain"] for params in searches.values())


def test_field_discovery_hides_excluded_relation_names(run, restricted_odoo):
    code, out, err = run(["fields", "account.move", "--filter", "partner_id"], restricted_odoo)
    assert code == 0, err
    assert json.loads(out)["fields"] == [{"name": "partner_id", "label": "Customer", "type": "many2one"}]


def test_guide_can_list_modules_when_explicitly_allowed(run, restricted_odoo, monkeypatch):
    monkeypatch.setenv("ODOO_ALLOWED_MODELS", "account.move, ir.module.module")
    restricted_odoo.records["ir.module.module"] = [{"name": "custom", "shortdesc": "Custom", "author": "Example"}]
    code, out, err = run(["guide"], restricted_odoo)
    assert code == 0, err
    assert json.loads(out)["non_standard_modules"] == [{"module": "custom", "name": "Custom", "author": "Example"}]
