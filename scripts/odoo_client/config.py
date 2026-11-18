"""Configuration, read only from process environment variables.

Per-client values and secrets live on the Claude cloud environment, never in
the repository, so nothing here reads a file.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .errors import ConfigError

WHERE = (
    "Set it on the Claude cloud environment (claude.ai/code → environment settings → "
    "Environment variables / Network secrets)."
)
JSON2_KEY_REFUSAL = (
    "ODOO_API_KEY must not be set for json2 — store the key as a network secret "
    "on the Claude cloud environment instead."
)

PROTOCOLS = ("jsonrpc", "json2")
DEFAULT_TIMEOUT = 60.0
DEFAULT_TZ = "Europe/Paris"

AUTH_PROXY = "network secret, injected by proxy"
AUTH_ENV = "environment variable"
AUTH_LOCAL = "ODOO_API_KEY sent as bearer token (local development only)"


@dataclass(frozen=True)
class Config:
    url: str
    protocol: str
    db: str
    login: str
    api_key: str = field(repr=False)
    timeout: float
    tz: str
    allowed_models: tuple
    remote: bool

    @property
    def auth_mode(self) -> str:
        if self.protocol == "jsonrpc":
            return AUTH_ENV
        return AUTH_LOCAL if self.api_key else AUTH_PROXY

    @property
    def secrets(self) -> tuple:
        return (self.api_key,) if self.api_key else ()


def _get(env, name: str) -> str:
    return (env.get(name) or "").strip()


def _missing(name: str, extra: str = "") -> str:
    return f"{name} is not set.{extra} {WHERE} For local runs, export it in your shell."


def report_timezone(environ=None) -> str:
    env = os.environ if environ is None else environ
    tz = _get(env, "ODOO_TZ") or DEFAULT_TZ
    try:
        ZoneInfo(tz)
    except Exception:
        raise ConfigError(f"ODOO_TZ must be a time zone name such as Europe/Paris, not {tz!r}.") from None
    return tz


def load_config(environ=None) -> Config:
    env = os.environ if environ is None else environ
    remote = _get(env, "CLAUDE_CODE_REMOTE") == "true"

    url = _get(env, "ODOO_URL")
    if not url:
        raise ConfigError(_missing("ODOO_URL"))
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ConfigError(
            "ODOO_URL must be the address you open Odoo with, starting with https:// "
            f"(for example https://mycompany.example.com). {WHERE}"
        )
    if parts.username or parts.password:
        raise ConfigError("ODOO_URL must not contain a login or password.")

    protocol = _get(env, "ODOO_PROTOCOL").lower()
    if not protocol:
        raise ConfigError(_missing("ODOO_PROTOCOL", " Use jsonrpc for Odoo 18, json2 for Odoo 19 or later."))
    if protocol == "xmlrpc":
        raise ConfigError(
            "ODOO_PROTOCOL=xmlrpc isn't supported: use jsonrpc, which covers the same Odoo "
            "versions and works through the Claude cloud proxy."
        )
    if protocol not in PROTOCOLS:
        raise ConfigError(f"ODOO_PROTOCOL must be jsonrpc (Odoo 18) or json2 (Odoo 19 or later), not {protocol!r}.")

    db = _get(env, "ODOO_DB")
    login = _get(env, "ODOO_LOGIN")
    api_key = _get(env, "ODOO_API_KEY")

    if protocol == "jsonrpc":
        for name, value in (("ODOO_DB", db), ("ODOO_LOGIN", login), ("ODOO_API_KEY", api_key)):
            if not value:
                raise ConfigError(_missing(name))
    elif api_key and remote:
        raise ConfigError(JSON2_KEY_REFUSAL)

    timeout = DEFAULT_TIMEOUT
    raw_timeout = _get(env, "ODOO_TIMEOUT")
    if raw_timeout:
        try:
            timeout = float(raw_timeout)
        except ValueError:
            timeout = 0.0
        if not 1 <= timeout <= 600:
            raise ConfigError("ODOO_TIMEOUT must be a number of seconds between 1 and 600.")

    allowed = tuple(m for m in re.split(r"[,\s]+", _get(env, "ODOO_ALLOWED_MODELS")) if m)

    return Config(
        url=url.rstrip("/"),
        protocol=protocol,
        db=db,
        login=login,
        api_key=api_key,
        timeout=timeout,
        tz=report_timezone(env),
        allowed_models=allowed,
        remote=remote,
    )
