"""Give results from both protocols the same shape."""
from __future__ import annotations

TIME_GRANULARITIES = frozenset({"hour", "day", "week", "month", "quarter", "year"})


def is_pair(value) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and isinstance(value[0], int)
        and not isinstance(value[0], bool)
        and isinstance(value[1], str)
    )


def normalize_value(value, field_type=None):
    """Many2one [id, name] becomes {"id", "name"}; Odoo's False for an empty non-boolean value becomes None."""
    if field_type in (None, "many2one", "many2many") and is_pair(value):
        return {"id": value[0], "name": value[1]}
    if value is False and field_type not in (None, "boolean"):
        return None
    return value


def normalize_records(records, field_types) -> list:
    return [
        {name: normalize_value(value, field_types.get(name)) for name, value in record.items()}
        for record in records or []
    ]


def normalize_groups(rows, groupby, aggregates, style, field_types=None) -> list:
    """style is "formatted" (Odoo 19 formatted_read_group) or "read_group" (Odoo 18 and the 19 fallback)."""
    field_types = field_types or {}
    groups = []
    for row in rows or []:
        group = {spec: _group_value(row, spec, style, field_types) for spec in groupby}
        for spec in aggregates:
            key = spec if style == "formatted" else spec.split(":", 1)[0]
            group[spec] = row.get(key)
        group["__count"] = row.get("__count")
        groups.append(group)
    return groups


def _group_value(row, spec, style, field_types):
    value = row.get(spec)
    path, _, granularity = spec.partition(":")
    if granularity in TIME_GRANULARITIES:
        if value in (False, None):
            return None
        if style == "formatted" and isinstance(value, (list, tuple)) and len(value) == 2:
            return {"start": value[0], "label": value[1]}
        bounds = (row.get("__range") or {}).get(spec)
        return {"start": bounds.get("from") if isinstance(bounds, dict) else None, "label": value}
    field_type = None if "." in path else field_types.get(path)
    return normalize_value(value, field_type)
