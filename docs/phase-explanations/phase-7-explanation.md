# Phase 7 explained: a real browser experience for reliable reservations

This phase is implemented locally and remains uncommitted for external review.
The [validation report](../validations/phase-7-validation.md) records exact evidence and limitations.
The project handoff deliberately remains the approved Phase 6 snapshot.

## 1. Phase overview

Before this phase, a developer could reserve seats using HTTP tools. Now an attendee can
use a normal website: discover an event, log in, hold one seat, confirm it, and inspect history.
An organizer can create and manage events and see a private booking snapshot.

The browser is the friendly front desk. PostgreSQL remains the official reservation ledger.
Making the front desk attractive does not give it permission to invent available seats.

## 2. What we implemented

- Responsive discovery cards, event details and advisory availability.
- Registration, login, session restoration, logout and role-aware navigation.
- Holds, server-anchored countdowns, confirmation, cancellation and private history.
- Organizer draft creation/editing, capacity, publication, closure and booking snapshots.
- Structured errors, safe uncertain retries, accessible dialogs and keyboard behavior.
- Component/API tests and separate real-browser Compose journeys.

There are no fake production events, payments, email notifications or cloud deployment.

## 3. Technologies used

| Technology | Simple purpose |
| --- | --- |
| React 19 | Describes the screen from current data and updates it when that data changes |
| TypeScript 5.9 | Checks that components and API calls use expected data shapes |
| Vite 7 | Runs the development server, proxies the API, and builds the browser files |
| React Router | Gives each screen a real address and supports back/forward navigation |
| Zod | Checks actual JSON at runtime; TypeScript alone cannot validate server responses |
| CSS | Provides the cream/green visual identity, responsive grids, states and focus styles |
| Vitest and Testing Library | Exercise components, transport errors, timers and interactions |
| Playwright and axe | Exercise Chromium against the real stack and check accessibility basics |

No Redux, component framework, or second authentication system was added.

## 4. How everything works

React renders cards from `GET /api/v1/events`. Clicking one opens `/events/:id`, which loads
its metadata and a separate availability snapshot. Availability might say one seat remains.
That describes a moment in time, so the Hold button still asks FastAPI to make a real decision.

Before login/registration, the API issues an anonymous cookie and returns a CSRF token.
The cookie is HttpOnly, so JavaScript cannot read its secret. The token stays in memory and
is sent in X-CSRF-Token on JSON mutations. The browser includes the cookie automatically.
FastAPI checks that the cookie, token, and trusted browser origin agree.

Registration creates an attendee account but leaves it logged out. Login rotates the cookie
and token. On reload, `/auth/me` restores the identity, while a later mutation obtains the
current token again. Public users cannot choose organizer privileges. Logout clears private UI
state; account changes abort old reads so a previous user's response cannot fill a new screen.

A hold submits `{}` with a new Idempotency-Key. If the response is lost after PostgreSQL commits,
the browser retains the same key for another attempt. The backend can return the original
outcome without allocating another seat. Afterward, the frontend reads current reservation
detail because a replay body might describe an older state. After reload loses an in-memory
intent, private history is checked before starting another hold.

The countdown uses the returned hold deadline and server time, then measures elapsed time
with a monotonic timer. A device with the wrong date still sees a useful estimate. Network
delay and timer throttling mean it is advisory. At zero, the UI rereads the server and stops
offering a fresh confirmation. A server rejection wins even if the timer showed time left.

Confirming and cancelling are separate authenticated commands with separate keys. The UI
displays CONFIRMED or CANCELLED only after fresh server state supports it. Releasing a hold
and cancelling a confirmed seat use distinct labels and require a confirmation dialog.

## 5. Important files and folders

| Path | Responsibility |
| --- | --- |
| frontend/src/App.tsx | Layout, routes, guards and per-resource component identities |
| frontend/src/session.tsx | Session restoration, role navigation and account isolation |
| frontend/src/api/client.ts | Cookies, CSRF, errors, timeouts, retry keys and reconciliation |
| frontend/src/api/models.ts | Runtime-validated API response shapes |
| frontend/src/hooks.ts | Read cancellation/stale results and departed-screen guards |
| frontend/src/pages/ | Account, event, reservation and organizer screens |
| frontend/src/components/ | Shared feedback, dates/statuses, dialogs and countdown |
| frontend/src/styles.css | Reusable visual rules and mobile/tablet/desktop layouts |
| frontend/e2e/journeys.spec.ts | Real backend journeys, contention, response loss and accessibility |
| backend/src/csrs/events/dashboard.py | Owner-only write-free booking counts and pagination |
| backend/scripts/frontend_fixture.py | Local UUID-scoped browser fixtures and cleanup |

## 6. API endpoints and running the system

The browser uses the existing auth, event, organizer and reservation routes described in
the [API contract](../contracts/api.md). Phase 7 adds only
`GET /api/v1/organizer/events/{event_id}/dashboard`.

```powershell
docker compose up --build -d --wait --wait-timeout 120
docker compose exec -T backend python -m alembic upgrade head
docker compose --profile worker up --build -d worker
```

Open `http://localhost:5173`. Vite forwards `/api` to FastAPI while keeping the original
browser Origin. Use localhost rather than changing hostnames without updating configuration.
Organizer access is provisioned through the existing local admin CLI, followed by a new login.
See the [README](../../README.md) for host development and verification commands.

## 7. Database design

No database table or migration changed. Users, sessions, events, reservations and idempotency
records retain their existing roles. The worker index remains at `0002_worker_expiry`.

The new dashboard reads one event and its reservations in one SQL snapshot. It separates
valid holds from overdue stored holds, confirmed bookings, cancellations and recorded expiry.
For example, a delayed worker can leave two overdue HELD rows in the stored allocation count.
The dashboard labels those two explicitly instead of calling them valid bookings.

Organizer rows expose reservation identifiers and times, not customer email addresses.
Attendee history still belongs only to that attendee. If an event is closed, public metadata
becomes unavailable, so history retains the event ID and explains the missing metadata.

## 8. Security and correctness

Frontend guards are helpful navigation. FastAPI still verifies the actual session, role,
ownership and CSRF for protected operations. No secret is put in a frontend environment variable.
No token/password/retry key is stored in localStorage, and untrusted event text is escaped.
Redirects accept known internal paths only. Unknown server error strings are not displayed.

When Redis denies a quota, the UI explains 429 and shows trustworthy numeric Retry-After.
There are no automatic retries. During Redis outages, registration/login can return 503;
public reads and authenticated commands may continue through PostgreSQL. Continuing a request
does not mean it succeeded: the UI still waits for the real SQL-backed response.

## 9. Testing and verification

Component tests feed controlled HTTP responses to the actual client. They include bad data,
expired sessions, denied roles, final-seat conflict, uncertain retries and timer boundaries.
They do not prove PostgreSQL locking. The retained backend integration suite does that with
real PostgreSQL/Redis and independent processes.

Separate browser tests use actual Vite/FastAPI/PostgreSQL/Redis/worker services. Two browser
sessions reach a request barrier before competing for one seat; exactly one must receive 201.
A response-loss test forwards an actual hold, drops its successful HTTP delivery, then checks
same-key recovery. A local fixture adjusts only its own hold for expiration checks and removes
its scoped rows afterward. SQL reconciliation checks counters, capacity and active uniqueness.

Accessibility checks include labels, heading structure, automated axe scans, visible keyboard
focus, native dialog dismissal/restoration, and mobile overflow. These are practical checks,
not a formal claim of complete WCAG compliance. Exact results are in the validation report.

## 10. What was NOT implemented yet

Phase 8 deployment, production benchmarks, payments, email/SMS, account recovery/MFA, numbered
seats, ticket transfers, waitlists and advanced analytics remain outside this phase. The
frontend supports the same-origin local architecture; it does not introduce cross-origin hosting.
Screen-reader assistive technology and non-Chromium browsers require further manual verification.

## 11. Interview preparation

Explain why a displayed seat count is advisory: another transaction can take the final seat
before a later request obtains the event lock. Explain why a failed fetch does not prove rollback:
the server might have committed before its response disappeared. Explain why a timer cannot
confirm a seat: PostgreSQL samples the decision time after acquiring the event lock.

Describe the difference between unit/component and browser integration evidence. Explain the
dashboard's distinction between effective expiration and stored cleanup. Show the account-isolation
test and how old reads are aborted rather than cached across users. Discuss the deliberate
tradeoff of checking private history before a new hold: extra reads buy safer recovery after reload.

## 12. Phase summary

CSRS now has usable attendee and organizer browser flows connected to the real backend.
The database reservation protocol remains authoritative. Implementation and local verification
are ready for external review; nothing is committed, pushed, merged, or deployed in this task.
