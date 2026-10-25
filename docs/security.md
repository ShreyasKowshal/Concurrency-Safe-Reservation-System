# Authentication and CSRF contract

**Implemented in Phase 2:** registration, login, logout, current user, session bootstrap,
CSRF/origin validation, role guards, and local organizer provisioning. Event/reservation
mutations remain future contracts. The React page is still a health screen, not an auth UI.

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

## Implemented policy and transaction details

Registration accepts passwords of 15-128 characters; login accepts 1-128 so invalid credentials
are verified without applying registration policy to existing accounts. Passwords are never
trimmed or truncated. Argon2id uses 19,456 KiB memory, two iterations, one lane, a 16-byte random
salt, and a 32-byte hash. Successful login upgrades older Argon2 parameters when necessary.
Email addresses are validated without DNS lookup, stripped at the edges, converted to ASCII
(IDN domains become punycode), and lowercased. SMTPUTF8 local parts are intentionally unsupported.

Cookie secrets and independent CSRF values each contain 256 random bits. Database token
lookups use SHA-256 cookie digests. Synchronizer tokens are stored server-side as designed;
they are not independent authentication credentials. Authenticated sessions expire after
8 hours by default; pre-sessions after 15 minutes. Both are absolute database-clock deadlines.
Fetching CSRF again neither rotates the token nor extends database/cookie expiry.

Services own explicit transactions and commit before routes return Set-Cookie/success.
Registration/login first validate the anonymous session, release the read transaction, and
perform expensive password hashing/verification without holding a database transaction.
They then lock and revalidate the pre-session (including database-clock expiry and CSRF)
before atomically changing account/session state. A consumed pre-session cannot be reused
by a competing request. Login also locks/rereads the user and checks active status and that
the verified password hash has not changed. Rotation deletes the old anonymous session;
logout sets revoked_at. Later reads always check the current user active flag.

Unknown email, wrong password, and inactive account use the same 401 INVALID_CREDENTIALS
response. Unknown accounts perform a real Argon2 verification against a process-local dummy.
This mitigates obvious timing differences; it is not a claim of constant end-to-end latency.
Duplicate registration returns generic 409 REGISTRATION_UNAVAILABLE; the status can reveal
that an address cannot be registered. Request validation responses retain 422 detail/type/loc/msg
but remove input/ctx so passwords, CSRF values, and complete request bodies are not echoed.
All auth responses, including errors, are no-store. Duplicate/untrusted Origin headers are rejected.

Local administrators can run `python -m csrs.cli promote-organizer EMAIL` for an existing
active user. It revokes that user's existing sessions; the user logs in again. This command
requires database access and is never exposed as an HTTP role-selection endpoint.
`python -m csrs.cli purge-sessions --batch-size 1000` deletes one bounded batch of expired
or revoked security sessions, skipping rows locked by other transactions. Repeat as needed.

Rate limiting and automatic maintenance scheduling remain deferred; run bounded session
cleanup manually in this phase. No email verification, password recovery, MFA, or auth UI
is implemented. Cookie/CSRF protection does not substitute for those later product controls.
Future mutation handlers must combine the HTTP origin/JSON guard with session/CSRF validation
inside their service transaction; a read-only role dependency alone does not authorize a write.
Ownership guards must receive the owner ID read from the stored resource, never a claimed body ID.

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
