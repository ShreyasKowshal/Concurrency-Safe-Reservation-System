import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { api } from "./api/client";
import { Countdown, remainingSeconds } from "./components/Countdown";
import { EventForm } from "./pages/Organizer";
import { SessionProvider, safeRedirect } from "./session";
import {
  event,
  eventId,
  json,
  owner,
  page,
  reservation,
  reservationId,
  user,
} from "./test/fixtures";

type Handler = (
  path: string,
  init: RequestInit,
) => Response | Promise<Response> | undefined;
function server(
  identity: typeof user | typeof owner | null = user,
  handler?: Handler,
) {
  const state = { identity };
  const fetch = vi.fn(
    async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), "http://localhost");
      const path = url.pathname;
      const custom = await handler?.(path + url.search, init);
      if (custom) return custom;
      if (path.endsWith("/auth/me"))
        return state.identity
          ? json(state.identity)
          : json(
              { error: { code: "AUTHENTICATION_REQUIRED", message: "login" } },
              401,
            );
      if (path.endsWith("/auth/csrf")) return json({ csrf_token: "csrf" });
      if (path.endsWith("/auth/login")) {
        state.identity = user;
        return json({ user, csrf_token: "logged-in" });
      }
      if (path.endsWith("/auth/register"))
        return json({ user, csrf_token: "registered" }, 201);
      if (path.endsWith("/auth/logout")) {
        state.identity = null;
        return new Response(null, { status: 204 });
      }
      if (path.endsWith("/availability"))
        return json({
          event_id: eventId,
          capacity: 10,
          available_seats: 2,
          as_of: reservation.server_time,
        });
      if (path.endsWith("/dashboard"))
        return json({
          ...page(reservation),
          event_id: eventId,
          capacity: 10,
          allocated_seats: 1,
          as_of: reservation.server_time,
          counts: {
            valid_held: 1,
            overdue_held: 0,
            confirmed: 0,
            cancelled: 0,
            expired: 0,
          },
        });
      if (path.endsWith("/me/reservations")) return json(page(reservation));
      if (path.endsWith(`/reservations/${reservationId}`))
        return json(reservation);
      if (path.endsWith(`/organizer/events/${eventId}`)) return json(event);
      if (path.endsWith("/organizer/events")) return json(page(event));
      if (path.endsWith(`/events/${eventId}`)) return json(event);
      if (path.endsWith("/events")) return json(page(event));
      return json({ error: { code: "NOT_FOUND", message: "absent" } }, 404);
    },
  );
  vi.stubGlobal("fetch", fetch);
  return { state, fetch };
}
function app(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SessionProvider>
        <App />
      </SessionProvider>
    </MemoryRouter>,
  );
}
afterEach(() => api.reset());
describe("session and authentication interaction", () => {
  it("isolates private state when a different account is restored on focus", async () => {
    const { state } = server(user, (path) =>
      path.includes("/me/reservations")
        ? json(
            state.identity?.email === user.email ? page(reservation) : page(),
          )
        : undefined,
    );
    app("/reservations");
    expect(
      await screen.findByText(`Reservation ${reservationId.slice(0, 8)}`),
    ).toBeVisible();
    state.identity = {
      ...user,
      id: "c2accfce-5865-4f10-bb4a-4f240c8a938e",
      email: "next@example.com",
    };
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(await screen.findByText("next@example.com")).toBeVisible();
    expect(
      screen.queryByText(`Reservation ${reservationId.slice(0, 8)}`),
    ).not.toBeInTheDocument();
  });
  it("restores the session and exposes appropriate private navigation", async () => {
    server();
    app("/");
    expect(
      await screen.findByRole("link", { name: "My reservations" }),
    ).toBeVisible();
    expect(screen.getByText(user.email)).toBeVisible();
    expect(
      screen.queryByRole("link", { name: "Organizer" }),
    ).not.toBeInTheDocument();
  });
  it("keeps organizer routes protected from attendees", async () => {
    const { fetch } = server();
    app("/organizer");
    expect(await screen.findByText("Organizer access required.")).toBeVisible();
    expect(
      fetch.mock.calls.some(([input]) =>
        String(input).includes("/organizer/events"),
      ),
    ).toBe(false);
  });
  it("keeps private data out of anonymous routes", async () => {
    const { fetch } = server(null);
    app("/reservations");
    expect(
      await screen.findByRole("link", { name: "Log in securely" }),
    ).toBeVisible();
    expect(
      fetch.mock.calls.some(([input]) =>
        String(input).includes("/me/reservations"),
      ),
    ).toBe(false);
  });
  it("logs in through the form and safely returns to reservations", async () => {
    server(null);
    app("/login?next=https://evil.example");
    const actor = userEvent.setup();
    await actor.type(await screen.findByLabelText("Email address"), user.email);
    await actor.type(screen.getByLabelText("Password"), "my password");
    await actor.click(screen.getByRole("button", { name: "Log in" }));
    expect(
      await screen.findByRole("heading", { name: "My reservations." }),
    ).toBeVisible();
  });
  it("registers without pretending the account is logged in", async () => {
    server(null);
    app("/register");
    const actor = userEvent.setup();
    await actor.type(await screen.findByLabelText("Email address"), user.email);
    await actor.type(
      screen.getByLabelText("Password"),
      "a memorable password phrase",
    );
    await actor.click(screen.getByRole("button", { name: "Create account" }));
    expect(
      await screen.findByRole("heading", { name: "Account created" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("link", { name: "My reservations" }),
    ).not.toBeInTheDocument();
  });
  it("validates registration password bounds in labeled controls", async () => {
    server(null);
    app("/register");
    const input = await screen.findByLabelText("Password");
    expect(input).toHaveAttribute("minlength", "15");
    expect(input).toHaveAttribute("maxlength", "128");
    expect(input).toHaveAccessibleDescription(
      expect.stringContaining("15–128"),
    );
  });
  it("clears private history on logout", async () => {
    server();
    app("/reservations");
    expect(
      await screen.findByText(`Reservation ${reservationId.slice(0, 8)}`),
    ).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Log out" }));
    expect(
      await screen.findByRole("link", { name: "Log in securely" }),
    ).toBeVisible();
    expect(
      screen.queryByText(`Reservation ${reservationId.slice(0, 8)}`),
    ).not.toBeInTheDocument();
  });
  it("handles session expiry during a protected read", async () => {
    server(user, (path) =>
      path.includes("/me/reservations")
        ? json(
            { error: { code: "AUTHENTICATION_REQUIRED", message: "ended" } },
            401,
          )
        : undefined,
    );
    app("/reservations");
    expect(
      await screen.findByText("Your session has ended. Please log in again."),
    ).toBeVisible();
    expect(
      screen.queryByText(`Reservation ${reservationId.slice(0, 8)}`),
    ).not.toBeInTheDocument();
  });
  it("shows rate-limit feedback and disables immediate retry", async () => {
    server(null, (path) =>
      path === "/api/v1/auth/login"
        ? json({ error: { code: "RATE_LIMITED", message: "limit" } }, 429, {
            "Retry-After": "10",
          })
        : undefined,
    );
    app("/login");
    const actor = userEvent.setup();
    await actor.type(await screen.findByLabelText("Email address"), user.email);
    await actor.type(screen.getByLabelText("Password"), "password");
    await actor.click(screen.getByRole("button", { name: "Log in" }));
    expect(
      await screen.findByText(
        "Too many requests. Please wait before trying again.",
      ),
    ).toBeVisible();
    expect(screen.getByText(/Try again in/)).toBeVisible();
  });
  it.each([
    "https://evil.example",
    "//evil.example",
    "/\\evil",
    "/login",
    "/events/id?next=evil",
  ])("rejects redirect %s", (target) => {
    expect(safeRedirect(target)).toBe("/reservations");
  });
});
describe("events and reservation workflows", () => {
  it("does not redirect back to a departed screen after a hold completes", async () => {
    let finish!: (response: Response) => void;
    const held = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    let sent = false;
    server(user, (path) =>
      path.includes("/me/reservations")
        ? json(page())
        : path.endsWith("/holds")
          ? ((sent = true), held)
          : undefined,
    );
    app(`/events/${eventId}`);
    await userEvent.click(
      await screen.findByRole("button", { name: "Hold one seat" }),
    );
    await waitFor(() => expect(sent).toBe(true));
    await userEvent.click(
      within(screen.getByRole("navigation")).getByRole("link", {
        name: "My reservations",
      }),
    );
    expect(
      await screen.findByRole("heading", { name: "My reservations." }),
    ).toBeVisible();
    await act(async () => {
      finish(json(reservation, 201));
      await held;
    });
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "My reservations." }),
      ).toBeVisible(),
    );
    expect(screen.queryByRole("timer")).not.toBeInTheDocument();
  });
  it("renders published discovery and real metadata", async () => {
    server(null);
    app("/");
    expect(
      await screen.findByRole("heading", { name: event.title }),
    ).toBeVisible();
    expect(screen.getByText("Room 101")).toBeVisible();
    expect(
      screen.getByRole("link", { name: `View ${event.title}` }),
    ).toHaveAttribute("href", `/events/${eventId}`);
  });
  it("shows an empty event board", async () => {
    server(null, (path) =>
      path.startsWith("/api/v1/events?") ? json(page()) : undefined,
    );
    app("/");
    expect(
      await screen.findByText("Something good is on the way."),
    ).toBeVisible();
  });
  it("handles unpublished detail without leaking metadata", async () => {
    server(null, (path) =>
      path === `/api/v1/events/${eventId}`
        ? json({ error: { code: "NOT_FOUND", message: "missing" } }, 404)
        : undefined,
    );
    app(`/events/${eventId}`);
    expect(await screen.findByRole("alert")).toHaveTextContent("unpublished");
    expect(screen.queryByText(event.description)).not.toBeInTheDocument();
  });
  it("renders sold-out advice and the booking deadline", async () => {
    server(user, (path) =>
      path.endsWith("/availability")
        ? json({
            event_id: eventId,
            available_seats: 0,
            capacity: 10,
            as_of: reservation.server_time,
          })
        : undefined,
    );
    app(`/events/${eventId}`);
    expect(await screen.findByText(/Currently full/)).toBeVisible();
    expect(screen.getByText("Booking closes")).toBeVisible();
    expect(screen.getByRole("button", { name: "Hold one seat" })).toBeEnabled();
  });
  it("shows closed booking based on server as_of rather than the device date", async () => {
    server(user, (path) =>
      path.endsWith("/availability")
        ? json({
            event_id: eventId,
            available_seats: 2,
            capacity: 10,
            as_of: "2035-01-02T10:00:00Z",
          })
        : undefined,
    );
    app(`/events/${eventId}`);
    expect(
      await screen.findByText("The booking deadline has passed."),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Hold one seat" }),
    ).toBeDisabled();
  });
  it("holds a seat and navigates to authoritative detail", async () => {
    server(user, (path, init) =>
      path.includes("/me/reservations")
        ? json(page())
        : path.endsWith("/holds") && init.method === "POST"
          ? json(reservation, 201)
          : undefined,
    );
    app(`/events/${eventId}`);
    await userEvent.click(
      await screen.findByRole("button", { name: "Hold one seat" }),
    );
    expect(await screen.findByRole("timer")).toHaveTextContent("05:00");
    expect(screen.getByText(`Reservation ID:`, { exact: false })).toBeVisible();
  });
  it("reconciles confirmation against current state", async () => {
    let confirmed = false;
    server(user, (path, init) => {
      if (path.endsWith("/confirm") && init.method === "POST") {
        confirmed = true;
        return json({
          ...reservation,
          status: "CONFIRMED",
          confirmed_at: "2035-01-01T12:01:00Z",
        });
      }
      if (path.endsWith(`/reservations/${reservationId}`) && confirmed)
        return json({
          ...reservation,
          status: "CONFIRMED",
          confirmed_at: "2035-01-01T12:01:00Z",
        });
    });
    app(`/reservations/${reservationId}`);
    await userEvent.click(
      await screen.findByRole("button", { name: "Confirm reservation" }),
    );
    expect(
      await screen.findByRole("heading", { name: "See you there." }),
    ).toBeVisible();
    expect(screen.queryByRole("timer")).not.toBeInTheDocument();
  });
  it("requires a destructive step before cancellation and refreshes status", async () => {
    let cancelled = false;
    server(user, (path, init) => {
      if (path.endsWith("/cancel") && init.method === "POST") cancelled = true;
      if (
        cancelled &&
        (path.endsWith("/cancel") ||
          path.endsWith(`/reservations/${reservationId}`))
      )
        return json({
          ...reservation,
          status: "CANCELLED",
          cancelled_at: "2035-01-01T12:01:00Z",
        });
    });
    app(`/reservations/${reservationId}`);
    await userEvent.click(
      await screen.findByRole("button", { name: "Release hold" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAccessibleName("Release your hold?");
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Release hold" }),
    );
    expect(await screen.findByText("CANCELLED")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Confirm reservation" }),
    ).not.toBeInTheDocument();
  });
  it("presents expired effective state and no confirmation action", async () => {
    server(user, (path) =>
      path.endsWith(`/reservations/${reservationId}`)
        ? json({ ...reservation, status: "EXPIRED" })
        : undefined,
    );
    app(`/reservations/${reservationId}`);
    expect(await screen.findByText("EXPIRED")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Confirm reservation" }),
    ).not.toBeInTheDocument();
  });
  it("keeps history usable when the related event is closed", async () => {
    server(user, (path) =>
      path === `/api/v1/events/${eventId}`
        ? json({ error: { code: "NOT_FOUND", message: "closed" } }, 404)
        : undefined,
    );
    app(`/reservations/${reservationId}`);
    expect(
      await screen.findByText(/Public event details may be unavailable/),
    ).toBeVisible();
    expect(
      await screen.findByRole("button", { name: "Confirm reservation" }),
    ).toBeVisible();
  });
  it("shows useful final-seat contention feedback", async () => {
    server(user, (path) =>
      path.includes("/me/reservations")
        ? json(page())
        : path.endsWith("/holds")
          ? json({ error: { code: "EVENT_FULL", message: "full" } }, 409)
          : undefined,
    );
    app(`/events/${eventId}`);
    await userEvent.click(
      await screen.findByRole("button", { name: "Hold one seat" }),
    );
    expect(
      await screen.findByText(/That seat was just reserved by someone else/),
    ).toBeVisible();
  });
});
describe("server-anchored countdown", () => {
  it("does not use an inaccurate wall clock", () => {
    vi.setSystemTime(new Date("2045-01-01"));
    expect(
      remainingSeconds(
        reservation.hold_expires_at,
        reservation.server_time,
        60000,
      ),
    ).toBe(240);
  });
  it("treats deadline equality as elapsed", () => {
    expect(
      remainingSeconds(
        reservation.hold_expires_at,
        reservation.hold_expires_at,
        0,
      ),
    ).toBe(0);
  });
  it("updates, announces elapsed only once, and cleans up its timer", async () => {
    vi.useFakeTimers();
    const elapsed = vi.fn();
    const view = render(
      <Countdown
        reservation={{
          ...reservation,
          hold_expires_at: "2035-01-01T12:00:02Z",
        }}
        onElapsed={elapsed}
      />,
    );
    expect(screen.getByRole("timer")).toHaveTextContent("00:02");
    await act(async () => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByRole("timer")).toHaveTextContent("00:00");
    expect(elapsed).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
describe("organizer management", () => {
  it("lists owned events and offers create/manage actions", async () => {
    server(owner);
    app("/organizer");
    expect(
      await screen.findByRole("link", { name: `Manage ${event.title}` }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: /Create an event/ }),
    ).toHaveAttribute("href", "/organizer/events/new");
  });
  it("renders separated booking counts without fabricating customers", async () => {
    server(owner);
    app(`/organizer/events/${eventId}`);
    expect(
      await screen.findByText("Overdue holds awaiting cleanup"),
    ).toBeVisible();
    expect(screen.getByText("Stored allocations")).toBeVisible();
    expect(screen.queryByText("Customer email")).not.toBeInTheDocument();
  });
  it("keeps published schedule immutable but permits end edits", async () => {
    server(owner);
    app(`/organizer/events/${eventId}/edit`);
    expect(await screen.findByLabelText("Starts")).toBeDisabled();
    expect(screen.getByLabelText("Booking closes")).toBeDisabled();
    expect(screen.getByLabelText("Ends")).toBeEnabled();
  });
  it("renders closed events read-only", async () => {
    server(owner, (path) =>
      path === `/api/v1/organizer/events/${eventId}`
        ? json({ ...event, status: "CLOSED" })
        : undefined,
    );
    app(`/organizer/events/${eventId}`);
    expect(
      await screen.findByText(/Closed events are read-only/),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Update capacity" }),
    ).not.toBeInTheDocument();
  });
  it("updates capacity through its separate endpoint", async () => {
    let body: unknown;
    server(owner, (path, init) => {
      if (path.endsWith("/capacity")) {
        body = JSON.parse(String(init.body));
        return json({ ...event, capacity: 12 });
      }
    });
    app(`/organizer/events/${eventId}`);
    const input = await screen.findByLabelText("Seat capacity");
    fireEvent.change(input, { target: { value: "12" } });
    await userEvent.click(
      screen.getByRole("button", { name: "Update capacity" }),
    );
    expect(await screen.findByText("Capacity updated.")).toBeVisible();
    expect(body).toEqual({ capacity: 12 });
  });
  it.each(["publish", "close"] as const)(
    "confirms %s before invoking its real route",
    async (action) => {
      let called = false;
      server(owner, (path, init) => {
        if (path === `/api/v1/organizer/events/${eventId}`)
          return json({
            ...event,
            status: action === "publish" ? "DRAFT" : "PUBLISHED",
          });
        if (path.endsWith(`/${action}`) && init.method === "POST") {
          called = true;
          return json({
            ...event,
            status: action === "publish" ? "PUBLISHED" : "CLOSED",
          });
        }
      });
      app(`/organizer/events/${eventId}`);
      const label = action === "publish" ? "Publish event" : "Close event";
      await userEvent.click(await screen.findByRole("button", { name: label }));
      expect(called).toBe(false);
      await userEvent.click(
        within(screen.getByRole("dialog")).getByRole("button", { name: label }),
      );
      await waitFor(() => expect(called).toBe(true));
    },
  );
  it("validates merged schedules before sending writes", async () => {
    const { fetch } = server(owner);
    render(
      <MemoryRouter>
        <EventForm />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Event title"), {
      target: { value: "New" },
    });
    fireEvent.change(screen.getByLabelText("Location"), {
      target: { value: "Room" },
    });
    for (const [name, value] of [
      ["Starts", "2035-01-02T10:00"],
      ["Ends", "2035-01-01T10:00"],
      ["Booking closes", "2035-01-01T09:00"],
      ["Seat capacity", "10"],
    ])
      fireEvent.change(screen.getByLabelText(name), { target: { value } });
    await userEvent.click(screen.getByRole("button", { name: "Create draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Booking must close",
    );
    expect(fetch).not.toHaveBeenCalled();
  });
});
