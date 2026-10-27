import { useEffect, useState, type ComponentType, type ReactNode } from "react";
import {
  Link,
  NavLink,
  Outlet,
  Route,
  Routes,
  useLocation,
  useParams,
} from "react-router-dom";
import { ApiError } from "./api/client";
import { Empty, ErrorNotice, Loading } from "./components/ui";
import { Auth } from "./pages/Auth";
import { EventDetails, Events } from "./pages/Events";
import {
  CreateEvent,
  EditEvent,
  ManageEvent,
  Organizer,
} from "./pages/Organizer";
import { ReservationDetails, Reservations } from "./pages/Reservations";
import { useSession } from "./session";

export function Guard({
  organizer = false,
  children,
}: {
  organizer?: boolean;
  children?: ReactNode;
}) {
  const session = useSession();
  const location = useLocation();
  if (session.loading) return <Loading label="Checking your session…" />;
  if (
    session.error &&
    !session.user &&
    !(session.error instanceof ApiError && session.error.status === 401)
  )
    return (
      <ErrorNotice error={session.error} retry={() => void session.restore()} />
    );
  if (!session.user)
    return (
      <Empty title="Log in to continue.">
        <Link
          className="button"
          to={`/login?next=${encodeURIComponent(location.pathname)}`}
        >
          Log in securely
        </Link>
      </Empty>
    );
  if (organizer && session.user.role !== "ORGANIZER")
    return (
      <Empty title="Organizer access required.">
        This workspace is available to organizers.{" "}
        <Link to="/">Explore events</Link>
      </Empty>
    );
  return children ?? <Outlet />;
}
function Layout() {
  const session = useSession();
  const location = useLocation();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    document.title = `${location.pathname === "/" ? "Discover experiences" : location.pathname.startsWith("/organizer") ? "Organizer workspace" : location.pathname.startsWith("/reservations") ? "My reservations" : "Your next experience"} · CSRS`;
    document
      .querySelector<HTMLElement>("main h1")
      ?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
    setError(undefined);
  }, [location.pathname]);
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <div className="header-inner">
          <Link className="brand" to="/" aria-label="CSRS home">
            <span className="brand-mark" aria-hidden="true">
              c.
            </span>
            <span>
              CSRS<small>ROOM FOR EXPERIENCES</small>
            </span>
          </Link>
          <nav aria-label="Main navigation">
            <NavLink to="/" end>
              Discover
            </NavLink>
            {session.user && (
              <NavLink to="/reservations">My reservations</NavLink>
            )}
            {session.user?.role === "ORGANIZER" && (
              <NavLink to="/organizer">Organizer</NavLink>
            )}
          </nav>
          <div className="account-nav">
            {session.loading ? (
              <span className="muted">Checking session…</span>
            ) : session.user ? (
              <>
                <span className="account-email" title={session.user.email}>
                  {session.user.email}
                </span>
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => {
                    if (busy) return;
                    setBusy(true);
                    setError(undefined);
                    void session
                      .logout()
                      .catch(setError)
                      .finally(() => setBusy(false));
                  }}
                >
                  {busy ? "Logging out…" : "Log out"}
                </button>
              </>
            ) : (
              <>
                <Link to="/login">Log in</Link>
                <Link className="button compact" to="/register">
                  Get started <span aria-hidden="true">↗</span>
                </Link>
              </>
            )}
          </div>
        </div>
      </header>
      <main
        id="main"
        className="container"
        key={`${session.user?.id ?? "public"}:${session.revision}`}
      >
        <ErrorNotice error={error} />
        {!!session.error && (
          <ErrorNotice
            error={session.error}
            retry={() => void session.restore()}
          />
        )}
        <Outlet />
      </main>
      <footer className="site-footer">
        <div>
          <Link className="footer-brand" to="/">
            CSRS<span aria-hidden="true">↗</span>
          </Link>
          <p>Room for your next experience.</p>
        </div>
        <p>
          Concurrency-Safe Reservation System
          <br />
          <span>Built around reliable reservations.</span>
        </p>
      </footer>
    </>
  );
}
function ResourcePage({ component: Component }: { component: ComponentType }) {
  const { id } = useParams();
  return <Component key={id} />;
}
export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Events />} />
        <Route
          path="events/:id"
          element={<ResourcePage component={EventDetails} />}
        />
        <Route path="login" element={<Auth key="login" mode="login" />} />
        <Route
          path="register"
          element={<Auth key="register" mode="register" />}
        />
        <Route element={<Guard />}>
          <Route path="reservations" element={<Reservations />} />
          <Route
            path="reservations/:id"
            element={<ResourcePage component={ReservationDetails} />}
          />
        </Route>
        <Route element={<Guard organizer />}>
          <Route path="organizer" element={<Organizer />} />
          <Route path="organizer/events/new" element={<CreateEvent />} />
          <Route
            path="organizer/events/:id"
            element={<ResourcePage component={ManageEvent} />}
          />
          <Route
            path="organizer/events/:id/edit"
            element={<ResourcePage component={EditEvent} />}
          />
        </Route>
        <Route
          path="*"
          element={
            <Empty title="This page wandered off.">
              <Link to="/">Head back to discovery</Link> and find something
              worth showing up for.
            </Empty>
          }
        />
      </Route>
    </Routes>
  );
}
