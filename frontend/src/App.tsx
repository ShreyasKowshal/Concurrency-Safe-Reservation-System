import { useEffect, useState } from "react";
import { getReadiness } from "./api/health";

type Connection = "checking" | "ready" | "database-unavailable" | "api-unavailable";

const labels: Record<Connection, string> = {
  checking: "Checking PostgreSQL connection…",
  ready: "API and PostgreSQL are ready",
  "database-unavailable": "API is running; PostgreSQL is unavailable",
  "api-unavailable": "Cannot reach the API. Check that the backend is running.",
};

export function App() {
  const [connection, setConnection] = useState<Connection>("checking");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 10_000);
    let active = true;
    setConnection("checking");
    void getReadiness(controller.signal)
      .then((health) => {
        if (active) setConnection(health.status === "ready" ? "ready" : "database-unavailable");
      })
      .catch(() => {
        if (active) setConnection("api-unavailable");
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt]);

  return (
    <main>
      <p className="eyebrow">CSRS / Phase 4</p>
      <h1>Concurrency-Safe Reservation System</h1>
      <p className="intro">
        Project foundation for reliable event reservations, with PostgreSQL as the source of truth.
      </p>
      <section aria-labelledby="health-heading">
        <h2 id="health-heading">Development environment</h2>
        <p role="status" aria-live="polite" className={`status ${connection}`}>
          {labels[connection]}
        </p>
        <button disabled={connection === "checking"} onClick={() => setAttempt((value) => value + 1)}>
          Check again
        </button>
      </section>
      <p className="scope">
        The backend includes session authentication and organizer event management. This screen checks
        environment health; event management and booking screens are planned for later phases.
      </p>
      <a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">
        Open local API documentation
      </a>
    </main>
  );
}
