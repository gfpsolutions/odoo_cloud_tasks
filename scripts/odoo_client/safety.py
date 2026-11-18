"""Read-only guardrails. Every check runs before any network call, and no flag
or environment variable can turn them off."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .errors import SafetyError

ALLOWED_METHODS = frozenset({
    "search_read",
    "search_count",
    "search",
    "read",
    "read_group",
    "formatted_read_group",
    "fields_get",
    "name_search",
    # res.users.context_get is how JSON-2 identifies the user behind the API key.
    "context_get",
})

# Technical or security settings, never exposed even if the Odoo user could read them.
BLOCKED_MODELS = frozenset({
    "ir.config_parameter",
    "res.users.apikeys",
    "res.users.apikeys.description",
    "auth_totp.device",
    "ir.mail_server",
    "fetchmail.server",
    "payment.provider",
})

DOMAIN_OPERATORS = frozenset({
    "=", "!=", "<>", ">", ">=", "<", "<=", "=?",
    "=like", "like", "not like", "=ilike", "ilike", "not ilike",
    "in", "not in", "child_of", "parent_of", "any", "not any",
})

OUT_DIR = "out"
MAX_IDS = 2000

_MODEL_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")
_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GROUPBY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*(:[a-z_]+)?$")
_AGGREGATE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:[a-z_]+$")
_ORDER_TERM = r"[\w.:]+(\s+(asc|desc))?(\s+nulls\s+(first|last))?"
_ORDER_RE = re.compile(rf"^\s*{_ORDER_TERM}(\s*,\s*{_ORDER_TERM})*\s*$", re.IGNORECASE)
_HEX_KEY_RE = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{40}(?![0-9A-Fa-f])")


def check_method(method: str) -> None:
    if method not in ALLOWED_METHODS:
        raise SafetyError(
            f'Method "{method}" is not allowed: this toolkit is read-only '
            f'(allowed: {", ".join(sorted(ALLOWED_METHODS))}).'
        )


def check_model(model: str, allowed_models=(), enforce_allowlist: bool = True) -> None:
    if not isinstance(model, str) or not _MODEL_RE.match(model):
        raise SafetyError(f"{model!r} is not a valid Odoo model name (expected something like sale.order).")
    if model in BLOCKED_MODELS:
        raise SafetyError(f'The model "{model}" holds technical or security settings and is always blocked.')
    if enforce_allowlist and allowed_models and model not in allowed_models:
        raise SafetyError(
            f'The model "{model}" is not in ODOO_ALLOWED_MODELS ({", ".join(allowed_models)}).'
        )


def check_call(model: str, method: str, allowed_models=(), enforce_allowlist: bool = True) -> None:
    check_method(method)
    check_model(model, allowed_models, enforce_allowlist)


def parse_domain(text: str) -> list:
    try:
        domain = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SafetyError(
            f"--domain is not valid JSON ({exc.msg} at position {exc.pos}). "
            """Example: --domain '[["state", "=", "posted"]]'"""
        ) from None
    validate_domain(domain)
    return domain


def validate_domain(domain, where: str = "--domain") -> None:
    if not isinstance(domain, list):
        raise SafetyError(f'{where} must be a JSON list of conditions, for example [["state", "=", "posted"]].')
    operands = 0
    for item in reversed(domain):
        if isinstance(item, str):
            if item == "!":
                if operands < 1:
                    raise SafetyError(f'{where}: "!" must be followed by a condition.')
            elif item in ("&", "|"):
                if operands < 2:
                    raise SafetyError(f'{where}: "{item}" must be followed by two conditions.')
                operands -= 1
            else:
                raise SafetyError(f'{where}: unknown logical operator {item!r} (use "&", "|" or "!").')
        elif isinstance(item, list) and len(item) == 3:
            field_path, operator, value = item
            if not isinstance(field_path, str) or not field_path:
                raise SafetyError(f"{where}: the field in {json.dumps(item)[:80]} must be a field name.")
            if not isinstance(operator, str) or operator.lower() not in DOMAIN_OPERATORS:
                raise SafetyError(
                    f"{where}: unsupported operator {operator!r} "
                    f"(use one of: {', '.join(sorted(DOMAIN_OPERATORS))})."
                )
            if operator.lower() in ("any", "not any") and isinstance(value, list):
                validate_domain(value, where)
            operands += 1
        else:
            raise SafetyError(f"{where}: each condition must be [field, operator, value], not {json.dumps(item)[:80]}.")
    if domain and operands < 1:
        raise SafetyError(f"{where}: no condition found.")


def _split(text: str) -> list:
    return [part.strip() for part in text.split(",") if part.strip()]


def parse_fields(text: str) -> list:
    fields = _split(text)
    for name in fields:
        if not _FIELD_RE.match(name):
            raise SafetyError(f"{name!r} is not a valid field name.")
    return fields


def parse_ids(text: str) -> list:
    try:
        ids = [int(part) for part in _split(text)]
    except ValueError:
        raise SafetyError("--ids must be record ids separated by commas, for example 12,15,40.") from None
    if not ids or any(i <= 0 for i in ids):
        raise SafetyError("--ids must be positive record ids separated by commas.")
    if len(ids) > MAX_IDS:
        raise SafetyError(f"--ids accepts at most {MAX_IDS} ids per call.")
    return ids


def parse_groupby(text: str) -> list:
    specs = _split(text)
    if not specs:
        raise SafetyError("--groupby needs at least one field, for example partner_id or invoice_date:month.")
    for spec in specs:
        if not _GROUPBY_RE.match(spec):
            raise SafetyError(f"{spec!r} is not a valid group-by (use field or field:granularity, e.g. invoice_date:month).")
    return specs


def parse_aggregates(text: str) -> list:
    specs = _split(text)
    for spec in specs:
        if not _AGGREGATE_RE.match(spec):
            raise SafetyError(f"{spec!r} is not a valid aggregate (use field:function, e.g. amount_total:sum).")
    return specs


def check_order(text: str) -> str:
    if not _ORDER_RE.match(text):
        raise SafetyError(f"{text!r} is not a valid --order (example: \"invoice_date desc, name\").")
    return text.strip()


def output_path(path: str) -> Path:
    base = (Path.cwd() / OUT_DIR).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    resolved = candidate.resolve()
    if resolved == base or base not in resolved.parents:
        raise SafetyError(f"Output files must be inside out/ (got {path!r}). Example: --csv out/report.csv")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def scrub(text, secrets=()) -> str:
    text = str(text)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return _HEX_KEY_RE.sub("[REDACTED]", text)
