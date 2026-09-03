# Connector Overview

The gateway integrates with three external systems, each wired in
differently depending on whether the data is best treated as static
knowledge or live state.

## Jira (Live Path)

Jira sprint and ticket data changes constantly, so it is never pre-indexed
into `knowledge_chunks`. Instead, `live_data_node` calls the Jira connector
directly at query time whenever triage detects a sprint-status or
ticket-status style question. The response's `message_sources` entry is
tagged `source_type = 'jira'` so users can see the answer came from a live
call, not the knowledge base.

## Confluence (Embed Path)

Confluence pages are documentation-like and change relatively slowly, so
they're treated like any other document: pulled in through the ingestion
pipeline, chunked, embedded, and upserted into `knowledge_chunks` with
`source_type = 'confluence'` on the parent `documents` row. A scheduled sync
job re-ingests changed pages and logs each run to `sync_runs`.

## SharePoint (Live Path, Delegated OAuth)

SharePoint documents are often permission-sensitive at the individual-file
level in a way that's hard to mirror correctly into our own
`access_control` table, so SharePoint is wired as a live path using
delegated OAuth — the connector queries SharePoint on behalf of the
requesting user's own identity, which means SharePoint's own permissions are
enforced automatically rather than duplicated in our schema.

## Choosing Live vs Embed

As a rule of thumb: if staleness of a few minutes would give a wrong answer
(sprint status, ticket state), use the live path. If the content is
reference material that's fine to be slightly stale between syncs
(documentation, policies), use the embed path.
