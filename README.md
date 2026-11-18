# odoo_cloud_tasks

Read-only Odoo reports that run on a schedule in Claude's cloud, with everyone's computer off. Works with Odoo 18 and 19.

- **Generic code, no secrets.** This repository has no keys, Odoo addresses, database names, logins or client notes. The same tagged release serves every client.
- **Each client runs it from their own Claude account.** The scheduled tasks, the cloud environment and the delivery connectors (their Gmail, their Slack) are theirs.
- **Clients don't need a GitHub account.** The scheduled task has no repository attached. Instead, the cloud environment's setup script downloads a tagged release of this public repository from `raw.githubusercontent.com`, which serves public files to anyone.
- **Read-only in code.** Only read methods can be called (`search_read`, `search_count`, `search`, `read`, `read_group`, `formatted_read_group`, `fields_get`, `name_search`, `context_get`), and security-related models are always blocked. No flag or variable changes that.

## How a run works

1. The scheduled task starts a fresh cloud VM in the client's cloud environment.
2. The VM starts from the environment's cached setup: the setup script has installed this toolkit in `/opt/odoo_cloud_tasks` and written Claude's instructions plus the client's company notes to `~/.claude/CLAUDE.md`, which Claude Code loads in every session.
3. Claude follows the task's prompt and queries Odoo with `python3 /opt/odoo_cloud_tasks/scripts/odoo.py …` through Anthropic's proxy.
4. Claude delivers the result through the connectors the task includes (for example a Gmail draft).

## Where secrets live

| Place | What it holds |
|---|---|
| This GitHub repository | Nothing, ever. A test and a pre-commit hook enforce it. |
| Odoo 19 or later | The API key as a **network secret** on the client's cloud environment. Anthropic's proxy adds it to requests for the Odoo host after they leave the VM, so the key never exists inside the VM. Don't set `ODOO_API_KEY`: the toolkit refuses to run if you do. |
| Odoo 18 | The API key as the `ODOO_API_KEY` **environment variable** on the client's cloud environment. Odoo 18 only accepts the key inside the request body, which the proxy can't fill in. Sessions in that environment can read it, so keep the environment personal (not shared with an organization). |
| Company notes | The environment's setup script. Not secret, but client-specific. |

## 0. First time only: check the GitHub-free setup (about 15 minutes)

Every piece of this setup is documented by Anthropic, but not the whole flow in an account without GitHub. Check it once, in a claude.ai account with no GitHub connected (a spare account, or the client's during setup):

1. At claude.ai/code, finish the first-time setup without connecting GitHub.
2. Create an environment (see step 3 below for the network settings) whose setup script is:
   ```bash
   #!/bin/bash
   set -euo pipefail
   curl -fsSL "https://raw.githubusercontent.com/<github-owner>/odoo_cloud_tasks/v1.0.0/install.sh" | bash -s -- "<github-owner>/odoo_cloud_tasks" "v1.0.0"
   echo "Say TEST-NOTES-LOADED at the start of your reply." >> ~/.claude/CLAUDE.md
   ```
3. At claude.ai/code/routines, create a scheduled task with **no repository**, in that environment, with the prompt: `Run python3 /opt/odoo_cloud_tasks/scripts/odoo.py --version, then run printenv.` If the form won't create a cloud task without a repository, add an API trigger (and don't keep its token).
4. Click **Run now** and open the run. Expected: the reply starts with TEST-NOTES-LOADED, the version prints, and `printenv` is refused by a permission rule. Don't add the Odoo variables to this test environment yet, so nothing sensitive can print if the rule doesn't apply.

If the task can't be created without a repository, or can't use that environment, the fallbacks are running the tasks from your own account, or attaching the repository (which needs a GitHub account on the account running the task).

## 1. Publish the repository (once)

1. Before the first commit, enable the pre-commit hook with `git config core.hooksPath .githooks`. Repeat this in each new clone.
2. Run `python3 tests/secret_scan.py` from the repository root to scan tracked files and new, non-ignored files. Resolve any findings and rerun until the scan passes.
3. Stage and commit the reviewed files. The hook checks the staged contents. Create a **public** GitHub repository named `odoo_cloud_tasks` and push the commit.
4. Tag the release with `git tag v1.0.0 && git push origin v1.0.0`. Each client's setup selects its release tag. GitHub Actions runs the tests on every push.

## 2. Odoo side (per client)

1. Create a dedicated internal user, for example "Claude Reports", with only the read rights the reports need (Sales, Invoicing or Accounting read-only, Inventory…). Odoo's access rights are the real boundary. Allowed companies: the ones to report on.
2. Log in as that user and create an API key: Preferences → Account Security → New API Key. Copy it once.
   - On Odoo 18 and 19 a non-admin user's key lasts **at most 90 days** by default. Set a reminder to rotate it. An Odoo admin can raise "API Keys maximum duration days" on a group the bot belongs to (developer mode, Settings → Users & Companies → Groups), at the cost of a longer-lived key.
3. On Odoo Online, the external API needs a Custom plan.
4. The Odoo host must be reachable from the internet: requests come from Anthropic's network, not from the client's office. A VPN-only or IP-restricted Odoo blocks them.

## 3. The client's cloud environment (per Odoo database)

At claude.ai/code, open the environment selector under the message box → **New environment**. Keep it personal.

**Network access:** Limited. Uncheck **Allow package managers**. The default list includes cloud storage hosts a hijacked session could use to send data out, and this toolkit installs nothing. In **Allowed domains**, add:
- `raw.githubusercontent.com` (the setup script downloads the toolkit from it)
- the Odoo host, for example `mycompany.example.com` (Odoo 18; on 19 the network secret already makes the host reachable)

**Environment variables**, Odoo 18:
```
ODOO_URL=https://<odoo-host>
ODOO_PROTOCOL=jsonrpc
ODOO_DB=<database name>
ODOO_LOGIN=<bot user login>
ODOO_API_KEY=<API key>
```

**Environment variables**, Odoo 19 or later (no key here):
```
ODOO_URL=https://<odoo-host>
ODOO_PROTOCOL=json2
ODOO_DB=<database name, only if the host serves several databases>
```

**Network secret** (Odoo 19 or later only): Network secrets → Add secret → type **Bearer**; Allowed websites: the Odoo host, exactly; header `Authorization`, prefix `Bearer` (Odoo accepts it in any case); value: the key. On Team plans without an admin role the form is shorter: Host, Token.

Set `ODOO_URL` to the final HTTPS address. The client rejects redirects, including redirects to another HTTPS address.

Optional variables: `ODOO_TZ` (report time zone, default `Europe/Paris`), `ODOO_TIMEOUT` (seconds, default 60), `ODOO_ALLOWED_MODELS` (comma-separated models). The model list restricts direct queries and scopes discovery to those models. When it is set, `guide` lists installed modules only if it includes `ir.module.module`. Odoo's access rules govern the records and related data the reporting user can read.

**Setup script:** copy `setup-script-TEMPLATE.sh`, set `REPO` and `VERSION`, paste the client's company notes (start from `company-notes-TEMPLATE.md`; the desktop extension's notes file works as is), and paste the result into the Setup script field. Keep the filled-in copy outside this repository, for example in `~/.odoo_cloud_tasks/<client>/setup.sh`.

## 4. A scheduled task (per report)

At claude.ai/code/routines → **New task**:
- **No repository.** Choose the client's environment.
- **Prompt:** start from a file in `tasks/` and fill in its `DELIVERY:` line. A good prompt says what to compute, the window, and where to deliver.
- **Schedule:** a few minutes past the hour (runs set exactly on the hour can start late). Preset times are in local time; a raw cron expression is in UTC unless it starts with `CRON_TZ=Europe/Paris`.
- **Connectors:** keep only the ones the delivery needs.
- If the form only treats the task as a cloud task once a trigger is added, add an API trigger and don't keep its token.

Click **Run now** once and read the transcript. A run marked "Succeeded" only means the session ended normally, so check that the report actually arrived. The prompts in `tasks/` deliver a "FAILED:" notice when Odoo can't be reached.

## 5. Local testing

Export the variables in your shell, or keep one file per client **outside** the repository and load it:
```bash
set -a; source ~/.odoo_cloud_tasks/<client>.env; set +a
python3 scripts/odoo.py check
```
On your machine (where `CLAUDE_CODE_REMOTE` isn't `true`), `ODOO_PROTOCOL=json2` accepts `ODOO_API_KEY` and sends it as the bearer token, so you can test Odoo 19 before a client goes live. In the cloud it refuses.

Tests: `pip install -r requirements-dev.txt && python3 -m pytest -q` (no network needed).

## 6. Commands

All print JSON on stdout; errors go to stderr with a non-zero exit code. `python3 scripts/odoo.py COMMAND --help` explains each one.

| Command | Purpose |
|---|---|
| `check` | Protocol, auth mode (never the key), Odoo version, database, user, companies, test count. Run first. |
| `guide` | Custom modules, custom (Studio / `x_`) fields and custom models. |
| `models [--filter TEXT]` | Find a model by keyword. |
| `fields MODEL [--filter TEXT]` | Field names, labels, types, relations and selection options. |
| `search MODEL --domain JSON --fields a,b [--limit 200] [--order …] [--all --csv out/x.csv]` | Records; `--all` pages through up to 20,000 into a file. |
| `count MODEL --domain JSON` | Number of matching records. |
| `group MODEL --domain JSON --groupby f[:month],… --aggregates f:sum,… [--order …] [--csv …]` | Server-side totals and breakdowns. |
| `read MODEL --ids 1,2 [--fields a,b]` | Records by id. |
| `period PERIOD [--field F]` | A date window in `ODOO_TZ`, with ready-made domains for date and datetime fields. |

Files can only be written under `out/`. Many2one values come back as `{"id", "name"}`, date groups as `{"start", "label"}`, and every query includes all the companies the Odoo user can access.

## 7. Maintenance

- **Upgrade a client:** tag a new release, then change `VERSION` in that client's setup script. The environment rebuilds on its next run.
- **Update company notes:** edit them in the setup script.
- **Rotate the key:** Odoo 18, edit `ODOO_API_KEY`; Odoo 19, delete the network secret and add it again (values can't be edited).
- **Odoo 18 → 19:** set `ODOO_PROTOCOL=json2`, remove `ODOO_LOGIN` and `ODOO_API_KEY`, and add the key as a network secret. `check` suggests this when it sees Odoo 19 on `jsonrpc`.
- **Revoke access now:** delete the bot user's API key in Odoo (or archive the user).

## 8. Troubleshooting

| Message | Fix |
|---|---|
| "… is not set. Set it on the Claude cloud environment …" | Add that variable to the environment. |
| "ODOO_API_KEY must not be set for json2 …" | Remove `ODOO_API_KEY` and store the key as a network secret. |
| "… network access doesn't allow &lt;host&gt; …" | Add the host to Allowed domains (Odoo 18), or make the network secret's allowed website match the host exactly (Odoo 19). |
| "HTTP 401 … network secret is missing, expired or not matched to this host" | Odoo 19: the key expired (90 days at most), the secret's host doesn't match `ODOO_URL`, or the prefix isn't `Bearer`. |
| "Odoo rejected the login" | Odoo 18: wrong `ODOO_DB`, `ODOO_LOGIN` or `ODOO_API_KEY`, or the key expired. The login must belong to the key's owner. |
| "Odoo error [AccessError] …" | The bot user lacks read rights for that data. |
| "HTTP 404 … JSON-2 needs Odoo 19" | The server is Odoo 18: use `ODOO_PROTOCOL=jsonrpc`. Or `ODOO_URL` has an extra path. |
| "did not return JSON" | `ODOO_URL` points at a website or firewall in front of Odoo; use the Odoo address itself. |
| The setup script fails | The tag or repository name is wrong, or `raw.githubusercontent.com` isn't in Allowed domains. |
| Run "Succeeded" but no report arrived | Open the run's transcript; the error is there. |

Background: [Configure cloud environments](https://code.claude.com/docs/en/cloud-environments), [Scheduled tasks](https://code.claude.com/docs/en/routines), [Odoo External JSON-2 API](https://www.odoo.com/documentation/19.0/developer/reference/external_api.html).
