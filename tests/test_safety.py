import json

import pytest

from fake_odoo import KEY
from odoo_client.errors import SafetyError
from odoo_client.safety import (
    ALLOWED_METHODS,
    BLOCKED_MODELS,
    check_method,
    check_model,
    check_order,
    output_path,
    parse_aggregates,
    parse_domain,
    parse_groupby,
    parse_ids,
    scrub,
)


@pytest.mark.parametrize("method", [
    "create", "write", "unlink", "copy", "action_post", "action_confirm", "button_draft",
    "message_post", "name_create", "sudo", "_read_group", "execute", "toggle_active",
])
def test_writes_and_private_methods_are_rejected(method):
    with pytest.raises(SafetyError, match="read-only"):
        check_method(method)


@pytest.mark.parametrize("method", sorted(ALLOWED_METHODS))
def test_read_methods_are_allowed(method):
    check_method(method)


def test_allowlist_is_exactly_the_read_methods():
    assert ALLOWED_METHODS == {
        "search_read", "search_count", "search", "read", "read_group",
        "formatted_read_group", "fields_get", "name_search", "context_get",
    }


@pytest.mark.parametrize("model", sorted(BLOCKED_MODELS))
def test_security_models_are_always_blocked(model):
    with pytest.raises(SafetyError, match="always blocked"):
        check_model(model, enforce_allowlist=False)


def test_model_allowlist_applies_to_metadata_too():
    allowed = ("sale.order",)
    check_model("sale.order", allowed)
    for other in ("account.move", "ir.model", "ir.model.fields", "ir.module.module"):
        with pytest.raises(SafetyError, match="ODOO_ALLOWED_MODELS"):
            check_model(other, allowed)
    check_model("account.move", allowed, enforce_allowlist=False)


@pytest.mark.parametrize("model", ["Sale.Order", "sale order", "", "../etc", "sale.order;drop"])
def test_invalid_model_names(model):
    with pytest.raises(SafetyError, match="not a valid Odoo model name"):
        check_model(model)


@pytest.mark.parametrize("domain", [
    [],
    [["state", "=", "posted"]],
    [["state", "in", ["posted", "cancel"]], ["invoice_date", ">=", "2026-10-01"]],
    ["|", ["state", "=", "draft"], ["state", "=", "posted"]],
    ["!", ["active", "=", False]],
    ["&", "|", ["a", "=", 1], ["b", "=", 2], ["c", "=", 3]],
    [["partner_id", "any", [["is_company", "=", True]]]],
    [["location_id.usage", "=", "internal"]],
])
def test_valid_domains(domain):
    assert parse_domain(json.dumps(domain)) == domain


@pytest.mark.parametrize("text, message", [
    ("state = posted", "not valid JSON"),
    ('{"state": "posted"}', "must be a JSON list"),
    ('[["state", "==", "posted"]]', "unsupported operator"),
    ('[["partner_id", "any!", []]]', "unsupported operator"),
    ('[["state", "="]]', "each condition"),
    ('["|", ["state", "=", "draft"]]', "two conditions"),
    ('["!"]', "followed by a condition"),
    ('["xor", ["a", "=", 1], ["b", "=", 2]]', "unknown logical operator"),
    ('[[1, "=", 1]]', "must be a field name"),
])
def test_invalid_domains(text, message):
    with pytest.raises(SafetyError, match=message):
        parse_domain(text)


def test_output_paths_must_stay_under_out(tmp_path):
    assert output_path("out/report.csv") == (tmp_path / "out" / "report.csv").resolve()
    assert output_path("out/2026/report.csv").parent.is_dir()
    for bad in ("report.csv", "out", "out/../report.csv", str(tmp_path / "elsewhere.csv"), "/etc/report.csv"):
        with pytest.raises(SafetyError, match="inside out/"):
            output_path(bad)


def test_scrub_removes_the_key_and_anything_shaped_like_one():
    hex_key = "ab12" * 10
    text = scrub(f"key {KEY} and {hex_key} in a traceback", (KEY,))
    assert KEY not in text and hex_key not in text
    assert text.count("[REDACTED]") == 2
    assert scrub("nothing secret here", (KEY,)) == "nothing secret here"


def test_argument_parsers():
    assert parse_ids("12, 15,40") == [12, 15, 40]
    assert parse_groupby("partner_id,invoice_date:month") == ["partner_id", "invoice_date:month"]
    assert parse_aggregates("amount_total:sum, amount_residual:max") == ["amount_total:sum", "amount_residual:max"]
    assert check_order("amount_total:sum desc, __count desc") == "amount_total:sum desc, __count desc"
    for bad_call in (
        lambda: parse_ids("12,abc"),
        lambda: parse_ids("0"),
        lambda: parse_groupby(""),
        lambda: parse_groupby("partner_id;drop"),
        lambda: parse_aggregates("amount_total"),
        lambda: check_order("name; delete"),
    ):
        with pytest.raises(SafetyError):
            bad_call()
