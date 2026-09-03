# Password Reset

## For End Users

Users authenticating via OAuth do not have a password managed by us — reset
requests should be directed to the company identity provider's own reset
flow. We cannot reset a password we don't store.

For the small number of legacy accounts still on local password auth
(pre-OAuth migration), use the "Forgot password" link on the login page. This
sends a time-limited reset link to the account's registered email. Links
expire after 30 minutes and can only be used once.

## For API Keys

API keys are not passwords and don't have a "reset" flow — see the API
authentication documentation for how to rotate a key instead.

## Troubleshooting

**User says the reset email never arrived**: check the mail delivery logs
first; most cases are a typo'd email or spam filtering, not a bug in the
gateway. Confirm the email in the `users` table matches what the user
expects.

**Reset link says "expired" immediately**: this usually means there's a
clock skew issue between the service issuing the link and the service
validating it. Check both containers' system time.

**User wants to change their email as part of the reset**: email changes
must go through identity verification separately; a password reset link
cannot also change the account email.
