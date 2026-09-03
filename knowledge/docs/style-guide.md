# Engineering Style Guide

## Python

Follow PEP 8 with a 100-character line limit. Type hints are required on
all new function signatures in `app/`. Prefer explicit imports over wildcard
imports. Async functions should be used for anything that does I/O (database
calls, HTTP calls to connectors), but synchronous code is fine for pure
computation like chunking or cosine similarity.

## Commit Messages

Write commit messages that explain why a change was made, not just what
changed — the diff already shows what changed. Reference the ticket number
when one exists. Avoid vague messages like "fix bug" or "updates."

## Agent Graph Nodes

Every node added to `app/agents/graph.py` should be small enough to unit
test in isolation with a mocked model call. Nodes should never write directly
to `knowledge/skills/` — any content that ends up in the knowledge base
either comes through the ingestion pipeline or through the reviewed
`content_review_queue` approval flow, never a direct file write from an
agent node.

## Database Migrations

Migrations should be additive and backward-compatible with the previous
application version for at least one release, per the deployment runbook.
Never drop a column in the same migration that stops writing to it — split
those into two separate releases.

## Testing

New ingestion or embedding code should include a runnable test script (not
just assertions in CI) so a human can eyeball real numbers, following the
pattern in `test/test_embed_similarity.py`.
