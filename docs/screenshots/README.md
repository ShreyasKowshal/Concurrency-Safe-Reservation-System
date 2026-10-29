# CSRS application screenshots

Captured from the locally running Docker application at `http://localhost:5173`
on **29 October 2026**, with browser times in Asia/Kolkata. CSRS is not publicly
deployed. React, FastAPI, PostgreSQL, Redis, and the independent expiration worker
are real services; no application data or response was mocked for these images.

The collection contains **72 browser captures and one labeled comparison**.
Desktop viewports are 1440 × 1000; tablet is 768 × 1000; mobile is 390 × 844.
Long forms and dashboards include their complete content. Discovery and booking
snapshots are captured directly from their rendered sections. Open an image to
inspect its original resolution.

## Gallery index

- [Public website](#public-website) — 5 images
- [Authentication](#authentication) — 4 images
- [Organizer lifecycle and bookings](#organizer-lifecycle-and-bookings) — 20 images
- [Attendee reservations and expiration](#attendee-reservations-and-expiration) — 12 images
- [Final-seat concurrency](#final-seat-concurrency) — 6 images
- [Errors and access control](#errors-and-access-control) — 10 images
- [Responsive layouts](#responsive-layouts) — 16 images

See the [coverage matrix and gaps](COVERAGE.md), [complete image manifest](MANIFEST.md),
and [capture and verification report](REPORT.md). The earlier seven captures remain
in [historical Phase 8 evidence](../evidence/README.md), linked rather than copied here.

## Public website

The event board shows genuinely published events. Two preexisting synthetic demo
events remain visible alongside the screenshot fixtures. Availability is advisory;
only a successful reservation command allocates a seat. Fully booked and zero
available are the same implemented public state, represented once.

### Homepage desktop

![Homepage desktop](01-public/homepage-desktop.png)

Landing hero and logged-out navigation.

### Discovery published events

![Discovery published events](01-public/discovery-published-events.png)

Four published synthetic events. Discovery returns to this identical four-card board after
the lifecycle event is closed; both states were captured and verified.

### Event detail available

![Event detail available](01-public/event-detail-available.png)

Published metadata and 20 of 20 available seats. After the confirmed booking is cancelled,
availability returns to this pixel-identical state; both moments were captured.

### Event fully booked

![Event fully booked](01-public/event-fully-booked.png)

Public detail shows zero available seats and the Currently full notice.

### Discovery after publication

![Discovery after publication](01-public/discovery-after-publication.png)

Publication adds the browser-created event to public discovery.

## Authentication

Forms are shown without entered credentials. Only one intentionally incorrect login
was sent in the completed capture run. The invalidated-session image follows real
revocation by the existing local promotion command; it is not a claim that an
eight-hour session naturally expired. The shared guard requires login again.
The logged-out organizer guard has the same pixels as this invalidated-session
view; both behaviors were verified and their identical PNG is stored once.

### Login

![Login](02-authentication/login.png)

Login with logged-out navigation; credentials have not been entered.

### Registration

![Registration](02-authentication/registration.png)

Public registration creates attendee accounts and documents the password requirements.

### Incorrect credentials

![Incorrect credentials](02-authentication/incorrect-credentials.png)

One rejected login request; entered credentials were cleared before capture.

### Session invalidated

![Session invalidated](02-authentication/session-invalidated.png)

A real server-side session revocation clears private content and requires login again.

## Organizer lifecycle and bookings

The organizer creates, edits, publishes, and closes a fresh synthetic event through
the browser. Capacity changes use the real server. Booking metrics distinguish
valid holds, overdue holds awaiting cleanup, confirmations, cancellations, recorded
expirations, and stored allocations. Dashboard rows contain identifiers, not customer
identities. The final mixed snapshot has capacity 20 and two active allocations:
one HELD and one CONFIRMED, alongside one CANCELLED and one EXPIRED history row.

### Workspace empty

![Workspace empty](03-organizer/workspace-empty.png)

The newly promoted synthetic organizer sees an empty workspace because they own no events.

### Workspace published and draft

![Workspace published and draft](03-organizer/workspace-published-and-draft.png)

Owner-only workspace containing two published events and one draft.

### Create event empty

![Create event empty](03-organizer/create-event-empty.png)

The complete empty organizer event form.

### Create event completed

![Create event completed](03-organizer/create-event-completed.png)

The form contains a synthetic title, location, description, future schedule, and capacity.

### Draft management

![Draft management](03-organizer/draft-management.png)

A newly created draft remains private and has no bookings.

### Edit populated draft

![Edit populated draft](03-organizer/edit-populated-draft.png)

The saved draft is loaded into the edit form, including editable schedule fields.

### Capacity increased

![Capacity increased](03-organizer/capacity-increased.png)

Capacity increases from 5 to 6 after an accepted server command; updated metadata is visible.

### Publish confirmation dialog

![Publish confirmation dialog](03-organizer/publish-confirmation-dialog.png)

The native application dialog explains public visibility and schedule locking.

### Published management

![Published management](03-organizer/published-management.png)

The former draft is now published, with capacity 6 and an empty booking dashboard.

### Edit published schedule locked

![Edit published schedule locked](03-organizer/edit-published-schedule-locked.png)

Published metadata can be edited while start time and booking deadline are read-only.

### Bookings empty

![Bookings empty](03-organizer/bookings-empty.png)

The workshop starts at capacity 20 with zero holds, confirmations, cancellations, and expirations.

### Bookings held

![Bookings held](03-organizer/bookings-held.png)

The dashboard shows one valid HELD reservation and one stored allocation.

### Bookings confirmed

![Bookings confirmed](03-organizer/bookings-confirmed.png)

Confirmation preserves one allocation and moves the reservation into Confirmed.

### Bookings cancelled

![Bookings cancelled](03-organizer/bookings-cancelled.png)

The cancelled reservation remains in history; stored allocation returns to zero.

### Bookings expired

![Bookings expired](03-organizer/bookings-expired.png)

After worker cleanup, the dashboard shows one recorded expiration, one retained confirmed seat,
and stored allocation 1.

### Bookings multiple statuses

![Bookings multiple statuses](03-organizer/bookings-multiple-statuses.png)

Capacity 20: HELD 1, CONFIRMED 1, CANCELLED 1, EXPIRED 1, Stored allocations 2.

### Close confirmation dialog

![Close confirmation dialog](03-organizer/close-confirmation-dialog.png)

The closure dialog states that new holds stop and existing reservations are preserved.

### Closed event management

![Closed event management](03-organizer/closed-event-management.png)

Closed management is read-only; its existing confirmed booking remains allocated.

### Closed event edit read only

![Closed event edit read only](03-organizer/closed-event-edit-read-only.png)

Opening a closed event's edit link directly shows the read-only state.

### Workspace published draft closed

![Workspace published draft closed](03-organizer/workspace-published-draft-closed.png)

The private workspace retains PUBLISHED, DRAFT, and CLOSED lifecycle cards.

## Attendee reservations and expiration

Holds, confirmation, cancellation, release dialogs, and private history use the real
browser controls. Cancelling a confirmed booking releases its seat and preserves
timestamps. Closing an event preserves existing reservations even when public
metadata disappears.

For expiration, a new hold was left untouched for its actual five-minute deadline.
Read-only SQL observed the stored EXPIRED status and non-null expiration timestamp
before the post-expiration UI capture. The independent background worker released
the hold; no database timestamps or reservation statuses were edited. The organizer
then showed one recorded expiration and one remaining confirmed allocation, and
availability returned to 19 of 20.

### History empty

![History empty](04-reservations/history-empty.png)

A new attendee has no reservations; signed-in navigation is visible.

### Before hold

![Before hold](04-reservations/before-hold.png)

A signed-in attendee sees available seats and the Hold one seat action.

### Held countdown

![Held countdown](04-reservations/held-countdown.png)

A HELD reservation shows its identifier, deadline, countdown, Confirm, and Release actions.

### Reservation confirmed

![Reservation confirmed](04-reservations/reservation-confirmed.png)

The server-confirmed reservation includes its confirmation timestamp and cancellation action.

### Cancellation dialog

![Cancellation dialog](04-reservations/cancellation-dialog.png)

The cancellation dialog explains that the seat will be released.

### Reservation cancelled

![Reservation cancelled](04-reservations/reservation-cancelled.png)

CANCELLED history includes both the earlier confirmation and actual cancellation timestamps.

### Expiration before deadline

![Expiration before deadline](04-reservations/expiration-before-deadline.png)

A second five-minute hold is left unconfirmed so the worker can expire it naturally.

### Reservation expired

![Reservation expired](04-reservations/reservation-expired.png)

After the actual five-minute deadline, SQL confirms worker-recorded EXPIRED before this UI read; the
expiration timestamp is visible.

### Availability after expiration

![Availability after expiration](04-reservations/availability-after-expiration.png)

The worker-expired hold releases capacity: 19 seats are available while one confirmed booking
remains.

### Release hold dialog

![Release hold dialog](04-reservations/release-hold-dialog.png)

A HELD reservation has its own voluntary release confirmation dialog.

### History multiple statuses

![History multiple statuses](04-reservations/history-multiple-statuses.png)

Private history includes active HELD, CONFIRMED, CANCELLED, and EXPIRED entries with detail links.

### Confirmed history after closure

![Confirmed history after closure](04-reservations/confirmed-history-after-closure.png)

Private confirmed history survives closure and uses the event-ID fallback when public metadata is
unavailable.

## Final-seat concurrency

Two isolated attendee contexts first read one available seat. The existing E2E
request-barrier pattern then released their real hold requests: one returned
**201**, and the other **409 EVENT_FULL**. The winner confirmed; the owner dashboard
and a read-only SQL observation both showed capacity 1 and allocation 1. After the
winner cancelled, the other attendee saw the seat available again.

PostgreSQL event-row locking (`SELECT FOR UPDATE`) serializes admission. Atomic
transactions commit the reservation, allocation counter, and durable retry outcome
together. The comparison joins two authentic screenshots, adding labels outside
the application without changing its results.

This is a browser-level demonstration, not proof of precise simultaneity or
production traffic performance. Separate, historical two-process automated tests
record **1 accepted / 49 EVENT_FULL out of 50** and **20 accepted / 80 EVENT_FULL
out of 100**, with SQL reconciliation. See [Phase 8 concurrency
evidence](../validations/phase-8-validation.md#9-concurrency-idempotency-and-recovery)
and its [follow-up and recorded supplemental
failure](../validations/phase-8-validation.md#17-final-follow-up-evidence).
Those larger workloads were not rerun for this documentation task.

### One seat available

![One seat available](05-concurrency/one-seat-available.png)

Both isolated attendees initially read one available seat; after the winner cancels, availability
returns to this identical state. The three pixel-identical captures are stored once.

### Winner held

![Winner held](05-concurrency/winner-held.png)

One attendee's request returns 201 and creates the final-seat HELD reservation.

### Final seat rejected

![Final seat rejected](05-concurrency/final-seat-rejected.png)

The other attendee's request returns 409 EVENT_FULL; refreshed availability is zero.

### Final seat comparison

![Final seat comparison](05-concurrency/final-seat-comparison.png)

Two genuine captures, joined at original size. Labels outside the application identify the
successful hold and rejected attendee; no UI values were changed.

### Winner confirmed

![Winner confirmed](05-concurrency/winner-confirmed.png)

The winner confirms the same reservation; the original hold deadline no longer governs it.

### Final seat organizer dashboard

![Final seat organizer dashboard](05-concurrency/final-seat-organizer-dashboard.png)

Capacity 1, Confirmed 1, Stored allocations 1: the actual owner booking snapshot.

## Errors and access control

Role guards, foreign-resource denials, unavailable public detail, schedule validation,
and rejected capacity reduction are actual implemented responses. No authentication,
CSRF, rate limit, or ownership check was bypassed.

Two images explicitly demonstrate browser transport faults. For lost-response
recovery, the backend committed a real 201 hold before browser delivery was dropped;
the retry reused the same idempotency key and recovered that reservation. Separately,
one availability read was aborted only in the screenshot browser. The UI rendered
its genuine network error and recovered on retry. No normal service was stopped and
no synthetic HTTP success/error body was supplied.

### Availability network error

![Availability network error](06-errors-and-security/availability-network-error.png)

An availability read aborted only in this browser triggers the network-error notice and retry action.

### Capacity below allocations

![Capacity below allocations](06-errors-and-security/capacity-below-allocations.png)

The server refuses capacity 1 while two seats are allocated; capacity remains 20.

### Closed event unavailable

![Closed event unavailable](06-errors-and-security/closed-event-unavailable.png)

Closed events are unavailable through public detail; no closed event is republished for discovery.

### Event schedule validation

![Event schedule validation](06-errors-and-security/event-schedule-validation.png)

The form rejects an end time before the start and displays a validation message.

### Lost response recovered

![Lost response recovered](06-errors-and-security/lost-response-recovered.png)

Retry with the original key recovers the committed hold; the same reservation then confirms
successfully.

### Lost response retry

![Lost response retry](06-errors-and-security/lost-response-retry.png)

Browser transport deliberately drops delivery after a real 201 commit; the UI offers safe
same-operation recovery.

### Organizer owner denied

![Organizer owner denied](06-errors-and-security/organizer-owner-denied.png)

A second authenticated organizer receives a privacy-preserving 404 for another organizer's event and
its booking snapshot; no owner data is exposed.

### Organizer role required

![Organizer role required](06-errors-and-security/organizer-role-required.png)

An authenticated attendee cannot enter the organizer workspace.

### Page not found

![Page not found](06-errors-and-security/page-not-found.png)

The React fallback route offers a return to discovery.

### Reservation owner denied

![Reservation owner denied](06-errors-and-security/reservation-owner-denied.png)

The backend denies another attendee access to this private reservation.

## Responsive layouts

The same unchanged application renders eight representative page types at both
768px and 390px widths. Each capture passed a document-width overflow assertion.
Full-height forms and dashboards retain lower controls, metrics, and reservation
rows; this is Chromium viewport coverage, not physical-device certification.
The mobile login hero currently joins “your” and “next” where its line break is
hidden. That existing typography issue is preserved here; application styling
was outside this documentation-only assignment.

| Page | Tablet · 768px | Mobile · 390px |
| --- | --- | --- |
| Landing hero | ![Landing hero at 768px](07-responsive/homepage-tablet.png) | ![Landing hero at 390px](07-responsive/homepage-mobile.png) |
| Published discovery | ![Published discovery at 768px](07-responsive/discovery-tablet.png) | ![Published discovery at 390px](07-responsive/discovery-mobile.png) |
| Event detail | ![Event detail at 768px](07-responsive/event-detail-tablet.png) | ![Event detail at 390px](07-responsive/event-detail-mobile.png) |
| Login | ![Login at 768px](07-responsive/login-tablet.png) | ![Login at 390px](07-responsive/login-mobile.png) |
| Organizer workspace | ![Organizer workspace at 768px](07-responsive/workspace-tablet.png) | ![Organizer workspace at 390px](07-responsive/workspace-mobile.png) |
| Create-event form | ![Create-event form at 768px](07-responsive/create-event-tablet.png) | ![Create-event form at 390px](07-responsive/create-event-mobile.png) |
| Confirmed reservation | ![Confirmed reservation at 768px](07-responsive/reservation-tablet.png) | ![Confirmed reservation at 390px](07-responsive/reservation-mobile.png) |
| Mixed booking dashboard | ![Mixed booking dashboard at 768px](07-responsive/booking-dashboard-tablet.png) | ![Mixed booking dashboard at 390px](07-responsive/booking-dashboard-mobile.png) |
