# SSO Setup for New Teams

When onboarding a new customer team that wants SSO instead of individual
logins, follow this process.

## Gathering Requirements

Ask the customer which identity provider they use (Okta, Azure AD, Google
Workspace are all supported). You'll need their SAML metadata URL or OIDC
discovery endpoint, plus the list of email domains that should be allowed to
authenticate under their `team_id`.

## Configuration

SSO configuration lives per-team in the admin panel, not in environment
variables — this lets each customer team have independent SSO settings
without redeploying the gateway. Add the identity provider metadata, map
their group claims to our `persona` values (business/developer/admin), and
set the allowed email domains.

## Testing

Before enabling SSO for a team in production, test with a single pilot user
in staging. Confirm: the user can log in, lands with the correct persona,
and their `team_id` is set correctly so they only see their own team's
knowledge base and conversation history.

## Common Pitfalls

- Forgetting to map a group claim means every SSO user defaults to the
  `business` persona, even actual developers — always verify the mapping
  with a real developer-team test user.
- SAML clock skew between the identity provider and our service can cause
  intermittent login failures; if a customer reports "works sometimes,"
  check clock sync first.
