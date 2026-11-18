# Odoo notes for Claude: <Client company name>

<!--
Fill in the sections below and delete what doesn't apply. For scheduled tasks, paste the result
into the client's environment setup script, between the COMPANY_NOTES lines of
setup-script-TEMPLATE.sh. Claude reads it at the start of every run and follows it over its general
Odoo knowledge. The same file works as the desktop extension's company notes file.
Write it like a briefing for a new analyst: plain language, exact technical names in backticks,
under about 10 pages. Whenever Claude gets a figure wrong, add a line here rather than correcting
it in a prompt.
-->

## Company basics
- Odoo version: 18 (Odoo Online / Odoo.sh / self-hosted)
- Companies in this database: `1` = Acme France (EUR), `2` = Acme Spain (EUR)
  - Unless the task names a company, report on: <all companies / company 1 only>
- Fiscal year: January to December
- Main currency: EUR. Use the `_signed` amount fields for company-currency totals.

## How to calculate key figures (business rules)
- **Revenue / turnover**: posted customer invoices minus credit notes, untaxed:
  `account.move`, `move_type in (out_invoice, out_refund)`, `state = posted`, sum `amount_untaxed_signed`, by `invoice_date`.
- **Orders booked**: `sale.order` with `state = sale`, by `date_order`, sum `amount_untaxed`.
- **Margin**: <e.g. `sale.order.line.margin`, needs the sale_margin module; or "ask me">
- **Overdue receivables**: `account.move`, `move_type = out_invoice`, `state = posted`, `payment_state in (not_paid, partial)`, `invoice_date_due < today`, sum `amount_residual_signed`.
- **Exclude** from all sales figures: <e.g. internal customer "Acme Intercompany" (res.partner id 123), test products starting with "TEST-">

## Custom modules (what they do)
- `acme_sale_ext`: adds a Region on quotations and a commission calculation for agents.
- `acme_project_site`: tracks installation sites (`x_project_site`) linked to sale orders.

## Custom fields (meaning and when to use them)
| Model | Field | Meaning |
|---|---|---|
| `sale.order` | `x_studio_region` | Sales region (North / South / Export). Use for "sales by region". |
| `res.partner` | `x_customer_segment` | A / B / C customer classification. |
| `sale.order.line` | `x_commission_amount` | Agent commission on the line, in EUR. |

## Custom workflow / statuses
- Quotations above 10,000 EUR go through an approval step: field `x_approval_state` (draft → to_approve → approved). "Pending approvals" means `x_approval_state = to_approve`.

## Things that look useful but are wrong
- Don't use `sale.order.amount_total` for revenue: it includes VAT and unconfirmed orders.
- The analytic account "OLD-2023" is archived history; ignore it.
- Product category "Services / Internal" is internal time; exclude it from sales reports.

## Standard reports (recipes)
### Monthly sales pack
- Revenue by month (this year vs last year), by region (`x_studio_region`), top 10 customers.
- Output: Excel file with one sheet per table, plus a short summary paragraph.

### Aged receivables
- Buckets 0-30 / 31-60 / 61-90 / 90+ days past `invoice_date_due`, per customer, `amount_residual_signed`.

## Vocabulary
- "Jobs" = sale orders. "Sites" = `x_project_site`. "Agents" = salespeople (`user_id`).
