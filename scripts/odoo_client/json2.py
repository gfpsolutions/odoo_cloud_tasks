"""Odoo 19+ External JSON-2 API: POST /json/2/<model>/<method> with named parameters.

In a Claude cloud session this client sends no Authorization header: Anthropic's
agent proxy adds the key, stored as a network secret, after the request leaves
the VM. Each Odoo instance documents its own models and methods at /doc.
"""
from __future__ import annotations

from .errors import OdooError
from .jsonrpc import legacy_order
from .safety import check_call

SECRET_HINT = (
    " The network secret is missing, expired or not matched to this host. "
    "Odoo 19 keys last at most 3 months."
)
LOCAL_KEY_HINT = " ODOO_API_KEY was rejected: it may be wrong or expired."


class Json2Backend:
    protocol = "json2"

    def __init__(self, config, transport):
        self.config = config
        self.transport = transport
        self._uid = None

    def _headers(self, *, authenticated: bool) -> dict:
        headers = {}
        if self.config.db:
            headers["X-Odoo-Database"] = self.config.db
        if authenticated and self.config.api_key and not self.config.remote:
            headers["Authorization"] = f"bearer {self.config.api_key}"
        return headers

    def call(self, model, method, params, enforce_allowlist=True):
        check_call(model, method, self.config.allowed_models, enforce_allowlist)
        path = f"/json/2/{model}/{method}"
        response = self.transport.request("POST", path, params, self._headers(authenticated=True))
        if 200 <= response.status < 300:
            try:
                return response.json()
            except (ValueError, UnicodeDecodeError):
                raise self.transport.unexpected(response, path) from None
        raise self._error(response, path)

    def _error(self, response, path) -> OdooError:
        status = response.status
        data = response.json_or_none()
        name = ""
        if isinstance(data, dict) and (data.get("name") or data.get("message")):
            name = data.get("name") or ""
            short = name.rsplit(".", 1)[-1]
            message = data.get("message") or ""
            text = f"Odoo answered HTTP {status}: {short}: {message}" if short else f"Odoo answered HTTP {status}: {message}"
        elif status == 404:
            text = (
                f"Odoo answered HTTP 404 at {path}. JSON-2 needs Odoo 19 or later (use ODOO_PROTOCOL=jsonrpc "
                "for Odoo 18), and ODOO_URL must be just the Odoo address."
            )
        else:
            text = f"Odoo answered HTTP {status} at {path}."
        if status == 401:
            text += LOCAL_KEY_HINT if self.config.api_key and not self.config.remote else SECRET_HINT
        return OdooError(text, status=status, name=name)

    def version(self) -> dict:
        response = self.transport.request("GET", "/web/version", headers=self._headers(authenticated=False))
        data = response.json_or_none()
        if response.status == 200 and isinstance(data, dict) and data.get("version"):
            return {"server_version": data.get("version"), "server_version_info": data.get("version_info")}
        if 200 <= response.status < 300:
            raise self.transport.unexpected(response, "/web/version")
        raise self._error(response, "/web/version")

    def current_user_id(self) -> int:
        if self._uid is None:
            context = self.call("res.users", "context_get", {}, enforce_allowlist=False)
            uid = context.get("uid") if isinstance(context, dict) else None
            if not uid:
                raise OdooError("Odoo didn't say which user the API key belongs to (res.users.context_get returned no uid).")
            self._uid = uid
        return self._uid

    def search_read(self, model, domain, fields, limit, offset, order, context, enforce_allowlist=True):
        params = {"domain": domain, "offset": offset, "context": context}
        if limit:
            params["limit"] = limit
        if fields:
            params["fields"] = fields
        if order:
            params["order"] = order
        return self.call(model, "search_read", params, enforce_allowlist)

    def search_count(self, model, domain, context):
        return self.call(model, "search_count", {"domain": domain, "context": context})

    def read(self, model, ids, fields, context, enforce_allowlist=True):
        params = {"ids": ids, "context": context}
        if fields:
            params["fields"] = fields
        return self.call(model, "read", params, enforce_allowlist)

    def fields_get(self, model, attributes, context):
        return self.call(model, "fields_get", {"attributes": attributes, "context": context})

    def group(self, model, domain, groupby, aggregates, order, limit, context):
        params = {"domain": domain, "groupby": groupby, "aggregates": list(aggregates) + ["__count"], "context": context}
        if order:
            params["order"] = order
        if limit:
            params["limit"] = limit
        try:
            return "formatted", self.call(model, "formatted_read_group", params)
        except OdooError as exc:
            if exc.status != 404:
                raise
        legacy = {"domain": domain, "fields": list(aggregates), "groupby": groupby, "lazy": False, "context": context}
        if order:
            legacy["orderby"] = legacy_order(order, aggregates)
        if limit:
            legacy["limit"] = limit
        return "read_group", self.call(model, "read_group", legacy)
