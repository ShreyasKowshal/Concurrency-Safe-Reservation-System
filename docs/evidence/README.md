# Phase 8 portfolio evidence

Date: 2026-10-28, Asia/Calcutta. Baseline `main` at
`6bf24b0203bf0c752c2edf5e668152c3945f07c2`. Captures were produced before publication.
This is localhost evidence, not a deployed release or production benchmark.

## Browser captures

The PNGs are captured by the real Chromium journeys in
[journeys.spec.ts](../../frontend/e2e/journeys.spec.ts). They use UUID-scoped synthetic
PostgreSQL fixtures and the actual FastAPI/Redis/worker stack. Account-address elements are
masked at capture time; no cookies, tokens, passwords or customer identities are included.
The fixture accounts/events are removed after the run; image IDs are not permanent demo URLs.

| Capture | What it shows |
| --- | --- |
| [discovery.png](discovery.png) | Public event discovery populated from the backend |
| [event-detail.png](event-detail.png) | Published event detail and advisory availability |
| [held-countdown.png](held-countdown.png) | Actual HELD reservation after reload, with countdown |
| [confirmed-reservation.png](confirmed-reservation.png) | Current CONFIRMED state after a successful command/refetch |
| [reservation-history.png](reservation-history.png) | Private history containing the confirmed reservation |
| [event-creation.png](event-creation.png) | Organizer draft-creation form |
| [organizer-dashboard.png](organizer-dashboard.png) | Owned event, lifecycle controls and booking categories |

Reproduce on a quiet migrated stack with Node.js 24 and Playwright Chromium installed:

```powershell
./scripts/local.ps1 start
$env:CSRS_CAPTURE_EVIDENCE = '1'
try { npm.cmd --prefix frontend run test:e2e }
finally { Remove-Item Env:CSRS_CAPTURE_EVIDENCE -ErrorAction SilentlyContinue }
```

Without the explicit flag, tests do not overwrite portfolio PNGs. Failure traces/screenshots
remain in ignored test-results and are uploaded by CI only on failure. No recordings/traces
are included here. Inspect new captures before publication: real public event metadata may
appear on discovery if you have added it locally. For manual captures, use only the scoped
demo data, crop/mask the account-address UI, avoid developer tools and never capture login
forms with entered credentials.

## Correctness and operational evidence

[phase-8-results.txt](phase-8-results.txt) records sanitized observed outcomes and reproduction
commands. [Phase 8 validation](../validations/phase-8-validation.md) provides the complete
test/audit table,
limitations, changed-file manifest and acceptance checklist. Keep the output's workload scope:
two API processes and a fixed 50/100-attempt correctness test do not measure production scale.

```powershell
docker compose --profile test run --rm backend-test python -m pytest tests/integration/test_reservation_transactions.py -k 'final_seats_across_two_api_processes or concurrent_duplicates_across_api_processes' -q -s -p no:cacheprovider
./scripts/verify-local.ps1
Get-Content backend/scripts/reconcile.sql | docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'
```

The verifier generates its own project/volume, verifies absent host ports and retains its
volume after ordinary shutdown. It never stops the normal application's dependencies.
Exact SQL invariants include persisted overdue HELD until a cleanup transaction commits.

## Hosted CI provenance

The [Phase 7 exact-commit Actions run](https://github.com/ShreyasKowshal/Concurrency-Safe-Reservation-System/actions/runs/40505497985)
is the historical green run recorded in the approved handoff for
`10be01a591567b2198b4dd38db8e96047ff872e4`. It is not a Phase 8 result, and its current remote
state was not re-fetched during capture. See [the handoff](../PROJECT_HANDOFF.md) for later
publication and exact-commit CI verification. No Actions screenshot or green run is fabricated.
