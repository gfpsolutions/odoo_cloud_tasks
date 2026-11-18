#!/usr/bin/env python3
"""Read-only Odoo queries for Claude scheduled tasks. Run with --help."""
import sys

if sys.version_info < (3, 9):
    sys.exit("odoo.py needs Python 3.9 or later.")

from odoo_client.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
