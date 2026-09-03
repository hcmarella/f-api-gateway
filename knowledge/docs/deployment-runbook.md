# Deployment Runbook

This document describes how to ship a change to the forge-api-gateway
production environment.

## Pre-Deploy Checklist

1. All CI checks are green on the PR: unit tests, the embedding sanity test,
   and the lint job.
2. The PR has been reviewed and approved by at least one other engineer.
3. If the change touches `db/schema.sql`, confirm the migration has been
   tested against a copy of the production database size, not just a fresh
   empty database. Migrations that add a column with a default value can lock
   large tables.
4. If the change touches `app/agents/graph.py`, re-run the full test question
   suite from the agent graph tests and confirm each question still routes to
   its expected branch.

## Deploy Steps

Deploys are triggered by merging to `main`. The CI pipeline builds the Docker
image, pushes it to the registry, and applies a rolling update to the
gateway service. Postgres and Redis are not redeployed as part of an
application release; schema migrations run as a separate, explicit step
before the application rollout begins.

Watch the rollout in the deploy dashboard. A rollout is considered healthy
when `/health/deep` returns `postgres: ok` and `redis: ok` from at least two
replicas for 60 consecutive seconds.

## Rollback

If error rates spike after a deploy, roll back immediately rather than trying
to hotfix forward. Rollback re-points traffic at the previous image tag; it
does not revert schema migrations, so migrations must always be
backward-compatible with the previous application version for at least one
release cycle.

## Post-Deploy

After a deploy, spot-check a few real questions against `/ai/chat` and
confirm the sources returned look correct, especially for any release that
touched the RAG or connector pipelines.
