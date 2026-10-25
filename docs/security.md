# Authentication and CSRF contract

**Design only: Phase 1 exposes no authentication or state-changing business endpoints.**
These requirements must be implemented and tested with authentication in Phase 2.
An absent CSRF middleware in Phase 1 must not be mistaken for implemented protection.

## Sessions and roles

Use Argon2id password hashes through an established library, and cryptographically random
opaque session secrets. Store only hashes of cookie secrets in PostgreSQL. Public registration
always creates an ATTENDEE. Provision organizers with a controlled administrative command.
Every organizer action requires both role and event ownership. Every reservation action
requires its owner. Never accept user/organizer IDs from input as authority.

Use a host-only cookie, Path=/, HttpOnly, SameSite=Lax, and Secure in HTTPS environments.
Production cookie name: `__Host-csrs_session`, with no Domain attribute. Plain HTTP localhost
development uses `csrs_session` without Secure; it cannot use the `__Host-` prefix. Do not
store session secrets in browser localStorage/sessionStorage or return them in JSON.

## Unauthenticated registration and login

Login CSRF matters: an attacker could otherwise cause a victim to enter the attacker's
account. Registration also changes server state and uses the same protection.

1. Before showing/submitting either form, fetch `GET /api/v1/auth/csrf` through the same-origin API.
2. If there is no valid session, create a short-lived ANONYMOUS pre-session in PostgreSQL:
   null user ID, independently random cookie secret and CSRF token, 15-minute lifetime.
3. Send the opaque pre-session cookie using the attributes above. Return only the synchronizer
   CSRF token in a JSON response with `Cache-Control: no-store`. Keep the token in React memory.
4. Registration/login must submit JSON, the pre-session cookie, and `X-CSRF-Token`.
   Validate the unexpired pre-session and compare the submitted token with its stored value
   in constant time. A token from another session does not match.
5. Also enforce the trusted-origin rule below, before evaluating credentials or creating users.
6. Successful login deletes/revokes the pre-session and creates an independent AUTHENTICATED
   session with fresh cookie and CSRF secrets. Never promote/reuse the anonymous session ID.
   Return the new CSRF token with the user response. This prevents session fixation.
7. Registration creates an account without automatically logging in in the MVP. Replace its
   pre-session and return a fresh anonymous CSRF token for a subsequent login.
8. Failed login can retain its unexpired pre-session. Missing/expired pre-session or token
   yields 403 CSRF_FAILED; refetch the token before an intentional retry.

Bootstrap is the sole GET that may create security-session state; it does not mutate domain
data. Its response must never be cached. Same-origin response access and no permissive CORS
prevent another site reading the token. Rate-limit anonymous bootstrap/session creation in
the Redis integration phase and expire old pre-sessions; do not permit unlimited durable rows.

## Authenticated mutations

Every POST, PUT, PATCH, or DELETE business/auth request, including logout and idempotent
replays, requires the valid authenticated cookie, matching session-bound `X-CSRF-Token`, and
trusted origin. GET/HEAD never mutate domain data. Idempotency is not CSRF protection.

`GET /auth/csrf` with a valid authenticated session returns its current token rather than
replacing it on every request, so multiple tabs remain usable. A page reload refetches it.
Expired/revoked authentication yields 401 for protected operations. Logout requires CSRF,
revokes the session and clears its cookie; a subsequent bootstrap creates a new pre-session.

## Trusted-origin rule

For protected mutations, compare the full parsed scheme/host/effective port against the
configured `CSRS_PUBLIC_ORIGIN`. Prefer Origin; if absent, use the Referer origin. An explicit
untrusted or `null` Origin is rejected without falling back. If neither proves a trusted
origin, reject with 403 even if a token was supplied. Scripts and test clients must provide
the configured Origin plus their cookie and token; there is no non-browser bypass header.

Reject unexpected content types on JSON mutations with 415. Do not accept form-encoded
login bodies. Do not enable wildcard/reflective credentialed CORS. Development Vite proxies
the API while preserving Origin; localhost:5173 is the configured browser origin. Accessing
the UI through 127.0.0.1 instead requires an intentional matching configuration change.
Trust proxy headers only from explicitly configured infrastructure in a later deployment.

SameSite and JSON/custom headers provide defense in depth. They do not replace synchronizer
token and origin validation. XSS can bypass CSRF defenses; avoid unsafe HTML rendering and
add appropriate deployment headers later. Tokens must never enter URLs, logs, or cached responses.

## Phase 2 security acceptance tests

- Registration and login reject missing cookie, missing token, mismatched token, expired
  pre-session, hostile/null Origin, missing source origin, and unexpected media type.
- Origin matching rejects suffix tricks, wrong ports, and wrong schemes; Referer fallback
  is used only when Origin is absent.
- Successful login rotates both secrets and invalidates the anonymous cookie/token pair.
- Authenticated mutations and logout reject a token copied from another session.
- Revoked/expired sessions cannot act; GET CSRF responses are never cached.
- Public registration cannot set roles; cross-user and cross-organizer access is denied.
- Browser integration through the Vite proxy demonstrates cookie and header behavior.

References: [OWASP CSRF prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html),
[session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html),
[password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
