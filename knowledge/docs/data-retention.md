# Data Retention Policy

## Conversation History

Conversations and messages are retained for 18 months by default, after
which they are hard-deleted by a nightly cleanup job. Teams on an enterprise
contract can request a custom retention window, configured per `team_id`.

## Knowledge Base Content

Rows in `knowledge_chunks` are retained until the source document is deleted
or the connector that produced them (local_md, confluence, sharepoint) marks
them stale during a re-sync. There is no automatic time-based expiry for
knowledge content — it's treated as intentionally curated, not ephemeral.

## Audit Logs

`audit_log` entries are retained for 7 years to satisfy compliance
requirements, regardless of a team's conversation retention setting. This
table is append-only; entries are never modified or deleted through normal
application code paths.

## Content Review Queue

Entries in `content_review_queue` are retained indefinitely, whether
approved or rejected, so that the history of what was proposed and why is
always available for audit. Only the underlying knowledge file changes when
an entry is approved; the queue row itself is never cleaned up.

## Deletion Requests

If a customer requests full data deletion (e.g. for GDPR/right-to-erasure),
that's handled as a manual, one-off process by the data team, not through
the standard retention job — file a ticket rather than trying to script it
yourself.
