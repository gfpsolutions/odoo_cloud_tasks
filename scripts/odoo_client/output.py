"""JSON on stdout, and report files under out/."""
from __future__ import annotations

import csv
import json
import os
import sys

# Spreadsheet apps run a cell that starts with one of these as a formula.
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def dumps(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


def redact(value, secrets):
    """Mask configured secrets before JSON or CSV can escape the original text."""
    if not secrets:
        return value
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
    elif isinstance(value, dict):
        return {redact(key, secrets): redact(item, secrets) for key, item in value.items()}
    elif isinstance(value, (list, tuple)):
        return [redact(item, secrets) for item in value]
    return value


def emit(data, secrets=()) -> None:
    sys.stdout.write(dumps(redact(data, secrets)) + "\n")


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        value = ";".join(str(item) for item in value)
    elif isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and (
        value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(_FORMULA_PREFIXES)
    ):
        return "'" + value
    return value


def flatten(row: dict) -> dict:
    flat = {}
    for key, value in row.items():
        if isinstance(value, dict) and set(value) == {"id", "name"}:
            flat[key] = value["name"]
            flat[f"{key}.id"] = value["id"]
        elif isinstance(value, dict) and set(value) == {"start", "label"}:
            flat[key] = value["label"]
            flat[f"{key}.start"] = value["start"]
        else:
            flat[key] = value
    return flat


def columns_of(rows) -> list:
    columns = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns


def write_csv(path, rows) -> list:
    flat_rows = [flatten(row) for row in rows]
    columns = columns_of(flat_rows)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow([_cell(column) for column in columns])
        for row in flat_rows:
            writer.writerow([_cell(row.get(column)) for column in columns])
    return columns


def write_json(path, rows) -> list:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(dumps(rows) + "\n")
    return columns_of(rows)


def display_path(path) -> str:
    try:
        return os.path.relpath(path)
    except ValueError:
        return str(path)
