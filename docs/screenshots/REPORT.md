# Screenshot capture and verification report

Date: **29 October 2026**, Asia/Kolkata. Documentation-only assignment on `main`
at `89e27fae0c9fce5567167f6f5216b1fbb7067c58`. The application remains local to
Docker Compose; nothing was publicly deployed.

This report preserves the capture-stage review snapshot. Its unstaged Git state
and stop-for-review statements below describe that earlier checkpoint. Subsequent
authorized publication and hosted CI are recorded in the [project handoff](../PROJECT_HANDOFF.md).

## Output and complete manifest

Folder: `C:\Users\ASUS\OneDrive\Desktop\csrs\docs\screenshots`.

**73 final PNGs: 72 distinct browser captures plus one labeled comparison.**
The completed scenarios produced 77 browser captures; five byte-identical repeated
states were deduplicated. The collection occupies **5,304,071 bytes (5.30 MB)**.
The [complete image manifest](MANIFEST.md) lists every file, dimensions, and SHA-256.

| Category | Images |
| --- | --- |
| Public website | 5 |
| Authentication | 4 |
| Organizer lifecycle and booking snapshots | 20 |
| Attendee reservations and expiration | 12 |
| Final-seat concurrency, including comparison | 6 |
| Errors and access control | 10 |
| Responsive layouts | 16 |
| Total | 73 |

## Workflows represented

- Public hero, logged-out navigation, published discovery, metadata, full/zero availability,
  publication visibility, and disappearance after closure.
- Login, registration, one incorrect-credentials response per capture run, native required-field
  validation verification, signed-in navigation, and real session revocation with login required.
- Owner workspace, empty workspace, draft/published/closed cards, empty and completed creation
  forms, populated edit, location change, capacity 5 to 6, publish/close dialogs, locked published
  schedule, and closed read-only view.
- Empty, HELD, CONFIRMED, CANCELLED, EXPIRED, and mixed-status owner booking snapshots with
  allocation metrics.
- Hold, countdown, confirm timestamp, cancellation dialog and timestamp, released availability,
  release-hold dialog, mixed private history, detail navigation, and retained confirmed history
  after event closure.
- Two isolated final-seat sessions, real successful/rejected requests, full public detail, winner
  confirmation, owner allocation 1, and availability returning after cancellation.
- Role denial, privacy-preserving foreign-resource denial, closed public detail, invalid schedule,
  capacity below allocations, network-read error/retry, and durable recovery after response delivery
  loss.
- Eight representative pages at both 768px and 390px, alongside 1440px desktop captures.

The [coverage matrix](COVERAGE.md) maps these to actual routes and records all gaps.

## Final-seat evidence and its limits

Two real browser contexts read availability 1. A request barrier, following the
existing E2E pattern, released the actual hold requests: **one HTTP 201 and one
HTTP 409 EVENT_FULL**. Attendee B won this run. The winner then confirmed the
same reservation. Both the owner UI and read-only SQL showed **capacity 1,
confirmed 1, allocated 1**. Cancellation returned availability to 1.

The comparison places the two original captures side by side at their original
sizes. Only an external label band was added; no application status, number, or
result was changed. Screenshots do not prove exact simultaneity or production
performance. Historical automated **1-of-50** and **20-of-100** correctness outcomes
are linked separately in the gallery, including the recorded supplemental 503
failure. Those larger tests were not rerun for this screenshot assignment.

## Genuine background expiration

A browser-created workshop hold was left untouched through its real five-minute
deadline. No reservation timestamps or statuses were edited. The worker was never
stopped. Read-only SQL observed stored EXPIRED before the post-expiration UI read:

| Observation | Result |
| --- | --- |
| Actual hold deadline | 29 October 2026, 17:56:42.849727 IST |
| Worker-recorded expiration | 29 October 2026, 17:56:56.881464 IST |
| Stored reservation status | EXPIRED, with non-null expiration timestamp |
| Workshop capacity / remaining allocation | 20 / 1 |
| Public availability after expiration | 19 / 20 |
| Mixed dashboard after one new hold | HELD 1, CONFIRMED 1, CANCELLED 1, EXPIRED 1; allocated 2 |

No booking mutation on this event was issued after the deadline and before that
SQL observation. The existing independent worker recorded the transition.

## Isolated preparation and cleanup

The existing `csrs.demo` UUID-scoped prepare/status/cleanup implementation was used.
Its CLI password prompt was supplied from memory through a temporary local wrapper:
a new random password crossed private stdin and was never printed or stored in a
file, environment variable, terminal argument, image, or committed source. Browser
sessions were isolated. Synthetic event edits and booking transitions used browser
forms and real API operations. No application implementation or configuration changed.

The principal scenario used scope `41a374fc-fc93-4ea0-bd3b-e774da44d716`.
Guarded cleanup removed its three users and four owned events, including the event
created through the form, with related reservations, retry outcomes, and authenticated
sessions. The targeted final capture used scope `55fbca79-c688-47b6-b364-ed66d052d9f6`;
its three fixture events/accounts were also cleaned. Aborted preparatory attempts
ran guarded cleanup too. The existing browser fixture's cookie-scoped cleanup
removed only anonymous pre-sessions whose cookies remained in these browser contexts.

**All original records were preserved.** Read-only repeatable-read snapshots compared
PostgreSQL cluster identity and full-row SHA-256 fingerprints across all five tables.
Every original user, session, event, reservation, and idempotency row still matched.
The final targeted run also restored its entire immediate before/after snapshot.

| Table | Original count | Final count |
| --- | --- | --- |
| Users | 4 | 4 |
| Sessions | 21 | 22 |
| Events | 4 | 4 |
| Reservations | 3 | 3 |
| Idempotency records | 7 | 7 |

The sole extra row is the first aborted run's **expired anonymous pre-session**.
A read-only delta check verified that it is anonymous, unowned, and expired. Its
cookie was never saved, so it was left for normal maintenance rather than guessing
at a cleanup selector or purging preexisting sessions. No screenshot accounts,
events, reservations, or retry outcomes remain. No reset, truncation, volume
removal, broad session purge, or unauthorized cleanup occurred.

## Quality and privacy review

Every final PNG was decoded and visually reviewed through image contact sheets;
long mobile pages were additionally inspected in readable original-width strips.
Key state images, the comparison, and the corrected validation image were opened
at larger size. All final files match their manifest dimensions and hashes.

The main capture pass asserted document-width bounds before each of its 76 images. Viewports were
1440 × 1000, 768 × 1000, and 390 × 844. Long forms and dashboards retain necessary
lower controls and rows; section captures avoid unrelated whitespace. Dialogs were
captured while actually displayed. The validation image was recaptured at scroll
top to remove a floating off-screen skip-link artifact from full-page capture.

One minor existing layout issue is documented: the mobile login hero joins “your”
and “next” where a line break is hidden. Controls remain readable and no horizontal
overflow was observed. Application styling was not changed for this task.

Five byte-identical copies were removed: discovery after closure, availability
after cancellation, the logged-out guard, attendee B's initial final-seat view,
and the final seat after release. Captions explain the shared visual states;
workflow outcomes were independently asserted before deduplication. Historical
`docs/evidence/` images were inspected and linked rather than copied.

Account-address elements were masked using the existing capture pattern. Password
fields were empty in every auth image; capture code refused populated password
fields. The visible accounts/events were synthetic; preexisting public cards were
verified as the synthetic CSRS demo titles. No personal email, cookie, CSRF token,
password, key, stack trace, developer tools, or OS desktop appears in the collection.
Reservation/event UUIDs are synthetic and retained only where the real UI uses them.
No trace, video, HAR, raw log, database dump, or secret was added to documentation.

## Important states not captured

Public empty discovery could not be reached while preserving the two existing
published events. Pagination and loading are implemented, but extra filler rows
and transient screenshots were not useful. Native required validation was asserted
without adding a duplicate blank form. An eight-hour session was not waited out;
the screenshot explicitly describes actual session revocation. Closed public detail
has no hold control, and expired detail removes confirmation. No normal service
outage or deliberate authentication-throttling experiment was performed. The browser
network faults are explicitly labeled. See [all boundaries and
gaps](COVERAGE.md#important-gaps-and-boundaries).

## README and gallery structure

The root README adds only a 14-line Application Screenshots section with five
selected images and full-gallery/coverage links. It states that captures come from
the locally running Docker application and that CSRS is not publicly deployed.
Unrelated README sections remain unchanged. The complete gallery has a compact
seven-category index, embedded images, captions, responsive comparisons, technical
context, and clear limits on screenshot/concurrency claims.

## Unexpected failures and resolutions

Temporary automation had several capture/check failures; they were not application
regressions and are not reported as an entirely passing monolithic test run:

1. Discovery was initially expected to contain only two new events. It also held
   two preexisting synthetic events. Assertions were corrected to preserve and
   include those events; the aborted scope was cleaned.
2. A capacity assertion expected “allocated”; the actual UI says “allocations”.
   Matching was corrected and the real rejection was captured in a fresh scope.
3. A foreign-owner assertion expected a permission error, but the implementation
   deliberately returns privacy-preserving NOT_FOUND/404. A targeted follow-up
   captured and verified the actual response.
4. That follow-up first matched the SPA document's 200 response. The check was
   restricted to the exact `/api/v1/organizer/events/:id` endpoint; the real 404
   then passed. Its scoped cleanup and full-row preservation check succeeded.
5. The scrolled validation capture showed the fixed skip link. Recapturing at
   scroll top removed the artifact without altering UI code.
6. Initial Markdown lint found long prose and extra blank lines; formatting was
   corrected before the final checks.

Docker/localhost and Chromium access required the normal executor escalation in
this environment. No security check was disabled and no dependency was installed.

## Final verification

- PNG verification passed for all 73 files: decoding, nonblank content, dimensions,
  SHA-256 manifest match, and no unexpected embedded metadata; zero duplicate hashes.
  Dimensions span 350–2880px wide and 603–3069px high, including section crops and comparison.
- Markdown parsing verified all 73 unique gallery images, 78 image references including
  root previews, 274 local references, and 12 fragment references; zero missing targets.
- Markdown lint passed for the root README and all four new Markdown documents:
  five files, zero errors, using the existing 100-column documentation configuration.
- `git diff --check` passed. Git status matches the complete 78-file list below,
  with zero staged files. Removing the new screenshot section reproduces the original
  root README exactly; unrelated README content is verified unchanged.
- Read-only SQL reconciliation: zero counter/bounds mismatches, zero duplicate
  active pairs, and zero incomplete idempotency claims.
- Original-row fingerprints and PostgreSQL cluster identity: unchanged.
- Real browser recovery after an aborted read: successful; no remaining error notice.
- Final targeted browser: public discovery rendered; proxied liveness and readiness
  both returned HTTP 200. Docker PostgreSQL, Redis, backend, frontend were healthy;
  worker remained running. No service was interrupted for screenshots.
- No application source, model, migration, auth/security implementation, worker,
  Redis configuration, dependency lock, existing evidence, or PROJECT_HANDOFF changed.
- The full historical backend/frontend/21-journey suites were not rerun for this
  documentation-only change; the capture assertions and targeted checks are the
  fresh workflow evidence. Historical test totals are not claimed as new results.

## Git state and complete changed-file list

`main` remains at `89e27fae0c9fce5567167f6f5216b1fbb7067c58`.
**78 changed/added files: one modified README, four added Markdown documents,
and 73 added PNGs; zero staged.** Temporary helpers, review sheets, and sanitized
working observations stay under ignored `.local/screenshots/` and are not proposed
Git artifacts. No new dependencies were added.

Nothing was committed, pushed, merged, released, or deployed. Work stops here for
external review. All added images are listed below; dimensions and hashes are in
[MANIFEST.md](MANIFEST.md).

| State | Path |
| --- | --- |
| Modified | `README.md` |
| Added | `docs/screenshots/README.md` |
| Added | `docs/screenshots/COVERAGE.md` |
| Added | `docs/screenshots/MANIFEST.md` |
| Added | `docs/screenshots/REPORT.md` |
| Added | [docs/screenshots/01-public/discovery-after-publication.png](01-public/discovery-after-publication.png) |
| Added | [docs/screenshots/01-public/discovery-published-events.png](01-public/discovery-published-events.png) |
| Added | [docs/screenshots/01-public/event-detail-available.png](01-public/event-detail-available.png) |
| Added | [docs/screenshots/01-public/event-fully-booked.png](01-public/event-fully-booked.png) |
| Added | [docs/screenshots/01-public/homepage-desktop.png](01-public/homepage-desktop.png) |
| Added | [docs/screenshots/02-authentication/incorrect-credentials.png](02-authentication/incorrect-credentials.png) |
| Added | [docs/screenshots/02-authentication/login.png](02-authentication/login.png) |
| Added | [docs/screenshots/02-authentication/registration.png](02-authentication/registration.png) |
| Added | [docs/screenshots/02-authentication/session-invalidated.png](02-authentication/session-invalidated.png) |
| Added | [docs/screenshots/03-organizer/bookings-cancelled.png](03-organizer/bookings-cancelled.png) |
| Added | [docs/screenshots/03-organizer/bookings-confirmed.png](03-organizer/bookings-confirmed.png) |
| Added | [docs/screenshots/03-organizer/bookings-empty.png](03-organizer/bookings-empty.png) |
| Added | [docs/screenshots/03-organizer/bookings-expired.png](03-organizer/bookings-expired.png) |
| Added | [docs/screenshots/03-organizer/bookings-held.png](03-organizer/bookings-held.png) |
| Added | [docs/screenshots/03-organizer/bookings-multiple-statuses.png](03-organizer/bookings-multiple-statuses.png) |
| Added | [docs/screenshots/03-organizer/capacity-increased.png](03-organizer/capacity-increased.png) |
| Added | [docs/screenshots/03-organizer/close-confirmation-dialog.png](03-organizer/close-confirmation-dialog.png) |
| Added | [docs/screenshots/03-organizer/closed-event-edit-read-only.png](03-organizer/closed-event-edit-read-only.png) |
| Added | [docs/screenshots/03-organizer/closed-event-management.png](03-organizer/closed-event-management.png) |
| Added | [docs/screenshots/03-organizer/create-event-completed.png](03-organizer/create-event-completed.png) |
| Added | [docs/screenshots/03-organizer/create-event-empty.png](03-organizer/create-event-empty.png) |
| Added | [docs/screenshots/03-organizer/draft-management.png](03-organizer/draft-management.png) |
| Added | [docs/screenshots/03-organizer/edit-populated-draft.png](03-organizer/edit-populated-draft.png) |
| Added | [docs/screenshots/03-organizer/edit-published-schedule-locked.png](03-organizer/edit-published-schedule-locked.png) |
| Added | [docs/screenshots/03-organizer/publish-confirmation-dialog.png](03-organizer/publish-confirmation-dialog.png) |
| Added | [docs/screenshots/03-organizer/published-management.png](03-organizer/published-management.png) |
| Added | [docs/screenshots/03-organizer/workspace-empty.png](03-organizer/workspace-empty.png) |
| Added | [docs/screenshots/03-organizer/workspace-published-and-draft.png](03-organizer/workspace-published-and-draft.png) |
| Added | [docs/screenshots/03-organizer/workspace-published-draft-closed.png](03-organizer/workspace-published-draft-closed.png) |
| Added | [docs/screenshots/04-reservations/availability-after-expiration.png](04-reservations/availability-after-expiration.png) |
| Added | [docs/screenshots/04-reservations/before-hold.png](04-reservations/before-hold.png) |
| Added | [docs/screenshots/04-reservations/cancellation-dialog.png](04-reservations/cancellation-dialog.png) |
| Added | [docs/screenshots/04-reservations/confirmed-history-after-closure.png](04-reservations/confirmed-history-after-closure.png) |
| Added | [docs/screenshots/04-reservations/expiration-before-deadline.png](04-reservations/expiration-before-deadline.png) |
| Added | [docs/screenshots/04-reservations/held-countdown.png](04-reservations/held-countdown.png) |
| Added | [docs/screenshots/04-reservations/history-empty.png](04-reservations/history-empty.png) |
| Added | [docs/screenshots/04-reservations/history-multiple-statuses.png](04-reservations/history-multiple-statuses.png) |
| Added | [docs/screenshots/04-reservations/release-hold-dialog.png](04-reservations/release-hold-dialog.png) |
| Added | [docs/screenshots/04-reservations/reservation-cancelled.png](04-reservations/reservation-cancelled.png) |
| Added | [docs/screenshots/04-reservations/reservation-confirmed.png](04-reservations/reservation-confirmed.png) |
| Added | [docs/screenshots/04-reservations/reservation-expired.png](04-reservations/reservation-expired.png) |
| Added | [docs/screenshots/05-concurrency/final-seat-comparison.png](05-concurrency/final-seat-comparison.png) |
| Added | [docs/screenshots/05-concurrency/final-seat-organizer-dashboard.png](05-concurrency/final-seat-organizer-dashboard.png) |
| Added | [docs/screenshots/05-concurrency/final-seat-rejected.png](05-concurrency/final-seat-rejected.png) |
| Added | [docs/screenshots/05-concurrency/one-seat-available.png](05-concurrency/one-seat-available.png) |
| Added | [docs/screenshots/05-concurrency/winner-confirmed.png](05-concurrency/winner-confirmed.png) |
| Added | [docs/screenshots/05-concurrency/winner-held.png](05-concurrency/winner-held.png) |
| Added | [docs/screenshots/06-errors-and-security/availability-network-error.png](06-errors-and-security/availability-network-error.png) |
| Added | [docs/screenshots/06-errors-and-security/capacity-below-allocations.png](06-errors-and-security/capacity-below-allocations.png) |
| Added | [docs/screenshots/06-errors-and-security/closed-event-unavailable.png](06-errors-and-security/closed-event-unavailable.png) |
| Added | [docs/screenshots/06-errors-and-security/event-schedule-validation.png](06-errors-and-security/event-schedule-validation.png) |
| Added | [docs/screenshots/06-errors-and-security/lost-response-recovered.png](06-errors-and-security/lost-response-recovered.png) |
| Added | [docs/screenshots/06-errors-and-security/lost-response-retry.png](06-errors-and-security/lost-response-retry.png) |
| Added | [docs/screenshots/06-errors-and-security/organizer-owner-denied.png](06-errors-and-security/organizer-owner-denied.png) |
| Added | [docs/screenshots/06-errors-and-security/organizer-role-required.png](06-errors-and-security/organizer-role-required.png) |
| Added | [docs/screenshots/06-errors-and-security/page-not-found.png](06-errors-and-security/page-not-found.png) |
| Added | [docs/screenshots/06-errors-and-security/reservation-owner-denied.png](06-errors-and-security/reservation-owner-denied.png) |
| Added | [docs/screenshots/07-responsive/booking-dashboard-mobile.png](07-responsive/booking-dashboard-mobile.png) |
| Added | [docs/screenshots/07-responsive/booking-dashboard-tablet.png](07-responsive/booking-dashboard-tablet.png) |
| Added | [docs/screenshots/07-responsive/create-event-mobile.png](07-responsive/create-event-mobile.png) |
| Added | [docs/screenshots/07-responsive/create-event-tablet.png](07-responsive/create-event-tablet.png) |
| Added | [docs/screenshots/07-responsive/discovery-mobile.png](07-responsive/discovery-mobile.png) |
| Added | [docs/screenshots/07-responsive/discovery-tablet.png](07-responsive/discovery-tablet.png) |
| Added | [docs/screenshots/07-responsive/event-detail-mobile.png](07-responsive/event-detail-mobile.png) |
| Added | [docs/screenshots/07-responsive/event-detail-tablet.png](07-responsive/event-detail-tablet.png) |
| Added | [docs/screenshots/07-responsive/homepage-mobile.png](07-responsive/homepage-mobile.png) |
| Added | [docs/screenshots/07-responsive/homepage-tablet.png](07-responsive/homepage-tablet.png) |
| Added | [docs/screenshots/07-responsive/login-mobile.png](07-responsive/login-mobile.png) |
| Added | [docs/screenshots/07-responsive/login-tablet.png](07-responsive/login-tablet.png) |
| Added | [docs/screenshots/07-responsive/reservation-mobile.png](07-responsive/reservation-mobile.png) |
| Added | [docs/screenshots/07-responsive/reservation-tablet.png](07-responsive/reservation-tablet.png) |
| Added | [docs/screenshots/07-responsive/workspace-mobile.png](07-responsive/workspace-mobile.png) |
| Added | [docs/screenshots/07-responsive/workspace-tablet.png](07-responsive/workspace-tablet.png) |
