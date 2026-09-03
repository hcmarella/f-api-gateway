# Billing FAQ

## How is usage calculated?

Billing is based on the number of chat completions processed per month, plus
a flat platform fee per team. A chat completion counts once per user message,
regardless of how many agent graph nodes (triage, rag_node, live_data_node,
etc.) it touches internally.

## What happens if we exceed our plan's included volume?

Overage is billed at a per-completion rate listed in your contract. There is
no hard cutoff — the gateway will continue serving requests past the included
volume, and overage charges appear on the next invoice. If you'd prefer a
hard cap instead of overage billing, contact your account manager.

## Can we get a usage breakdown by team or persona?

Yes. The admin panel exposes a usage report broken down by `team_id`, and
within a team, by persona (`business` vs `developer`). This pulls from
`audit_log` entries tagged with completion events.

## How do refunds work for outages?

If a SEV1 incident (see the incident response guide) causes more than 30
minutes of gateway downtime in a billing period, affected teams are
automatically credited a prorated amount on their next invoice. No action is
needed from the customer.

## Who do I contact for billing disputes?

Billing disputes go to billing-support@, not the on-call engineering
rotation. Engineering can pull usage data to help investigate a dispute but
does not own the billing relationship.
