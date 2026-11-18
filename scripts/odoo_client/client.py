"""Read-only operations shared by both protocols: company context, result
normalization, discovery and the connection check."""
from __future__ import annotations

import re

from .errors import OdooError
from .json2 import Json2Backend
from .jsonrpc import JsonRpcBackend
from .normalize import normalize_groups, normalize_records
from .safety import BLOCKED_MODELS, check_call
from .transport import Transport

PAGE_SIZE = 500
HARD_CAP = 20000
FIELD_ATTRIBUTES = ["string", "type", "relation", "required", "store", "selection"]
USER_FIELDS = ["name", "login", "company_id", "company_ids", "lang", "tz"]
_ODOO_AUTHOR = re.compile(r"odoo\s*s\.?\s*a\.?", re.IGNORECASE)


def major_version(version: dict):
    info = version.get("server_version_info")
    if isinstance(info, list) and info and isinstance(info[0], int) and not isinstance(info[0], bool):
        return info[0]
    match = re.search(r"(\d+)", str(version.get("server_version") or ""))
    return int(match.group(1)) if match else None


def _with_default_granularity(spec, field_types):
    if ":" not in spec and "." not in spec and field_types.get(spec) in ("date", "datetime"):
        return f"{spec}:month"
    return spec


class OdooClient:
    def __init__(self, config, backend):
        self.config = config
        self.backend = backend
        self._user = None
        self._context = None
        self._field_types = {}

    @classmethod
    def from_config(cls, config, opener=None, sleep=None):
        options = {"opener": opener}
        if sleep is not None:
            options["sleep"] = sleep
        transport = Transport(config.url, config.timeout, **options)
        backend_class = Json2Backend if config.protocol == "json2" else JsonRpcBackend
        return cls(config, backend_class(config, transport))

    def user(self) -> dict:
        if self._user is None:
            uid = self.backend.current_user_id()
            try:
                rows = self.backend.read("res.users", [uid], USER_FIELDS, {}, enforce_allowlist=False)
            except OdooError:
                rows = []
            self._user = rows[0] if rows else {"id": uid}
        return self._user

    def context(self) -> dict:
        """Every query sees all of the bot user's companies; without allowed_company_ids
        Odoo silently limits results to its default company."""
        if self._context is None:
            user = self.user()
            context = {"tz": self.config.tz}
            if user.get("lang"):
                context["lang"] = user["lang"]
            companies = []
            current = user.get("company_id")
            if isinstance(current, (list, tuple)) and current:
                companies.append(current[0])
            for company_id in user.get("company_ids") or []:
                if company_id not in companies:
                    companies.append(company_id)
            if companies:
                context["allowed_company_ids"] = companies
            self._context = context
        return self._context

    def _guard(self, model, method):
        # The company context costs network calls, so refuse a blocked call before fetching it.
        check_call(model, method, self.config.allowed_models)

    def _model_visible(self, model):
        allowed = self.config.allowed_models
        return model not in BLOCKED_MODELS and (not allowed or model in allowed)

    def field_types(self, model) -> dict:
        if model not in self._field_types:
            self._guard(model, "fields_get")
            fields = self.backend.fields_get(model, ["type"], self.context())
            self._field_types[model] = {name: meta.get("type") for name, meta in (fields or {}).items()}
        return self._field_types[model]

    def count(self, model, domain) -> int:
        self._guard(model, "search_count")
        return self.backend.search_count(model, domain, self.context())

    def search(self, model, domain, fields=None, limit=None, offset=0, order=None) -> list:
        self._guard(model, "search_read")
        records = self.backend.search_read(model, domain, fields, limit, offset, order, self.context())
        return normalize_records(records, self.field_types(model))

    def search_all(self, model, domain, fields=None, order=None):
        self._guard(model, "search_read")
        total = self.count(model, domain)
        wanted = min(total, HARD_CAP)
        records = []
        while len(records) < wanted:
            page = self.search(model, domain, fields, min(PAGE_SIZE, wanted - len(records)), len(records), order or "id")
            if not page:
                break
            records.extend(page)
        return records, total, total > HARD_CAP

    def read(self, model, ids, fields=None) -> list:
        self._guard(model, "read")
        records = self.backend.read(model, ids, fields, self.context())
        return normalize_records(records, self.field_types(model))

    def describe_fields(self, model, keyword=None) -> dict:
        self._guard(model, "fields_get")
        fields = self.backend.fields_get(model, FIELD_ATTRIBUTES, self.context()) or {}
        needle = (keyword or "").lower()
        rows = []
        for name in sorted(fields):
            meta = fields[name]
            label = meta.get("string") or ""
            if needle and needle not in name.lower() and needle not in label.lower():
                continue
            row = {"name": name, "label": label, "type": meta.get("type")}
            if meta.get("relation") and self._model_visible(meta["relation"]):
                row["relation"] = meta["relation"]
            if meta.get("required"):
                row["required"] = True
            if meta.get("store") is False:
                row["stored"] = False
            if isinstance(meta.get("selection"), list) and meta["selection"]:
                row["options"] = [list(option) for option in meta["selection"]]
            rows.append(row)
        return {"model": model, "field_count": len(rows), "fields": rows}

    def group(self, model, domain, groupby, aggregates, order=None, limit=None):
        self._guard(model, "read_group")
        field_types = self.field_types(model)
        specs = [_with_default_granularity(spec, field_types) for spec in groupby]
        style, rows = self.backend.group(model, domain, specs, aggregates, order, limit, self.context())
        return specs, normalize_groups(rows, specs, aggregates, style, field_types)

    def _model_metadata(self, registry, domain, fields, limit, order):
        # Only the discovery commands use this exception, with fixed registries and projections.
        allowed = self.config.allowed_models
        if allowed:
            scope = ["model", "in", [m for m in allowed if m not in BLOCKED_MODELS]]
        else:
            scope = ["model", "not in", sorted(BLOCKED_MODELS)]
        rows = self.backend.search_read(
            registry, [*domain, scope], fields, limit, 0, order, self.context(), enforce_allowlist=False)
        return [row for row in rows if self._model_visible(row["model"])]

    def models(self, keyword=None, limit=200) -> dict:
        domain = [["transient", "=", False]]
        if keyword:
            domain += ["|", ["model", "ilike", keyword], ["name", "ilike", keyword]]
        rows = self._model_metadata("ir.model", domain, ["model", "name"], limit, "model")
        models = [{"model": row["model"], "name": row.get("name")} for row in rows]
        return {"count": len(models), "models": models}

    def guide(self) -> dict:
        version = self.backend.version()
        context = self.context()
        allowed = self.config.allowed_models

        def attempt(fetch):
            try:
                return fetch()
            except OdooError as exc:
                return {"unavailable": str(exc)}

        if allowed and "ir.module.module" not in allowed:
            modules = {"unavailable": "The database-wide module list is outside ODOO_ALLOWED_MODELS."}
        else:
            modules = attempt(lambda: self.backend.search_read(
                "ir.module.module", [["state", "=", "installed"]], ["name", "shortdesc", "author"],
                2000, 0, "name", context))
        custom_fields = attempt(lambda: self._model_metadata(
            "ir.model.fields", [["state", "=", "manual"]], ["model", "name", "field_description", "ttype", "relation"],
            1500, "model, name"))
        custom_models = attempt(lambda: self._model_metadata(
            "ir.model", [["state", "=", "manual"]], ["model", "name"], 500, "model"))

        if isinstance(modules, list):
            modules = [
                {"module": m["name"], "name": m.get("shortdesc") or "", "author": m.get("author") or ""}
                for m in modules
                if not _ODOO_AUTHOR.search(m.get("author") or "")
            ]
        if isinstance(custom_fields, list):
            by_model = {}
            for f in custom_fields:
                model = f.get("model")
                row = {"field": f["name"], "label": f.get("field_description") or "", "type": f.get("ttype")}
                if f.get("relation") and self._model_visible(f["relation"]):
                    row["relation"] = f["relation"]
                by_model.setdefault(model, []).append(row)
            custom_fields = by_model
        if isinstance(custom_models, list):
            custom_models = [{"model": m["model"], "name": m.get("name")} for m in custom_models]

        return {
            "server_version": version.get("server_version"),
            "major_version": major_version(version),
            "non_standard_modules": modules,
            "custom_fields_by_model": custom_fields,
            "custom_models": custom_models,
            "hint": (
                "Fields added by custom Python modules (not Studio) are not listed in custom_fields_by_model: "
                "run `fields MODEL` on the models those modules extend. The company notes explain what custom fields mean."
            ),
        }

    def check(self) -> dict:
        version = self.backend.version()
        user = self.user()
        context = self.context()
        allowed = self.config.allowed_models
        test_model = "res.partner" if not allowed or "res.partner" in allowed else allowed[0]
        count = self.count(test_model, [])

        result = {
            "ok": True,
            "protocol": self.config.protocol,
            "auth_mode": self.config.auth_mode,
            "url": self.config.url,
            "database": self.config.db or "(chosen by Odoo from the host name)",
            "server_version": version.get("server_version"),
            "user": {"id": user.get("id"), "name": user.get("name"), "login": user.get("login")},
            "companies": self._companies(context.get("allowed_company_ids") or []),
            "default_context": context,
            "report_timezone": self.config.tz,
            "test": {"model": test_model, "search_count": count},
        }
        if allowed:
            result["model_restriction"] = list(allowed)

        warnings = []
        major = major_version(version)
        if self.config.protocol == "jsonrpc" and major and major >= 19:
            warnings.append(
                "This server is Odoo 19 or later: switch to ODOO_PROTOCOL=json2 with the key stored as a "
                "network secret, so the key never enters the VM."
            )
        if major and major < 18:
            warnings.append(
                f"This toolkit targets Odoo 18 and 19; this server runs {version.get('server_version')}, "
                "so some field names may differ."
            )
        if warnings:
            result["warnings"] = warnings
        return result

    def _companies(self, ids) -> list:
        if not ids:
            return []
        try:
            rows = self.backend.search_read(
                "res.company", [["id", "in", ids]], ["name"], len(ids), 0, "id", self.context(), enforce_allowlist=False)
        except OdooError:
            return [{"id": company_id} for company_id in ids]
        return [{"id": row["id"], "name": row.get("name")} for row in rows]
