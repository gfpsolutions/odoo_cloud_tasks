"""Command line: JSON on stdout, errors on stderr, non-zero exit on failure."""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .client import HARD_CAP, PAGE_SIZE, OdooClient
from .config import load_config, report_timezone
from .errors import SafetyError, ToolkitError
from .output import display_path, emit, redact, write_csv, write_json
from .periods import PRESETS, parse_day, window
from .safety import (
    check_order,
    output_path,
    parse_aggregates,
    parse_domain,
    parse_fields,
    parse_groupby,
    parse_ids,
    scrub,
)

MAX_LIMIT = 2000
SAMPLE_ROWS = 5

DESCRIPTION = """\
Read-only Odoo queries for Claude scheduled tasks (Odoo 18 and 19).

Configuration comes only from environment variables on the Claude cloud
environment: ODOO_URL, ODOO_PROTOCOL (jsonrpc for Odoo 18, json2 for Odoo 19
or later), ODOO_DB, and for jsonrpc also ODOO_LOGIN and ODOO_API_KEY.
Optional: ODOO_TIMEOUT (seconds, default 60), ODOO_TZ (default Europe/Paris),
ODOO_ALLOWED_MODELS. Results are JSON on stdout; errors go to stderr with a
non-zero exit code. Only read methods can ever be called.
"""

EPILOG = """\
examples:
  odoo.py check
  odoo.py fields account.move --filter amount
  odoo.py period last-month --field invoice_date
  odoo.py count account.move --domain '[["move_type", "=", "out_invoice"], ["state", "=", "posted"]]'
  odoo.py group account.move --domain '[["state", "=", "posted"]]' \\
      --groupby invoice_date:month --aggregates amount_untaxed_signed:sum
  odoo.py search res.partner --fields name,email --limit 20
  odoo.py search sale.order --fields name,partner_id,amount_total --all --csv out/orders.csv

Run "odoo.py COMMAND --help" for the options of one command.
"""

DOMAIN_HELP = (
    'Odoo domain as JSON, e.g. \'[["state", "=", "posted"], ["invoice_date", ">=", "2026-10-01"]]\'. '
    'Prefix conditions with "|", "&" or "!" for OR, AND, NOT. Default: [] (all records).'
)


def _add_domain(parser):
    parser.add_argument("--domain", default="[]", help=DOMAIN_HELP)


def _add_output(parser):
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--csv", metavar="PATH",
        help="Also write the rows to a CSV file under out/ (UTF-8, opens in Excel). stdout then shows a summary.")
    group.add_argument(
        "--json", metavar="PATH", dest="json_path",
        help="Also write the rows to a JSON file under out/. stdout then shows a summary.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odoo.py", description=DESCRIPTION, epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"odoo_cloud_tasks {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    sub.add_parser(
        "check", help="Test the connection. Run this first in every task.",
        description="Test the connection and show the protocol, the auth mode (never the key), the Odoo "
                    "version, the database, the Odoo user and its companies, and a test count of res.partner.")

    sub.add_parser(
        "guide", help="List custom modules, custom fields and custom models.",
        description="List what is customized in this database: installed modules not made by Odoo S.A., custom "
                    "(Studio / x_) fields per model, and custom models. Sections the Odoo user can't read are "
                    "marked unavailable.")

    p = sub.add_parser(
        "models", help="Find models by keyword.",
        description="Find models by keyword, e.g. invoice -> account.move, quant -> stock.quant.")
    p.add_argument("--filter", metavar="TEXT", help="Word to look for in the technical or display name.")
    p.add_argument("--limit", type=int, default=200, help="Max models to list (default 200).")

    p = sub.add_parser(
        "fields", help="Describe a model's fields.",
        description="List a model's fields with label, type, related model, and the options of selection "
                    "fields. Run it before querying a model, so you use real field names and values.")
    p.add_argument("model", help="Technical model name, e.g. account.move.")
    p.add_argument("--filter", metavar="TEXT", help="Only fields whose name or label contains TEXT.")

    p = sub.add_parser(
        "search", help="List records.",
        description="List matching records with the fields you choose. Many2one values come back as "
                    '{"id", "name"}. Output includes the total number of matches.')
    p.add_argument("model", help="Technical model name, e.g. sale.order.")
    _add_domain(p)
    p.add_argument("--fields", metavar="a,b,c", help="Fields to return. Always pass it to keep the output small.")
    p.add_argument("--limit", type=int, default=200, help=f"Max records, 1 to {MAX_LIMIT} (default 200). Ignored with --all.")
    p.add_argument("--offset", type=int, default=0, help="Skip this many records, for paging (default 0).")
    p.add_argument("--order", help='Sort, e.g. "invoice_date desc, name".')
    p.add_argument(
        "--all", action="store_true",
        help=f"Fetch every match in pages of {PAGE_SIZE}, up to {HARD_CAP} records. Requires --csv or --json.")
    _add_output(p)

    p = sub.add_parser("count", help="Count matching records.", description="Count the records matching a domain.")
    p.add_argument("model", help="Technical model name.")
    _add_domain(p)

    p = sub.add_parser(
        "group", help="Totals and breakdowns, computed by Odoo.",
        description="Group and total records on the server, like a pivot table. Many2one groups come back as "
                    '{"id", "name"}, date groups as {"start", "label"}. Every group includes __count.')
    p.add_argument("model", help="Technical model name.")
    _add_domain(p)
    p.add_argument(
        "--groupby", required=True, metavar="FIELD[:GRANULARITY],...",
        help="Group-by fields, e.g. partner_id or invoice_date:month (day, week, month, quarter, year).")
    p.add_argument(
        "--aggregates", default="", metavar="FIELD:FUNCTION,...",
        help="Measures, e.g. amount_untaxed_signed:sum,amount_residual_signed:sum "
             "(sum, avg, min, max, count, count_distinct).")
    p.add_argument("--order", help='Sort groups by a group-by, an aggregate or __count, e.g. "amount_total:sum desc".')
    p.add_argument("--limit", type=int, help="Max number of groups.")
    _add_output(p)

    p = sub.add_parser("read", help="Read records by id.", description="Read specific records by id.")
    p.add_argument("model", help="Technical model name.")
    p.add_argument("--ids", required=True, metavar="1,2,3", help="Record ids separated by commas.")
    p.add_argument("--fields", metavar="a,b,c", help="Fields to return.")
    _add_output(p)

    p = sub.add_parser(
        "period", help="Compute a date window and the matching domains.",
        description="Compute a report window in ODOO_TZ (default Europe/Paris) and print ready-made domains: "
                    "date_domain for date fields, datetime_domain (UTC bounds) for datetime fields. "
                    "Needs no Odoo connection.")
    p.add_argument("preset", nargs="?", choices=PRESETS, metavar="PERIOD", help=f"One of: {', '.join(PRESETS)}.")
    p.add_argument("--from", dest="first", metavar="YYYY-MM-DD", help="Start of a custom window (inclusive), with --to.")
    p.add_argument("--to", dest="last", metavar="YYYY-MM-DD", help="End of a custom window (inclusive), with --from.")
    p.add_argument("--field", help="Field name to put in the ready-made domains, e.g. invoice_date.")
    p.add_argument("--today", metavar="YYYY-MM-DD", help="Compute as if today were this date, to re-run a past report.")
    return parser


def _between(value, option, maximum=None):
    if value is None or value < 1 or (maximum is not None and value > maximum):
        raise SafetyError(f"{option} must be between 1 and {maximum}." if maximum else f"{option} must be at least 1.")
    return value


def _output_target(args):
    if getattr(args, "csv", None):
        return output_path(args.csv), "csv"
    if getattr(args, "json_path", None):
        return output_path(args.json_path), "json"
    return None, None


def _write_file(result, path, kind, rows, secrets):
    rows = redact(rows, secrets)
    columns = write_csv(path, rows) if kind == "csv" else write_json(path, rows)
    result.update(file=display_path(path), columns=columns, sample=rows[:SAMPLE_ROWS])


def _warn(message):
    sys.stderr.write(f"warning: {message}\n")


def cmd_check(args, client):
    return client.check()


def cmd_guide(args, client):
    return client.guide()


def cmd_models(args, client):
    return client.models(args.filter, _between(args.limit, "--limit", MAX_LIMIT))


def cmd_fields(args, client):
    return client.describe_fields(args.model, args.filter)


def cmd_search(args, client):
    domain = parse_domain(args.domain)
    fields = parse_fields(args.fields) if args.fields else None
    order = check_order(args.order) if args.order else None
    path, kind = _output_target(args)
    result = {"model": args.model, "domain": domain}

    if args.all:
        if not path:
            raise SafetyError(
                "--all needs --csv out/NAME.csv or --json out/NAME.json: the records go to the file and "
                "stdout shows a summary.")
        records, total, capped = client.search_all(args.model, domain, fields, order)
        result.update(total_matching=total, returned=len(records))
        if capped:
            warning = (f"Only the first {len(records)} of {total} records were fetched (hard cap). "
                       "Narrow the domain, or use group for totals.")
            result.update(capped=True, warnings=[warning])
            _warn(warning)
    else:
        if args.offset < 0:
            raise SafetyError("--offset can't be negative.")
        limit = _between(args.limit, "--limit", MAX_LIMIT)
        total = client.count(args.model, domain)
        records = client.search(args.model, domain, fields, limit, args.offset, order)
        result.update(
            total_matching=total, returned=len(records), offset=args.offset,
            more_available=args.offset + len(records) < total)

    if path:
        _write_file(result, path, kind, records, client.config.secrets)
    else:
        result["records"] = records
    return result


def cmd_count(args, client):
    domain = parse_domain(args.domain)
    return {"model": args.model, "domain": domain, "count": client.count(args.model, domain)}


def cmd_group(args, client):
    domain = parse_domain(args.domain)
    groupby = parse_groupby(args.groupby)
    aggregates = parse_aggregates(args.aggregates) if args.aggregates else []
    order = check_order(args.order) if args.order else None
    limit = _between(args.limit, "--limit") if args.limit is not None else None
    path, kind = _output_target(args)
    specs, groups = client.group(args.model, domain, groupby, aggregates, order, limit)
    result = {"model": args.model, "domain": domain, "groupby": specs, "aggregates": aggregates,
              "group_count": len(groups)}
    if path:
        _write_file(result, path, kind, groups, client.config.secrets)
    else:
        result["groups"] = groups
    return result


def cmd_read(args, client):
    ids = parse_ids(args.ids)
    fields = parse_fields(args.fields) if args.fields else None
    path, kind = _output_target(args)
    records = client.read(args.model, ids, fields)
    result = {"model": args.model, "returned": len(records)}
    if path:
        _write_file(result, path, kind, records, client.config.secrets)
    else:
        result["records"] = records
    return result


def cmd_period(args):
    if args.field:
        parse_fields(args.field)
    return window(
        preset=args.preset,
        tz_name=report_timezone(),
        today=parse_day(args.today, "--today") if args.today else None,
        first=parse_day(args.first, "--from") if args.first else None,
        last=parse_day(args.last, "--to") if args.last else None,
        field=args.field,
    )


HANDLERS = {
    "check": cmd_check,
    "guide": cmd_guide,
    "models": cmd_models,
    "fields": cmd_fields,
    "search": cmd_search,
    "count": cmd_count,
    "group": cmd_group,
    "read": cmd_read,
}


def main(argv=None, opener=None, sleep=None) -> int:
    args = build_parser().parse_args(argv)
    key = (os.environ.get("ODOO_API_KEY") or "").strip()
    secrets = (key,) if key else ()
    try:
        if args.command == "period":
            result = cmd_period(args)
        else:
            client = OdooClient.from_config(load_config(), opener=opener, sleep=sleep)
            result = HANDLERS[args.command](args, client)
        emit(result, secrets)
        return 0
    except ToolkitError as exc:
        message = str(exc)
    except KeyboardInterrupt:
        sys.stderr.write("error: interrupted\n")
        return 130
    except Exception as exc:
        # No traceback: it could echo request data.
        message = f"Unexpected error ({type(exc).__name__}): {exc}"
    sys.stderr.write(f"error: {scrub(message, secrets)}\n")
    return 1
