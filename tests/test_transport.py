import socket
import ssl
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

from fake_odoo import FakeOdoo
from odoo_client.errors import OdooError
from odoo_client.transport import Transport


def make_transport(odoo, sleeps=None):
    sleep = sleeps.append if sleeps is not None else (lambda seconds: None)
    return Transport("https://odoo.example.com", 30, opener=odoo, sleep=sleep)


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("method, path", [("GET", "/web/version"), ("POST", "/jsonrpc")])
def test_opener_stops_at_first_redirect(status, method, path):
    with patch.object(urllib.request.HTTPSHandler, "https_open") as send:
        redirect = send.return_value
        redirect.code = status
        redirect.info.return_value = {"location": "https://other.example.com/api"}
        transport = Transport("https://odoo.example.com", 30)
        with pytest.raises(OdooError, match="redirect") as error:
            transport.request(method, path)
        assert error.value.status == status
        send.assert_called_once()


def test_blocked_host_header_gives_the_allowlist_hint():
    odoo = FakeOdoo()
    odoo.plan = [(403, "Forbidden", {"x-deny-reason": "host_not_allowed"})]
    with pytest.raises(OdooError) as error:
        make_transport(odoo).request("POST", "/jsonrpc", {})
    assert "network access doesn't allow odoo.example.com" in str(error.value)
    assert "Allowed domains" in str(error.value)


def test_refused_proxy_tunnel_gives_the_allowlist_hint_without_retrying():
    odoo = FakeOdoo()
    odoo.plan = [urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden"))]
    with pytest.raises(OdooError, match="Allowed domains"):
        make_transport(odoo).request("POST", "/jsonrpc", {})
    assert len(odoo.requests) == 1


def test_gateway_errors_are_retried_with_backoff():
    odoo = FakeOdoo()
    odoo.plan = [(503, "<html>busy</html>", {}), (502, "bad gateway", {}), (200, {"ok": True}, {})]
    sleeps = []
    response = make_transport(odoo, sleeps).request("GET", "/web/version")
    assert response.status == 200 and response.json() == {"ok": True}
    assert sleeps == [1.0, 3.0]
    assert len(odoo.requests) == 3


def test_odoo_errors_are_not_retried():
    odoo = FakeOdoo()
    odoo.plan = [(500, {"name": "builtins.ValueError", "message": "Invalid field"}, {})]
    response = make_transport(odoo).request("POST", "/json/2/res.partner/search_read", {})
    assert response.status == 500
    assert len(odoo.requests) == 1


def test_connection_errors_are_retried_then_reported():
    odoo = FakeOdoo()
    odoo.plan = [urllib.error.URLError(ConnectionRefusedError(61, "Connection refused")) for _ in range(3)]
    with pytest.raises(OdooError, match="Could not reach Odoo at odoo.example.com"):
        make_transport(odoo).request("POST", "/jsonrpc", {})
    assert len(odoo.requests) == 3


def test_timeouts_are_reported_without_retrying():
    odoo = FakeOdoo()
    odoo.plan = [socket.timeout("timed out")]
    with pytest.raises(OdooError, match="did not answer within 30 seconds"):
        make_transport(odoo).request("POST", "/jsonrpc", {})
    assert len(odoo.requests) == 1


def test_certificate_failures_are_explained():
    odoo = FakeOdoo()
    odoo.plan = [urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verify failed"))]
    with pytest.raises(OdooError, match="TLS certificate check failed for odoo.example.com"):
        make_transport(odoo).request("POST", "/jsonrpc", {})


def test_requests_carry_user_agent_and_json_content_type():
    odoo = FakeOdoo()
    odoo.plan = [(200, {"result": 1}, {})]
    make_transport(odoo).request("POST", "/jsonrpc", {"a": 1}, {"X-Odoo-Database": "example-db"})
    headers = odoo.requests[0]["headers"]
    assert headers["user-agent"].startswith("odoo_cloud_tasks/")
    assert headers["content-type"] == "application/json; charset=utf-8"
    assert headers["x-odoo-database"] == "example-db"
    assert odoo.requests[0]["body"] == {"a": 1}
