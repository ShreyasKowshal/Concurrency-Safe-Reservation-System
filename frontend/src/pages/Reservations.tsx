import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, isAbort } from "../api/client";
import type { Reservation } from "../api/models";
import { Countdown, remainingSeconds } from "../components/Countdown";
import {
  Breadcrumb,
  ConfirmDialog,
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
  Pager,
  Status,
  Time,
} from "../components/ui";
import { useActive, useResource } from "../hooks";

export function ReservationRow({
  reservation,
  privateAction = true,
}: {
  reservation: Reservation;
  privateAction?: boolean;
}) {
  return (
    <article className="reservation-row">
      <div className="reservation-icon" aria-hidden="true">
        ↗
      </div>
      <div>
        <p className="eyebrow">
          One seat · <Time value={reservation.created_at} />
        </p>
        <h2>
          {privateAction ? (
            <Link to={`/reservations/${reservation.id}`}>
              Reservation {reservation.id.slice(0, 8)}
            </Link>
          ) : (
            `Reservation ${reservation.id.slice(0, 8)}`
          )}
        </h2>
        <p className="muted break-word">Event ID: {reservation.event_id}</p>
        {reservation.status === "HELD" && (
          <p>
            Hold expires <Time value={reservation.hold_expires_at} />
          </p>
        )}
      </div>
      <div className="row-end">
        <Status value={reservation.status} />
        {privateAction && (
          <Link to={`/reservations/${reservation.id}`}>View reservation →</Link>
        )}
      </div>
    </article>
  );
}
export function Reservations() {
  const [cursor, setCursor] = useState("");
  const resource = useResource(`history:${cursor}`, (signal) =>
    api.history(cursor, signal),
  );
  return (
    <>
      <PageHeading
        eyebrow="Your experiences"
        title="My reservations."
        action={
          <button
            className="secondary"
            disabled={resource.loading}
            onClick={() => {
              if (cursor) setCursor("");
              else void resource.refresh();
            }}
          >
            Refresh history
          </button>
        }
      >
        Your holds, confirmed plans, and past reservations. Statuses come from
        the server.
      </PageHeading>
      <ErrorNotice
        error={resource.error}
        retry={() => void resource.refresh()}
      />
      {resource.loading && <Loading label="Loading your reservations…" />}
      {resource.data && (
        <>
          {resource.data.items.length ? (
            <div className="reservation-list">
              {resource.data.items.map((reservation) => (
                <ReservationRow
                  key={reservation.id}
                  reservation={reservation}
                />
              ))}
            </div>
          ) : (
            <Empty title="Your next experience is waiting.">
              <Link to="/">Explore events</Link> and hold your first seat.
            </Empty>
          )}
          <Pager
            next={resource.data.next_cursor}
            cursor={cursor}
            setCursor={setCursor}
          />
        </>
      )}
    </>
  );
}
export function ReservationDetails() {
  const active = useActive();
  const { id = "" } = useParams();
  const resource = useResource(`reservation:${id}`, (signal) =>
    api.reservation(id, signal),
  );
  const row = resource.data;
  const related = useResource(
    `related:${row?.event_id ?? "pending"}`,
    async (signal) => {
      if (!row) return null;
      try {
        return await api.event(row.event_id, signal);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
  );
  const [action, setAction] = useState<"confirm" | "cancel" | null>(null);
  const [error, setError] = useState<unknown>();
  const [message, setMessage] = useState("");
  const [dialog, setDialog] = useState(false);
  const [elapsed, setElapsed] = useState(false);
  const lock = useRef(false);
  const reference = useRef({ data: resource.data, at: performance.now() });
  if (reference.current.data !== resource.data)
    reference.current = { data: resource.data, at: performance.now() };
  useEffect(() => {
    setElapsed(false);
  }, [row]);
  const execute = async (next: "confirm" | "cancel") => {
    if (lock.current) return;
    lock.current = true;
    setAction(next);
    setError(undefined);
    setMessage("");
    try {
      const current = await api.command(next, id);
      if (!active.current) return;
      setMessage(
        current.status === "CONFIRMED"
          ? "You're in! Your reservation is confirmed by the server."
          : current.status === "EXPIRED"
            ? "The server reports that this hold has expired."
            : "Reservation cancelled. Your seat has been released.",
      );
    } catch (failure) {
      if (active.current && !isAbort(failure)) setError(failure);
    } finally {
      if (active.current) {
        setDialog(false);
        await resource.refresh();
      }
      lock.current = false;
      if (active.current) setAction(null);
    }
  };
  const expiresNow = row
    ? remainingSeconds(
        row.hold_expires_at,
        row.server_time,
        performance.now() - reference.current.at,
      ) === 0
    : true;
  const cancelEligible =
    row &&
    (row.status === "HELD" ||
      (row.status === "CONFIRMED" &&
        (!related.data ||
          Date.parse(related.data.starts_at) > Date.parse(row.server_time))));
  return (
    <>
      <Breadcrumb to="/reservations">My reservations</Breadcrumb>
      <PageHeading
        eyebrow="Your place, in detail"
        title={
          row?.status === "CONFIRMED" ? "See you there." : "Your reservation."
        }
      >
        Reservation ID: <span className="break-word">{id}</span>
      </PageHeading>
      <ErrorNotice
        error={resource.error}
        retry={() => void resource.refresh()}
      />
      {resource.loading && <Loading label="Checking reservation state…" />}
      {row && (
        <div className="detail-layout">
          <article className="panel">
            <div className="actions">
              <span role="status">
                <Status value={row.status} />
              </span>
              <button
                className="secondary"
                disabled={resource.loading || !!action}
                onClick={() => void resource.refresh()}
              >
                Refresh status
              </button>
            </div>
            <h2>{related.data?.title ?? "Your event"}</h2>
            {related.data ? (
              <p>
                {related.data.location} ·{" "}
                <Time value={related.data.starts_at} />
              </p>
            ) : (
              <p className="muted">
                Public event details may be unavailable after closure. Your
                reservation history remains accessible.
              </p>
            )}
            <p className="break-word">Event ID: {row.event_id}</p>
            <ErrorNotice
              error={related.error}
              retry={() => void related.refresh()}
            />
            <dl className="metadata">
              <div>
                <dt>Created</dt>
                <dd>
                  <Time value={row.created_at} />
                </dd>
              </div>
              <div>
                <dt>Hold deadline</dt>
                <dd>
                  <Time value={row.hold_expires_at} />
                </dd>
              </div>
              {row.confirmed_at && (
                <div>
                  <dt>Confirmed</dt>
                  <dd>
                    <Time value={row.confirmed_at} />
                  </dd>
                </div>
              )}
              {row.cancelled_at && (
                <div>
                  <dt>Cancelled</dt>
                  <dd>
                    <Time value={row.cancelled_at} />
                  </dd>
                </div>
              )}
              {row.expired_at && (
                <div>
                  <dt>Expiration recorded</dt>
                  <dd>
                    <Time value={row.expired_at} />
                  </dd>
                </div>
              )}
              <div>
                <dt>Server checked at</dt>
                <dd>
                  <Time value={row.server_time} />
                </dd>
              </div>
            </dl>
            {row.status === "EXPIRED" && (
              <p className="notice warning">
                This hold has expired. The worker may record cleanup later; this
                does not extend your hold.
              </p>
            )}
            {row.status === "CONFIRMED" && (
              <p className="notice success">
                One seat confirmed. The original hold deadline no longer affects
                this booking.
              </p>
            )}
            {row.status === "CANCELLED" && (
              <p className="notice">
                This reservation was cancelled. Rebooking creates a new
                reservation.
              </p>
            )}
          </article>
          <aside className="panel booking-panel">
            {row.status === "HELD" && (
              <Countdown
                reservation={row}
                onElapsed={() => {
                  setElapsed(true);
                  void resource.refresh();
                }}
              />
            )}
            <div role="status">
              {message && <p className="notice success">{message}</p>}
            </div>
            <ErrorNotice error={error} />
            {row.status === "HELD" && (
              <button
                className="full"
                disabled={
                  !!action ||
                  resource.loading ||
                  ((elapsed || expiresNow) && !api.hasIntent("confirm", id))
                }
                onClick={() => void execute("confirm")}
              >
                {action === "confirm"
                  ? "Confirming…"
                  : api.hasIntent("confirm", id)
                    ? "Retry same confirmation"
                    : "Confirm reservation"}
              </button>
            )}
            {cancelEligible && (
              <button
                className="danger-outline full"
                disabled={!!action || resource.loading}
                onClick={() => setDialog(true)}
              >
                {row.status === "HELD" ? "Release hold" : "Cancel reservation"}
              </button>
            )}
            {(row.status === "CANCELLED" || row.status === "EXPIRED") && (
              <Link className="button full" to="/">
                Find another experience
              </Link>
            )}
            <Link className="text-link" to="/reservations">
              Back to all reservations
            </Link>
            <small>
              Actions are checked by the server. If a response is lost, repeat
              the same action to safely recover its outcome.
            </small>
          </aside>
        </div>
      )}
      {dialog && (
        <ConfirmDialog
          title={
            row?.status === "HELD"
              ? "Release your hold?"
              : "Cancel this reservation?"
          }
          confirmLabel={
            row?.status === "HELD" ? "Release hold" : "Cancel reservation"
          }
          busy={!!action}
          onClose={() => setDialog(false)}
          onConfirm={() => void execute("cancel")}
        >
          Your seat will become available to someone else. This reservation
          cannot be reactivated.
        </ConfirmDialog>
      )}
    </>
  );
}
