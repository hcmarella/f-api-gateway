# API Authentication

The gateway supports two authentication modes for external API consumers.

## API Key Authentication

Every team is issued a scoped API key when they're onboarded. Include it in
the `Authorization: Bearer <key>` header on every request. Keys are scoped to
a single `team_id` and cannot read or write data belonging to another team,
enforced at the query layer via the `access_control` table.

Keys can be rotated at any time from the admin panel. The old key remains
valid for 24 hours after rotation to allow in-flight deployments to pick up
the new one without downtime.

## OAuth for Interactive Users

Human users authenticate via OAuth against the company identity provider.
The resulting session maps to a row in the `users` table, which carries a
`persona` field (`business`, `developer`, or `admin`). The persona determines
which skills and knowledge sources a user's questions are allowed to match
against — see the skill routing documentation for details.

## Rate Limits

API key traffic is limited to 100 requests per minute per team by default.
Contact platform engineering if your integration needs a higher limit;
approved increases are configured per-key, not globally.

## Common Auth Errors

- `401 Unauthorized`: missing or malformed `Authorization` header.
- `403 Forbidden`: valid key, but the requested resource belongs to a
  different team, or the user's persona doesn't have access.
- `429 Too Many Requests`: rate limit exceeded; check the `Retry-After`
  header.
