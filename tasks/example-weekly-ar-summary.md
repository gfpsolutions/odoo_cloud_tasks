# Weekly accounts-receivable summary (example scheduled-task prompt)

Paste everything below the line into the scheduled task's prompt, then replace the DELIVERY line. Schedule it weekly, for example Monday at 07:10.

---

Produce this week's accounts-receivable summary from Odoo with the Odoo toolkit in your instructions. Work read-only.

1. Run `check`. If it fails, skip everything else and deliver only a short failure notice, with a subject starting with "FAILED: Weekly AR summary", that quotes the error message.
2. Window: the previous 7 full days in the report time zone. Run `period last-7-days --field invoice_date` and use its dates everywhere below.
3. Customer invoices posted in the window: `account.move` with move_type = out_invoice, state = posted and invoice_date in the window. Give the count and the total of `amount_total_signed`. Do the same for credit notes (move_type = out_refund).
4. Customer payments received in the window: `account.payment` with payment_type = inbound, partner_type = customer and a date in the window. First check its `state` options with `fields account.payment --filter state`, and leave out draft, cancelled and rejected payments. Give the count and the total amount.
5. Top 10 overdue customer balances as of today: posted customer invoices with payment_state not_paid or partial and invoice_date_due before today. Use `group` on partner_id with the aggregates `amount_residual_signed:sum,invoice_date_due:min`, ordered by `amount_residual_signed:sum desc`, limit 10. For each customer, give the overdue amount and how many days overdue their oldest unpaid invoice is.
6. Write a 5-line plain-language summary for a busy manager: what changed this week and what needs attention.

For every figure, state the window with its time zone, the filters used and the record count.

DELIVERY: <for example: create a Gmail draft to recipient@example.com with the subject "Weekly AR summary – <window>", the 5-line summary first and the tables below it>
