# Screenshot coverage matrix

Derived from the implemented React routes, page components, session guards, API
client, real route behavior, and existing Chromium journeys at handoff commit
`89e27fae0c9fce5567167f6f5216b1fbb7067c58`. See the [gallery](README.md),
[image manifest](MANIFEST.md), and [verification report](REPORT.md).

## Captured application coverage

| Route / feature | Captured implemented states | Evidence category |
| --- | --- | --- |
| `/` | Hero, logged-out navigation, multiple published cards, newly published event appearing, closed event disappearing | Public website |
| `/events/:id` | Metadata, location, schedule, capacity, advisory availability, login-to-hold link, signed-in hold button, full/zero seats, capacity after cancellation and expiration | Public / reservations / concurrency |
| `/login`, `/register` | Empty forms, password guidance, one incorrect login response with credentials cleared | Authentication |
| `/organizer` | Owner-only published/draft cards; published/draft/closed workspace; empty workspace for a newly promoted synthetic organizer | Organizer |
| `/organizer/events/new` | Empty and completed forms; invalid end-before-start schedule; newly created draft | Organizer / validation |
| `/organizer/events/:id/edit` | Populated draft, supported location change, disabled published start/deadline, closed read-only deep link | Organizer |
| `/organizer/events/:id` | Draft; capacity 5 to 6; publish and close dialogs; published and closed controls; preserved confirmed booking after closure | Organizer |
| Owner booking snapshot | Empty, HELD, CONFIRMED, CANCELLED, recorded EXPIRED, and four-status dashboard; correct active allocations and capacity | Organizer |
| `/reservations` | Empty private history and mixed HELD/CONFIRMED/CANCELLED/EXPIRED history; working detail links | Reservations |
| `/reservations/:id` | HELD identifier/countdown/deadline; Confirm and Release actions; CONFIRMED timestamp; cancellation/release dialogs; CANCELLED timestamps; EXPIRED with recorded timestamp; confirmed event-ID fallback after closure | Reservations |
| Natural expiration | Five-minute hold left untouched; stored worker EXPIRED observed through read-only SQL before UI; capacity released | Reservations / organizer |
| Final seat | Two isolated attendees initially read 1; barrier-released real 201/409 responses; winner HELD and CONFIRMED; full public event; owner capacity 1/confirmed 1/allocated 1; seat available after cancellation | Concurrency |
| Access and errors | Logged-out guard, attendee role guard, foreign-organizer denial, foreign-reservation denial, public closed-event unavailability, page fallback, rejected capacity below allocations | Errors and security |
| Session invalidation | Existing local promotion revokes only the synthetic rival's session; private content clears and login is required | Authentication |
| Lost response | Browser drops delivery of a real successful hold; same key recovers one reservation, then confirmation succeeds | Errors and security |
| Network read failure | Availability request aborted only in the screenshot browser; actual error notice and successful retry | Errors and security |
| Responsive | Hero, discovery, event detail, login, workspace, create form, confirmed detail, mixed booking dashboard at 768 and 390 widths; 1440 desktop throughout | Responsive |

## Important gaps and boundaries

| Proposed state | Actual behavior / reason not separately captured |
| --- | --- |
| Empty public discovery | Two existing published synthetic demo events were already present. They were preserved; no fixture filtering, fake response, or global unpublication was used. |
| Next-page navigation | Cursor pagination is implemented at 20 items/page. Only four or five public events, four owned events, and fewer than 20 history rows were needed. Bulk filler records would add little portfolio value. |
| Standalone loading screenshots | Loading indicators are implemented but transient. Captures wait for completed content to keep the gallery useful and avoid incomplete evidence. |
| Native required-field validation bubble | Empty registration submit was checked: email `valueMissing` was true and Chromium returned “Please fill out this field.” Native validation was not added as an almost-identical blank-form image. A persistent application schedule-validation error is captured. |
| Natural eight-hour authentication expiry | Not waited out. The real revocation path demonstrates the shared authentication-required UI. No image is labeled as a naturally expired session or a separate unsupported expiry banner. |
| Booking-deadline-passed event | A dedicated deadline scenario was not added. Closed-event public unavailability and true full-capacity rejection cover distinct safely reached unavailable states. |
| Reserve a closed event from public detail | Closed detail is hidden by the backend, so the actual UI provides no reachable hold control there. The unavailable public response and read-only owner view are captured. |
| Late confirmation control after expiration | The expired detail removes Confirm. No removed button was reintroduced; the natural expired state and worker timestamp are shown. |
| Real Redis/PostgreSQL outage or raw 503 screen | Normal services were kept running. The gallery labels its browser-only network faults explicitly; historical isolated outage tests remain in the existing Phase 8 evidence. |
| Repeated failed auth / throttle | No deliberate throttling experiment. Each completed capture run used one wrong login and bounded successful logins under the real limits. |
| Registration success / extra new attendee | Registration form and native required checks are covered; the guarded demo helper already supplied the three required synthetic accounts. No unscoped extra account was registered. |
| Firefox, Safari, physical devices, full accessibility certification | This assignment covers existing Playwright Chromium at three viewport widths; no broader certification is claimed. |
| Waitlists, payments, seat map, search/filter, password recovery | These are not implemented and are not invented in the gallery. |

The browser final-seat demo is separate from the historical automated 1-of-50 and
20-of-100 correctness results. See the [gallery explanation](README.md#final-seat-concurrency).
