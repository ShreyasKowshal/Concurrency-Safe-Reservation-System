import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, isAbort } from "../api/client";
import type { EventSummary } from "../api/models";
import {
  Breadcrumb,
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
  Pager,
  Status,
  Time,
} from "../components/ui";
import { useActive, useResource } from "../hooks";
import { useSession } from "../session";

export function EventCard({
  event,
  organizer = false,
}: {
  event: EventSummary;
  organizer?: boolean;
}) {
  const date = new Date(event.starts_at);
  return (
    <article className="event-card">
      <div className="event-art" aria-hidden="true">
        <span className="art-grid" />
        <div className="art-orbit" />
        <span className="art-word">
          BE
          <br />
          THERE.
        </span>
        <span className="art-caption">A little curiosity goes a long way.</span>
      </div>
      <div className="event-card-body">
        <div className="card-top">
          <span className="date-tile">
            <strong>{date.getDate()}</strong>
            {date.toLocaleDateString(undefined, { month: "short" })}
          </span>
          <Status value={event.status} />
        </div>
        <h2>
          <Link
            to={
              organizer
                ? `/organizer/events/${event.id}`
                : `/events/${event.id}`
            }
          >
            {event.title}
          </Link>
        </h2>
        <p className="muted">{event.location}</p>
        <p className="event-date">
          <Time value={event.starts_at} />
        </p>
        <div className="card-bottom">
          <span>{event.capacity.toLocaleString()} total capacity</span>
          <Link
            aria-label={`${organizer ? "Manage" : "View"} ${event.title}`}
            to={
              organizer
                ? `/organizer/events/${event.id}`
                : `/events/${event.id}`
            }
          >
            {organizer ? "Manage event" : "View event"}{" "}
            <span aria-hidden="true">↗</span>
          </Link>
        </div>
      </div>
    </article>
  );
}
export function Events() {
  const [cursor, setCursor] = useState("");
  const resource = useResource(`events:${cursor}`, (signal) =>
    api.events(cursor, signal),
  );
  return (
    <>
      <section className="hero">
        <div>
          <p className="eyebrow">
            <span className="tiny-dot" /> Gather. Learn. Connect.
          </p>
          <h1>
            Good things happen
            <br />
            when you <em>show up.</em>
          </h1>
          <p>
            Find your next workshop, conversation, or spark of inspiration.
            <br className="desktop-break" /> Your next experience starts with a
            seat.
          </p>
          <a className="button" href="#discover">
            Explore events <span aria-hidden="true">↘</span>
          </a>
        </div>
        <div className="hero-graphic" aria-hidden="true">
          <span className="graphic-label">
            ROOM FOR
            <br />
            NEW PERSPECTIVES
          </span>
          <div className="ticket">
            <span>CSRS / ADMIT ONE</span>
            <b>
              YOU'RE
              <br />
              INVITED.
            </b>
            <div className="ticket-rule" />
            <small>One seat. Endless possibilities.</small>
            <span className="ticket-bars">┃│┃┃│┃│┃┃│</span>
          </div>
          <span className="graphic-star">✳</span>
          <span className="graphic-footer">
            Make your next move a memorable one. ↗
          </span>
        </div>
      </section>
      <section id="discover">
        <PageHeading
          eyebrow="The event board"
          level={2}
          title="Find your next thing."
          action={
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
          }
        >
          Published events, ordered by start time. Times are shown in your local
          timezone.
        </PageHeading>
        <ErrorNotice
          error={resource.error}
          retry={() => void resource.refresh()}
        />
        {resource.loading && <Loading label="Finding events…" />}
        {resource.data && (
          <>
            <div className="section-meta">
              <span>{resource.data.items.length} events on this page</span>
              <span>
                Curiosity welcome <span aria-hidden="true">↗</span>
              </span>
            </div>
            {resource.data.items.length ? (
              <div className="event-grid">
                {resource.data.items.map((event) => (
                  <EventCard key={event.id} event={event} />
                ))}
              </div>
            ) : (
              <Empty title="Something good is on the way.">
                There are no published events on this page. Check back soon.
              </Empty>
            )}
            <Pager
              next={resource.data.next_cursor}
              cursor={cursor}
              setCursor={setCursor}
            />
          </>
        )}
      </section>
      <section className="how-it-works">
        <p className="eyebrow">A simple way to be there</p>
        <div>
          <h2>Find it. Hold it. Make it official.</h2>
          <p>
            Choose an event, hold one seat for up to five minutes, then confirm.
            Availability is a snapshot; your seat is secured only when the
            server accepts your reservation.
          </p>
        </div>
      </section>
    </>
  );
}
export function EventDetails() {
  const active = useActive();
  const { id = "" } = useParams();
  const session = useSession();
  const navigate = useNavigate();
  const resource = useResource(`event:${id}`, (signal) =>
    api.event(id, signal),
  );
  const seats = useResource(`availability:${id}`, (signal) =>
    api.availability(id, signal),
  );
  const [pending, setPending] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState<unknown>();
  const hold = async () => {
    if (lock.current) return;
    lock.current = true;
    setPending(true);
    setError(undefined);
    try {
      const reservation = await api.command("hold", id);
      if (active.current) navigate(`/reservations/${reservation.id}`);
    } catch (failure) {
      if (active.current && !isAbort(failure)) {
        setError(failure);
        void seats.refresh();
        void resource.refresh();
      }
    } finally {
      lock.current = false;
      if (active.current) setPending(false);
    }
  };
  const closed =
    seats.data && resource.data
      ? Date.parse(resource.data.booking_closes_at) <=
        Date.parse(seats.data.as_of)
      : false;
  return (
    <>
      <Breadcrumb to="/">All events</Breadcrumb>
      {resource.loading && <Loading label="Loading event…" />}
      <ErrorNotice
        error={resource.error}
        retry={() => void resource.refresh()}
      />
      {resource.data && (
        <>
          <PageHeading
            eyebrow="An experience worth showing up for"
            title={resource.data.title}
          >
            <Status value={resource.data.status} />
          </PageHeading>
          <div className="detail-layout">
            <article className="panel event-description">
              <p className="eyebrow">About the event</p>
              <h2>A little more to look forward to.</h2>
              <p className="preserve-lines">
                {resource.data.description ||
                  "The organizer has not added a description yet."}
              </p>
              <dl className="metadata">
                <div>
                  <dt>Where</dt>
                  <dd>{resource.data.location}</dd>
                </div>
                <div>
                  <dt>Starts</dt>
                  <dd>
                    <Time value={resource.data.starts_at} />
                  </dd>
                </div>
                <div>
                  <dt>Ends</dt>
                  <dd>
                    <Time value={resource.data.ends_at} />
                  </dd>
                </div>
                <div>
                  <dt>Booking closes</dt>
                  <dd>
                    <Time value={resource.data.booking_closes_at} />
                  </dd>
                </div>
              </dl>
              <small>All times use your local timezone.</small>
            </article>
            <aside className="panel booking-panel">
              <p className="eyebrow">Your place in the room</p>
              <h2>Save yourself a seat.</h2>
              {seats.loading && <Loading label="Checking availability…" />}
              <ErrorNotice
                error={seats.error}
                retry={() => void seats.refresh()}
              />
              {seats.data && (
                <>
                  <p className="seat-count">
                    <strong>{seats.data.available_seats}</strong> /{" "}
                    {seats.data.capacity} seats available
                  </p>
                  <p className="muted">
                    Advisory snapshot at <Time value={seats.data.as_of} />.
                    Another attendee may reserve a seat before you.
                  </p>
                  {seats.data.available_seats === 0 && (
                    <p className="notice warning">
                      Currently full. Refresh availability to check for released
                      seats.
                    </p>
                  )}
                  {closed && (
                    <p className="notice warning">
                      The booking deadline has passed.
                    </p>
                  )}
                </>
              )}
              <ErrorNotice error={error} />
              {session.loading ? (
                <Loading label="Checking session…" />
              ) : session.user ? (
                <>
                  <button
                    className="full"
                    disabled={pending || closed}
                    onClick={() => void hold()}
                  >
                    {pending ? "Requesting your hold…" : "Hold one seat"}{" "}
                    <span aria-hidden="true">→</span>
                  </button>
                  <Link className="text-link" to="/reservations">
                    Check My reservations
                  </Link>
                </>
              ) : (
                <Link
                  className="button full"
                  to={`/login?next=${encodeURIComponent(`/events/${id}`)}`}
                >
                  Log in to hold a seat
                </Link>
              )}
              <button
                className="secondary full"
                disabled={seats.loading || pending}
                onClick={() => void seats.refresh()}
              >
                Refresh availability
              </button>
              <small>
                One seat per attendee. Holds last up to five minutes and end no
                later than the booking deadline. A hold response from the server
                is the allocation decision.
              </small>
            </aside>
          </div>
        </>
      )}
    </>
  );
}
