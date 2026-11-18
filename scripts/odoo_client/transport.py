"""HTTP for both protocols, on stdlib urllib.

urllib honors HTTPS_PROXY, which Claude cloud VMs require for every outbound
request; xmlrpc.client does not, which is why XML-RPC isn't used.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import __version__
from .errors import OdooError

USER_AGENT = f"odoo_cloud_tasks/{__version__}"
RETRIES = 2
BACKOFF_SECONDS = (1.0, 3.0)
RETRY_STATUSES = frozenset({500, 502, 503, 504})


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Leave the redirect to the HTTP error handler. API credentials belong to the configured endpoint.
        return None


def build_opener():
    context = ssl.create_default_context()
    if not os.environ.get("SSL_CERT_FILE"):
        for name in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
            path = os.environ.get(name, "")
            if path and os.path.isfile(path):
                context.load_verify_locations(cafile=path)
                break
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), _NoRedirects())


class Response:
    def __init__(self, status, headers, body):
        self.status = status
        self.headers = {str(k).lower(): v for k, v in (headers or {}).items()}
        self.body = body or b""

    def json(self):
        return json.loads(self.body.decode("utf-8"))

    def json_or_none(self):
        try:
            return self.json()
        except (ValueError, UnicodeDecodeError):
            return None

    def is_odoo_error(self) -> bool:
        data = self.json_or_none()
        return isinstance(data, dict) and any(k in data for k in ("error", "name", "message"))


def _read_error_body(exc) -> bytes:
    try:
        return exc.read() or b""
    except Exception:
        return b""


class Transport:
    def __init__(self, base_url, timeout, opener=None, sleep=time.sleep):
        self.base_url = base_url
        self.host = urlsplit(base_url).hostname or base_url
        self.timeout = timeout
        self.opener = opener or build_opener()
        self.sleep = sleep

    def request(self, method, path, payload=None, headers=None) -> Response:
        data = None
        all_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            all_headers["Content-Type"] = "application/json; charset=utf-8"
        all_headers.update(headers or {})
        url = self.base_url + path

        for attempt in range(RETRIES + 1):
            last_try = attempt == RETRIES
            request = urllib.request.Request(url, data=data, headers=all_headers, method=method)
            try:
                with self.opener.open(request, timeout=self.timeout) as resp:
                    return Response(resp.status, resp.headers, resp.read())
            except urllib.error.HTTPError as exc:
                if 300 <= exc.code < 400:
                    exc.close()
                    raise OdooError(
                        f"Odoo returned a redirect (HTTP {exc.code}). Set ODOO_URL to the final HTTPS address.",
                        status=exc.code,
                    ) from None
                response = Response(exc.code, exc.headers, _read_error_body(exc))
                if exc.code == 403 and str(response.headers.get("x-deny-reason", "")).lower() == "host_not_allowed":
                    raise self._host_not_allowed() from None
                if exc.code in RETRY_STATUSES and not response.is_odoo_error() and not last_try:
                    self._wait(attempt)
                    continue
                return response
            except urllib.error.URLError as exc:
                reason = exc.reason
                text = str(reason)
                # A refused proxy CONNECT surfaces only as this message; its headers are not available.
                if "Tunnel connection failed: 403" in text:
                    raise self._host_not_allowed() from None
                if isinstance(reason, ssl.SSLError):
                    raise OdooError(
                        f"The TLS certificate check failed for {self.host} ({text}). "
                        "Odoo needs a valid HTTPS certificate for this host name."
                    ) from None
                if isinstance(reason, (socket.timeout, TimeoutError)):
                    raise self._timed_out() from None
                if last_try:
                    raise OdooError(
                        f"Could not reach Odoo at {self.host} ({text}). "
                        "Check ODOO_URL and the cloud environment's network access."
                    ) from None
                self._wait(attempt)
            except (socket.timeout, TimeoutError):
                raise self._timed_out() from None
            except (ConnectionError, http.client.HTTPException) as exc:
                if last_try:
                    raise OdooError(f"The connection to {self.host} failed ({type(exc).__name__}: {exc}).") from None
                self._wait(attempt)
        raise OdooError(f"Could not reach Odoo at {self.host}.")

    def unexpected(self, response, path) -> OdooError:
        status = response.status
        if status == 404:
            message = (
                f"Odoo answered HTTP 404 at {path}. ODOO_URL must be just the Odoo address "
                "(for example https://mycompany.example.com), without /odoo or /web."
            )
        elif 200 <= status < 300:
            message = (
                f"{self.host} did not return JSON. ODOO_URL must point at the Odoo server itself; "
                "a website or firewall in front of it may block the API."
            )
        else:
            message = f"Odoo answered HTTP {status} at {path}."
        return OdooError(message, status=status)

    def _wait(self, attempt: int) -> None:
        self.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])

    def _host_not_allowed(self) -> OdooError:
        return OdooError(
            f"The Claude cloud environment's network access doesn't allow {self.host} — add it under "
            "Network access → Limited → Allowed domains. With a network secret (Odoo 19), the secret's "
            f"allowed website must be exactly {self.host}.",
            status=403,
        )

    def _timed_out(self) -> OdooError:
        return OdooError(
            f"Odoo did not answer within {self.timeout:g} seconds. Narrow the query "
            "(shorter period, fewer fields, a limit) or raise ODOO_TIMEOUT."
        )
