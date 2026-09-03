# Rate Limits and Throttling

## Default Limits

Every team's API key is limited to 100 requests per minute by default,
enforced at the gateway edge before any request reaches the agent graph.
Limits are tracked per `team_id` in Redis using a sliding window counter.

## Why Redis and Not Postgres

Rate limiting needs to check and increment a counter on every request with
minimal latency, so it's implemented against Redis rather than Postgres.
If Redis is unavailable, the gateway currently fails open (allows the
request) rather than failing closed, to avoid an outage in the rate limiter
taking down the whole product. This tradeoff is intentional and documented
in the incident response guide's Redis-unavailable section.

## Requesting a Higher Limit

Teams that need more than 100 requests per minute should contact platform
engineering with their expected peak volume. Increases are applied per-key
in the admin panel and take effect within a minute, no deploy required.

## What Counts Against the Limit

Every call to `/ai/chat` counts once. Internal agent graph node executions
(triage, rag_node, live_data_node, etc.) triggered by a single chat request
do not count separately. Admin endpoints like the review queue are not
subject to the same per-team chat rate limit; they have their own, higher
limit intended for internal tooling.

## Rate Limit Response

When throttled, the gateway returns `429 Too Many Requests` with a
`Retry-After` header indicating seconds until the window resets. Clients
should back off rather than retrying immediately.
