# odoo_cloud_tasks

Generic, read-only Odoo toolkit (Odoo 18 and 19) for unattended Claude cloud runs (scheduled tasks).

- All configuration and secrets come from the Claude cloud environment (environment variables, network secrets, setup script), never from this repository. Never add an Odoo address, database name, login or key to any file.
- Never print environment variables or credentials.
- Scheduled runs never commit, push or open pull requests.
- For Odoo data, use the `odoo` skill (`.claude/skills/odoo/SKILL.md`) and `python3 scripts/odoo.py`.

## Developing
- Standard library only at runtime (Python 3.9+). Ask before adding any dependency.
- Never loosen the read-only method allowlist in `scripts/odoo_client/safety.py`.
- `python3 -m pytest -q` must pass. Tests never touch the network.
- A new runtime file must also be listed in `install.sh` (a test checks this).
