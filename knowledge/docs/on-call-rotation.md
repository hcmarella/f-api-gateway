# On-Call Rotation

## Schedule

On-call rotates weekly, Monday to Monday, handoff at 10am. The rotation
covers the gateway, its Postgres/pgvector database, Redis, and the connector
sync jobs (Jira, Confluence, SharePoint). It does not cover customer-specific
SSO configuration issues, which route to the identity team instead.

## Primary vs Secondary

Primary on-call gets paged first for any SEV1 or SEV2. Secondary is paged
automatically if primary doesn't acknowledge within 5 minutes, and should
also be treated as a backup for anything primary needs a second pair of eyes
on, like a risky rollback decision.

## Handoff Checklist

At the end of your rotation, write a short handoff note in `#on-call` listing
any open incidents, anything you fixed that might regress, and anything
you're still keeping an eye on (e.g. "watching connector sync latency, been
creeping up but not alert-worthy yet").

## Expectations

You're expected to acknowledge a page within 5 minutes during business hours
and 15 minutes overnight. If you're going to be unavailable during your
rotation (travel, appointment), arrange a swap in advance rather than letting
a page go unanswered.

## Escalation

If you're stuck on a SEV1 for more than 30 minutes without progress, escalate
to the engineering manager on duty rather than continuing to debug solo.
Escalating early is never held against you; a prolonged unresolved SEV1 is
worse than "unnecessarily" pulling someone else in.
