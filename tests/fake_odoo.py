"""Stands in for urllib's opener and answers like Odoo 18 (/jsonrpc) or Odoo 19 (/json/2)."""
from __future__ import annotations

import copy
import io
import json
import urllib.error
from email.message import Message
from urllib.parse import urlsplit

KEY = "fake-api-key-for-tests"
UID = 7
USER = {
    "id": UID,
    "name": "Claude Reports",
    "login": "bot@example.com",
    "company_id": [1, "Example Co"],
    "company_ids": [1, 2],
    "lang": "fr_FR",
    "tz": "Europe/Paris",
}
COMPANIES = [{"id": 1, "name": "Example Co"}, {"id": 2, "name": "Example Spain"}]
FIELDS = {
    "account.move": {
        "name": {"string": "Number", "type": "char"},
        "partner_id": {"string": "Customer", "type": "many2one", "relation": "res.partner"},
        "invoice_date": {"string": "Invoice Date", "type": "date"},
        "state": {
            "string": "Status",
            "type": "selection",
            "required": True,
            "selection": [["draft", "Draft"], ["posted", "Posted"], ["cancel", "Cancelled"]],
        },
        "amount_total_signed": {"string": "Total Signed", "type": "monetary"},
        "amount_residual_signed": {"string": "Amount Due Signed", "type": "monetary"},
        "invoice_origin": {"string": "Origin", "type": "char"},
        "is_move_sent": {"string": "Is Move Sent", "type": "boolean"},
        "payment_reference": {"string": "Payment Reference", "type": "char", "store": False},
        "narration": {"string": "Terms and Conditions", "type": "html"},
    },
    "res.partner": {
        "name": {"string": "Name", "type": "char"},
        "email": {"string": "Email", "type": "char"},
    },
}


class OdooFault(Exception):
    """An exception raised inside the fake Odoo, reported the way each protocol reports errors."""

    def __init__(self, name, message, debug="", status=422):
        super().__init__(message)
        self.name = name
        self.message = message
        self.debug = debug
        self.status = status


class FakeResponse:
    def __init__(self, status, body, headers):
        self.status = status
        self.headers = headers
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _params(method, args, kwargs):
    params = dict(kwargs)
    if method in ("search_read", "search_count", "search") and args:
        params["domain"] = args[0]
    elif method == "read" and args:
        params["ids"] = args[0]
    elif method == "read_group":
        params.update(domain=args[0], fields=args[1], groupby=args[2])
    return params


class FakeOdoo:
    def __init__(self, server="jsonrpc", version="18.0+e", key=KEY):
        self.server = server  # "jsonrpc" behaves like Odoo 18, "json2" like Odoo 19
        self.version = version
        self.key = key
        self.proxy_injects = True  # json2: Anthropic's proxy adds the key when the client sends none
        self.requests = []  # every HTTP request: method, path, headers (lowercase), body
        self.calls = []  # every model method that ran: (model, method, params)
        self.plan = []  # outcomes served before normal handling: an exception, or (status, payload, headers)
        self.records = {}
        self.counts = {"res.partner": 42}
        self.groups = {}
        self.faults = {}
        self.missing = set()

    @property
    def major(self):
        return int(self.version.replace("saas~", "").split(".")[0])

    def calls_to(self, method):
        return [params for _model, name, params in self.calls if name == method]

    def open(self, request, timeout=None):
        url = request.full_url
        path = urlsplit(url).path
        headers = {k.lower(): v for k, v in request.header_items()}
        body = json.loads(request.data.decode("utf-8")) if request.data else None
        self.requests.append({"method": request.get_method(), "path": path, "headers": headers, "body": body})
        if self.plan:
            outcome = self.plan.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return self._reply(url, *outcome)
        if path == "/jsonrpc":
            return self._jsonrpc(url, body)
        if path == "/web/version" and self.server == "json2":
            return self._reply(url, 200, {"version": self.version, "version_info": [self.major, 0, 0, "final", 0, ""]})
        if path.startswith("/json/2/") and self.server == "json2":
            return self._json2(url, path, headers, body or {})
        return self._reply(url, 404, "<html><body>Not Found</body></html>")

    def _reply(self, url, status, payload, headers=None):
        raw = payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode("utf-8")
        if 200 <= status < 300:
            return FakeResponse(status, raw, headers or {})
        message = Message()
        for name, value in (headers or {}).items():
            message[name] = value
        raise urllib.error.HTTPError(url, status, "error", message, io.BytesIO(raw))

    def _jsonrpc(self, url, body):
        service = body["params"]["service"]
        method = body["params"]["method"]
        args = body["params"]["args"]

        def ok(result):
            return self._reply(url, 200, {"jsonrpc": "2.0", "id": body["id"], "result": result})

        def error(name, message, debug=""):
            data = {"name": name, "message": message, "arguments": [message], "debug": debug}
            return self._reply(url, 200, {"jsonrpc": "2.0", "id": body["id"],
                                          "error": {"code": 200, "message": "Odoo Server Error", "data": data}})

        if service == "common" and method == "version":
            return ok({"server_version": self.version, "server_version_info": [self.major, 0, 0, "final", 0, "e"]})
        if service == "common" and method == "authenticate":
            _db, login, key, _env = args
            return ok(UID if login == USER["login"] and key == self.key else False)
        if service == "object" and method == "execute_kw":
            _db, uid, key, model, name, margs, kwargs = args
            if key != self.key or uid != UID:
                return error("odoo.exceptions.AccessDenied", "Access Denied")
            try:
                return ok(self.dispatch(model, name, _params(name, margs, kwargs)))
            except OdooFault as fault:
                return error(fault.name, fault.message, fault.debug)
        return error("builtins.KeyError", f"unknown service {service}")

    def _json2(self, url, path, headers, body):
        model, method = path.split("/")[3:5]
        auth = headers.get("authorization")
        if (auth is None and not self.proxy_injects) or auth not in (None, f"bearer {self.key}"):
            return self._reply(url, 401, {
                "name": "werkzeug.exceptions.Unauthorized", "message": "Invalid apikey",
                "arguments": ["Invalid apikey", 401], "context": {}, "debug": "Traceback (most recent call last): ..."})
        if (model, method) in self.missing:
            return self._reply(url, 404, {
                "name": "werkzeug.exceptions.NotFound",
                "message": f"The method {method!r} does not exist on the model {model!r}"})
        try:
            return self._reply(url, 200, self.dispatch(model, method, body))
        except OdooFault as fault:
            return self._reply(url, fault.status, {
                "name": fault.name, "message": fault.message, "arguments": [fault.message],
                "context": {}, "debug": fault.debug})

    def dispatch(self, model, method, params):
        self.calls.append((model, method, params))
        if (model, method) in self.faults:
            raise self.faults[(model, method)]
        if model == "res.users" and method == "read":
            return [copy.deepcopy(USER)]
        if model == "res.users" and method == "context_get":
            return {"lang": "fr_FR", "tz": "Europe/Paris", "uid": UID}
        if model == "res.company" and method == "search_read":
            return copy.deepcopy(COMPANIES)
        if method == "fields_get":
            wanted = params.get("attributes") or []
            return {
                name: {k: v for k, v in meta.items() if not wanted or k in wanted}
                for name, meta in FIELDS.get(model, {}).items()
            }
        if method == "search_count":
            return self.counts.get(model, len(self.records.get(model, [])))
        if method == "search_read":
            rows = self.records.get(model, [])
            offset = params.get("offset") or 0
            limit = params.get("limit")
            rows = rows[offset:offset + limit] if limit else rows[offset:]
            fields = params.get("fields")
            return [
                {k: v for k, v in row.items() if not fields or k == "id" or k in fields}
                for row in copy.deepcopy(rows)
            ]
        if method == "read":
            return [copy.deepcopy(row) for row in self.records.get(model, []) if row["id"] in params["ids"]]
        if method in ("read_group", "formatted_read_group"):
            return copy.deepcopy(self.groups.get((model, method), []))
        raise OdooFault("builtins.AttributeError", f"The method {method!r} does not exist on the model {model!r}", status=404)
