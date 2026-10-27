import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, isAbort } from "../api/client";
import type { EventInput, OwnerEvent } from "../api/models";
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
import { EventCard } from "./Events";
import { ReservationRow } from "./Reservations";

export function Organizer() {
  const [cursor, setCursor] = useState("");
  const resource = useResource(`owned:${cursor}`, (signal) =>
    api.owned(cursor, signal),
  );
  return (
    <>
      <PageHeading
        eyebrow="Organizer workspace"
        title="Bring people together."
        action={
          <Link className="button" to="/organizer/events/new">
            Create an event ＋
          </Link>
        }
      >
        Manage your events from the first draft to the final seat.
      </PageHeading>
      <div className="toolbar">
        <p className="muted">Only events owned by your account appear here.</p>
        <button
          className="secondary"
          disabled={resource.loading}
          onClick={() => {
            if (cursor) setCursor("");
            else void resource.refresh();
          }}
        >
          Refresh events
        </button>
      </div>
      <ErrorNotice
        error={resource.error}
        retry={() => void resource.refresh()}
      />
      {resource.loading && <Loading label="Loading owned events…" />}
      {resource.data && (
        <>
          {resource.data.items.length ? (
            <div className="event-grid">
              {resource.data.items.map((event) => (
                <EventCard key={event.id} event={event} organizer />
              ))}
            </div>
          ) : (
            <Empty title="Every great event starts here.">
              Create a draft, add the details, then publish when you're ready.
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
function localDate(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}
export function EventForm({ event }: { event?: OwnerEvent }) {
  const active = useActive();
  const navigate = useNavigate();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const lock = useRef(false);
  const published = event?.status === "PUBLISHED";
  const fields = error instanceof ApiError ? error.fields : {};
  const described = (name: string) =>
    fields[name] ? `${name}-error` : undefined;
  const fieldError = (name: string) =>
    fields[name] && (
      <small className="field-error" id={`${name}-error`}>
        {fields[name]}
      </small>
    );
  const submit = async (formEvent: FormEvent<HTMLFormElement>) => {
    formEvent.preventDefault();
    if (lock.current || uncertain) return;
    const form = formEvent.currentTarget;
    if (!form.reportValidity()) return;
    const data = new FormData(form);
    const metadata = {
      title: String(data.get("title")).trim(),
      description: String(data.get("description")),
      location: String(data.get("location")).trim(),
      ends_at: new Date(String(data.get("ends_at"))).toISOString(),
    };
    const schedule = published
      ? {}
      : {
          starts_at: new Date(String(data.get("starts_at"))).toISOString(),
          booking_closes_at: new Date(
            String(data.get("booking_closes_at")),
          ).toISOString(),
        };
    const start = schedule.starts_at ?? event!.starts_at;
    const close = schedule.booking_closes_at ?? event!.booking_closes_at;
    if (
      Date.parse(close) > Date.parse(start) ||
      Date.parse(start) >= Date.parse(metadata.ends_at)
    ) {
      setError(
        new ApiError(
          422,
          "INVALID_EVENT_SCHEDULE",
          "Booking must close at or before the start, and the event must end after it starts.",
          0,
          false,
          { ends_at: "Check start, end, and booking deadline." },
        ),
      );
      return;
    }
    lock.current = true;
    setBusy(true);
    setError(undefined);
    try {
      const result = event
        ? await api.editEvent(event.id, { ...metadata, ...schedule })
        : await api.createEvent({
            ...metadata,
            ...schedule,
            capacity: Number(data.get("capacity")),
          } as EventInput);
      if (active.current)
        navigate(`/organizer/events/${result.id}`, { replace: true });
    } catch (failure) {
      if (active.current && !isAbort(failure)) {
        setError(failure);
        if (failure instanceof ApiError && failure.uncertain)
          setUncertain(true);
      }
    } finally {
      lock.current = false;
      if (active.current) setBusy(false);
    }
  };
  return (
    <form className="panel event-form" onSubmit={submit}>
      <p className="notice">
        Times use your device's local timezone and are sent as UTC.{" "}
        {published && "Published start and booking deadline are read-only."}
      </p>
      <label htmlFor="title">Event title</label>
      <input
        id="title"
        name="title"
        defaultValue={event?.title}
        required
        maxLength={200}
        pattern={".*\\S.*"}
        aria-invalid={!!fields.title}
        aria-describedby={described("title")}
      />
      {fieldError("title")}
      <label htmlFor="location">Location</label>
      <input
        id="location"
        name="location"
        defaultValue={event?.location}
        required
        maxLength={300}
        pattern={".*\\S.*"}
        aria-invalid={!!fields.location}
        aria-describedby={described("location")}
      />
      {fieldError("location")}
      <label htmlFor="description">Description</label>
      <textarea
        id="description"
        name="description"
        defaultValue={event?.description}
        maxLength={10000}
        rows={6}
        aria-invalid={!!fields.description}
        aria-describedby={described("description")}
      />
      {fieldError("description")}
      <div className="form-grid">
        {(
          [
            ["starts_at", "Starts"],
            ["ends_at", "Ends"],
            ["booking_closes_at", "Booking closes"],
          ] as const
        ).map(([name, label]) => (
          <div key={name}>
            <label htmlFor={name}>{label}</label>
            <input
              id={name}
              name={name}
              type="datetime-local"
              defaultValue={localDate(event?.[name])}
              required
              disabled={published && name !== "ends_at"}
              aria-invalid={!!fields[name]}
              aria-describedby={described(name)}
            />
            {fieldError(name)}
          </div>
        ))}
        {!event && (
          <div>
            <label htmlFor="capacity">Seat capacity</label>
            <input
              id="capacity"
              name="capacity"
              type="number"
              min={1}
              max={2147483647}
              step={1}
              required
              aria-invalid={!!fields.capacity}
              aria-describedby={described("capacity")}
            />
            {fieldError("capacity")}
          </div>
        )}
      </div>
      <ErrorNotice error={error} />
      {uncertain && (
        <p className="notice warning">
          This change may have saved.{" "}
          <Link to={event ? `/organizer/events/${event.id}` : "/organizer"}>
            Check your current events before submitting again.
          </Link>
        </p>
      )}
      <div className="actions">
        <button disabled={busy || uncertain}>
          {busy ? "Saving…" : event ? "Save changes" : "Create draft"}
        </button>
        <Link
          className="button secondary"
          to={event ? `/organizer/events/${event.id}` : "/organizer"}
        >
          Back to workspace
        </Link>
      </div>
    </form>
  );
}
export function CreateEvent() {
  return (
    <>
      <Breadcrumb to="/organizer">Organizer workspace</Breadcrumb>
      <PageHeading eyebrow="Make it happen" title="Create an event.">
        Start with a draft. Review every detail before publishing.
      </PageHeading>
      <EventForm />
    </>
  );
}
export function EditEvent() {
  const { id = "" } = useParams();
  const resource = useResource(`edit:${id}`, (signal) =>
    api.ownerEvent(id, signal),
  );
  return (
    <>
      <Breadcrumb to={`/organizer/events/${id}`}>Event overview</Breadcrumb>
      <PageHeading eyebrow="The details matter" title="Edit your event." />
      <ErrorNotice
        error={resource.error}
        retry={() => void resource.refresh()}
      />
      {resource.loading && <Loading />}
      {resource.data &&
        (resource.data.status === "CLOSED" ? (
          <Empty title="This event is closed.">
            Closed events are read-only.
          </Empty>
        ) : (
          <EventForm key={resource.data.id} event={resource.data} />
        ))}
    </>
  );
}
export function ManageEvent() {
  const active = useActive();
  const { id = "" } = useParams();
  const [cursor, setCursor] = useState("");
  const resource = useResource(`manage:${id}`, (signal) =>
    api.ownerEvent(id, signal),
  );
  const bookings = useResource(`bookings:${id}:${cursor}`, (signal) =>
    api.dashboard(id, cursor, signal),
  );
  const [error, setError] = useState<unknown>();
  const [message, setMessage] = useState("");
  const [action, setAction] = useState<"publish" | "close" | null>(null);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const mutate = async (
    operation: () => Promise<OwnerEvent>,
    success: string,
  ) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(undefined);
    setMessage("");
    try {
      await operation();
      if (active.current) setMessage(success);
    } catch (failure) {
      if (active.current && !isAbort(failure)) setError(failure);
    } finally {
      if (active.current) {
        setAction(null);
        await Promise.all([resource.refresh(), bookings.refresh()]);
      }
      lock.current = false;
      if (active.current) setBusy(false);
    }
  };
  const event = resource.data;
  return (
    <>
      <Breadcrumb to="/organizer">Organizer workspace</Breadcrumb>
      <PageHeading
        eyebrow="Event overview"
        title={event?.title ?? "Manage event."}
        action={
          event &&
          event.status !== "CLOSED" && (
            <Link
              className="button secondary"
              to={`/organizer/events/${id}/edit`}
            >
              Edit details
            </Link>
          )
        }
      />
      <ErrorNotice
        error={resource.error}
        retry={() => void resource.refresh()}
      />
      {resource.loading && <Loading label="Loading event…" />}
      {event && (
        <>
          <div className="detail-layout">
            <article className="panel">
              <Status value={event.status} />
              <h2>{event.location}</h2>
              <p className="preserve-lines">
                {event.description || "No description yet."}
              </p>
              <dl className="metadata">
                <div>
                  <dt>Starts</dt>
                  <dd>
                    <Time value={event.starts_at} />
                  </dd>
                </div>
                <div>
                  <dt>Ends</dt>
                  <dd>
                    <Time value={event.ends_at} />
                  </dd>
                </div>
                <div>
                  <dt>Booking closes</dt>
                  <dd>
                    <Time value={event.booking_closes_at} />
                  </dd>
                </div>
              </dl>
              {event.status === "PUBLISHED" && (
                <Link to={`/events/${id}`}>View public event ↗</Link>
              )}
            </article>
            <aside className="panel booking-panel">
              <h2>Event controls</h2>
              <div role="status">
                {message && <p className="notice success">{message}</p>}
              </div>
              <ErrorNotice error={error} />
              {event.status === "CLOSED" ? (
                <p className="notice">
                  Closed events are read-only. Existing valid holds and bookings
                  are preserved.
                </p>
              ) : (
                <>
                  <form
                    key={`${event.id}:${event.capacity}`}
                    onSubmit={(formEvent) => {
                      formEvent.preventDefault();
                      const form = formEvent.currentTarget;
                      if (form.reportValidity())
                        void mutate(
                          () =>
                            api.capacity(
                              id,
                              Number(new FormData(form).get("capacity")),
                            ),
                          "Capacity updated.",
                        );
                    }}
                  >
                    <label htmlFor="capacity">Seat capacity</label>
                    <input
                      id="capacity"
                      name="capacity"
                      type="number"
                      required
                      min={1}
                      max={2147483647}
                      step={1}
                      defaultValue={event.capacity}
                    />
                    <small>
                      The server reclaims due holds and checks allocations
                      before accepting a reduction.
                    </small>
                    <button
                      className="secondary full"
                      disabled={busy || resource.loading}
                    >
                      Update capacity
                    </button>
                  </form>
                  <button
                    className={
                      event.status === "DRAFT" ? "full" : "danger-outline full"
                    }
                    disabled={busy || resource.loading}
                    onClick={() =>
                      setAction(event.status === "DRAFT" ? "publish" : "close")
                    }
                  >
                    {event.status === "DRAFT" ? "Publish event" : "Close event"}
                  </button>
                </>
              )}
              <button
                className="secondary full"
                disabled={busy || resource.loading}
                onClick={() => {
                  void resource.refresh();
                  void bookings.refresh();
                }}
              >
                Refresh event & bookings
              </button>
            </aside>
          </div>
          <section className="bookings-section">
            <PageHeading
              eyebrow="Owner-only booking snapshot"
              title="Who's holding a place?"
              level={2}
            >
              Reservation identifiers and statuses, with no customer identities.
              Counts cover this entire event; rows are paginated.
            </PageHeading>
            <ErrorNotice
              error={bookings.error}
              retry={() => void bookings.refresh()}
            />
            {bookings.loading && <Loading label="Loading booking snapshot…" />}
            {bookings.data && (
              <>
                <div className="metric-grid">
                  {Object.entries({
                    "Valid holds": bookings.data.counts.valid_held,
                    "Overdue holds awaiting cleanup":
                      bookings.data.counts.overdue_held,
                    Confirmed: bookings.data.counts.confirmed,
                    Cancelled: bookings.data.counts.cancelled,
                    "Recorded expired": bookings.data.counts.expired,
                    "Stored allocations": bookings.data.allocated_seats,
                  }).map(([label, value]) => (
                    <div className="metric" key={label}>
                      <strong>{value}</strong>
                      <span>{label}</span>
                    </div>
                  ))}
                </div>
                <p className="muted">
                  Capacity: {bookings.data.capacity}. Snapshot:{" "}
                  <Time value={bookings.data.as_of} />. Stored allocations
                  include overdue holds until cleanup records expiration.
                </p>
                {bookings.data.items.length ? (
                  <div className="reservation-list">
                    {bookings.data.items.map((row) => (
                      <ReservationRow
                        key={row.id}
                        reservation={row}
                        privateAction={false}
                      />
                    ))}
                  </div>
                ) : (
                  <Empty title="No reservations yet.">
                    Bookings appear here after attendees hold a seat.
                  </Empty>
                )}
                <Pager
                  next={bookings.data.next_cursor}
                  cursor={cursor}
                  setCursor={setCursor}
                />
              </>
            )}
          </section>
        </>
      )}
      {action && (
        <ConfirmDialog
          title={
            action === "publish" ? "Publish this event?" : "Close this event?"
          }
          confirmLabel={action === "publish" ? "Publish event" : "Close event"}
          busy={busy}
          onClose={() => setAction(null)}
          onConfirm={() =>
            void mutate(
              () => api.transition(id, action),
              action === "publish" ? "Event published." : "Event closed.",
            )
          }
        >
          {action === "publish"
            ? "This makes the event public and locks its start time and booking deadline."
            : "Closing stops new holds and cannot be undone. Existing reservations are preserved."}
        </ConfirmDialog>
      )}
    </>
  );
}
