import pytest

from fake_odoo import KEY
from odoo_client.config import AUTH_ENV, AUTH_LOCAL, AUTH_PROXY, JSON2_KEY_REFUSAL, load_config
from odoo_client.errors import ConfigError

ODOO_18 = {
    "ODOO_URL": "https://odoo.example.com/",
    "ODOO_PROTOCOL": "jsonrpc",
    "ODOO_DB": "example-db",
    "ODOO_LOGIN": "bot@example.com",
    "ODOO_API_KEY": KEY,
}
ODOO_19_CLOUD = {"ODOO_URL": "https://odoo.example.com", "ODOO_PROTOCOL": "json2", "CLAUDE_CODE_REMOTE": "true"}


def test_jsonrpc_config_and_defaults():
    config = load_config(ODOO_18)
    assert config.url == "https://odoo.example.com"
    assert config.auth_mode == AUTH_ENV
    assert config.timeout == 60
    assert config.tz == "Europe/Paris"
    assert config.allowed_models == ()
    assert KEY not in repr(config)


@pytest.mark.parametrize("name", ["ODOO_URL", "ODOO_PROTOCOL", "ODOO_DB", "ODOO_LOGIN", "ODOO_API_KEY"])
def test_jsonrpc_requires_each_variable(name):
    env = dict(ODOO_18)
    env[name] = "  "
    with pytest.raises(ConfigError) as error:
        load_config(env)
    assert f"{name} is not set" in str(error.value)
    assert "Claude cloud environment" in str(error.value)


def test_json2_uses_the_network_secret_and_needs_no_database():
    config = load_config(ODOO_19_CLOUD)
    assert config.auth_mode == AUTH_PROXY
    assert config.db == ""
    assert config.secrets == ()


def test_json2_refuses_an_api_key_in_the_cloud():
    with pytest.raises(ConfigError) as error:
        load_config({**ODOO_19_CLOUD, "ODOO_API_KEY": KEY})
    assert str(error.value) == JSON2_KEY_REFUSAL
    assert KEY not in str(error.value)


def test_json2_accepts_an_api_key_for_local_development():
    env = {**ODOO_19_CLOUD, "ODOO_API_KEY": KEY}
    del env["CLAUDE_CODE_REMOTE"]
    assert load_config(env).auth_mode == AUTH_LOCAL


@pytest.mark.parametrize("protocol, message", [
    ("xmlrpc", "isn't supported: use jsonrpc"),
    ("soap", "must be jsonrpc"),
])
def test_unsupported_protocols(protocol, message):
    with pytest.raises(ConfigError, match=message):
        load_config({**ODOO_18, "ODOO_PROTOCOL": protocol})


def test_protocol_is_case_insensitive():
    assert load_config({**ODOO_18, "ODOO_PROTOCOL": "JSONRPC"}).protocol == "jsonrpc"


@pytest.mark.parametrize("url, message", [
    ("odoo.example.com", "starting with https://"),
    ("http://odoo.example.com", "starting with https://"),
    ("ftp://odoo.example.com", "starting with https://"),
    ("https://someone:secret@odoo.example.com", "must not contain a login or password"),
])
def test_url_validation(url, message):
    with pytest.raises(ConfigError, match=message):
        load_config({**ODOO_18, "ODOO_URL": url})


@pytest.mark.parametrize("value", ["abc", "0", "601"])
def test_timeout_validation(value):
    with pytest.raises(ConfigError, match="ODOO_TIMEOUT"):
        load_config({**ODOO_18, "ODOO_TIMEOUT": value})


def test_timeout_and_time_zone_overrides():
    config = load_config({**ODOO_18, "ODOO_TIMEOUT": "120", "ODOO_TZ": "America/New_York"})
    assert config.timeout == 120
    assert config.tz == "America/New_York"


def test_time_zone_validation():
    with pytest.raises(ConfigError, match="ODOO_TZ"):
        load_config({**ODOO_18, "ODOO_TZ": "Mars/Olympus_Mons"})


def test_allowed_models_parsing():
    config = load_config({**ODOO_18, "ODOO_ALLOWED_MODELS": "sale.order, res.partner  account.move,"})
    assert config.allowed_models == ("sale.order", "res.partner", "account.move")
