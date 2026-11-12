# ADR-0009: Staff JWT, reload the user, scope by venue from the principal

**Status:** Accepted

## Context
Staff from different venues (a college office, a hospital) share one deployment. Visitors are anonymous; only staff authenticate.

## Decision
* `POST /api/auth/login` verifies a bcrypt hash and returns an HS256 JWT with `sub`, `venue_id`, `role` and a 60-minute expiry.
* `get_current_staff` decodes the token **and reloads the user from the DB**, rejecting it if they're missing or `is_active = false`. Role changes and deactivation therefore take effect immediately, not at token expiry.
* `require_role("admin")` is a dependency factory that gives declarative RBAC per route.
* Every staff query filters by `current_staff.venue_id`. A resource in another venue returns **404, not 403**, so its existence isn't leaked.

## Alternatives rejected
* **Trusting claims without reload:** a fired staff member keeps access for up to 60 minutes.
* **Sessions/cookies:** fine too, but the JWT matches OpsFlow and works for the separate display board origin.
* **PostgreSQL row-level security:** stronger defence in depth; documented as the production next step.

## Consequences
* One extra primary-key lookup per staff request, which is negligible.
* JWTs are signed, not encrypted: never put secrets in claims.
