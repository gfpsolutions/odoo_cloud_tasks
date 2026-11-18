"""Odoo 18 external API over /jsonrpc.

The API key travels inside the request body, so Anthropic's proxy can't inject
it: on Odoo 18 it has to be an environment variable (ODOO_API_KEY).
"""
from __future__ import annotations

import itertools

from .errors import OdooError
from .safety import check_call

_HINTS = {
    "AccessDenied": " Check ODOO_DB, ODOO_LOGIN and ODOO_API_KEY on the Claude cloud environment.",
    "AccessError": " The Odoo user behind the key can't read this data; adjust its access rights in Odoo.",
}


def _rpc_error(error) -> OdooError:
    data = error.get("data") or {}
    name = data.get("name") or ""
    message = data.get("message") or error.get("message") or "unknown error"
    short = name.rsplit(".", 1)[-1]
    text = f"Odoo error [{short}]: {message}" if short else f"Odoo error: {message}"
    return OdooError(text + _HINTS.get(short, ""), name=name)


def legacy_order(order, aggregates):
    """read_group names aggregate columns by field ("amount_total"), not by spec ("amount_total:sum")."""
    if not order:
        return order
    by_spec = {spec: spec.split(":", 1)[0] for spec in aggregates}
    terms = []
    for term in order.split(","):
        words = term.split()
        if words and words[0] in by_spec:
            words[0] = by_spec[words[0]]
        terms.append(" ".join(words))
    return ", ".join(terms)


class JsonRpcBackend:
    protocol = "jsonrpc"

    def __init__(self, config, transport):
        self.config = config
        self.transport = transport
        self._uid = None
        self._ids = itertools.count(1)

    def _rpc(self, service, method, args):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": next(self._ids),
        }
        response = self.transport.request("POST", "/jsonrpc", payload)
        data = response.json_or_none()
        if isinstance(data, dict) and data.get("error"):
            raise _rpc_error(data["error"])
        if not isinstance(data, dict) or not 200 <= response.status < 300:
            raise self.transport.unexpected(response, "/jsonrpc")
        return data.get("result")

    def version(self) -> dict:
        info = self._rpc("common", "version", []) or {}
        return {"server_version": info.get("server_version"), "server_version_info": info.get("server_version_info")}

    def current_user_id(self) -> int:
        if self._uid is None:
            uid = self._rpc("common", "authenticate", [self.config.db, self.config.login, self.config.api_key, {}])
            if not uid:
                raise OdooError(
                    "Odoo rejected the login. Check ODOO_DB, ODOO_LOGIN (the login of the user who owns the key) "
                    "and ODOO_API_KEY on the Claude cloud environment. API keys expire: 90 days at most by default."
                )
            self._uid = uid
        return self._uid

    def call(self, model, method, args=(), kwargs=None, enforce_allowlist=True):
        check_call(model, method, self.config.allowed_models, enforce_allowlist)
        uid = self.current_user_id()
        return self._rpc(
            "object",
            "execute_kw",
            [self.config.db, uid, self.config.api_key, model, method, list(args), kwargs or {}],
        )

    def search_read(self, model, domain, fields, limit, offset, order, context, enforce_allowlist=True):
        kwargs = {"offset": offset, "context": context}
        if limit:
            kwargs["limit"] = limit
        if fields:
            kwargs["fields"] = fields
        if order:
            kwargs["order"] = order
        return self.call(model, "search_read", [domain], kwargs, enforce_allowlist)

    def search_count(self, model, domain, context):
        return self.call(model, "search_count", [domain], {"context": context})

    def read(self, model, ids, fields, context, enforce_allowlist=True):
        kwargs = {"context": context}
        if fields:
            kwargs["fields"] = fields
        return self.call(model, "read", [ids], kwargs, enforce_allowlist)

    def fields_get(self, model, attributes, context):
        return self.call(model, "fields_get", [], {"attributes": attributes, "context": context})

    def group(self, model, domain, groupby, aggregates, order, limit, context):
        kwargs = {"lazy": False, "context": context}
        if order:
            kwargs["orderby"] = legacy_order(order, aggregates)
        if limit:
            kwargs["limit"] = limit
        return "read_group", self.call(model, "read_group", [domain, list(aggregates), groupby], kwargs)
