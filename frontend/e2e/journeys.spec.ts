import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { test, expect, type BrowserContext, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// Real backend only. No mocked success data. Fixtures use scoped local admin SQL.
const root = fileURLToPath(new URL("../../", import.meta.url));
async function capture(page: Page, name: string) {
  if (process.env.CSRS_CAPTURE_EVIDENCE !== "1") return;
  await page.screenshot({
    path: join(root, "docs", "evidence", `${name}.png`),
    fullPage: true,
    mask: [page.locator(".account-email")],
    maskColor: "#f4f1e9",
  });
}
const scope = randomUUID();
async function fixture(action: string, cookies: string[] = []) {
  const output = await new Promise<string>((resolve, reject) => {
    const child = execFile(
      "docker",
      [
        "compose",
        "exec",
        "-T",
        "backend",
        "python",
        "scripts/frontend_fixture.py",
        action,
        scope,
      ],
      {
        cwd: root,
        encoding: "utf8",
        timeout: 30000,
        maxBuffer: 1024 * 1024,
      },
      (error, stdout) => {
        if (error) reject(error);
        else resolve(stdout);
      },
    );
    child.stdin?.end(JSON.stringify(cookies));
  });
  return JSON.parse(output);
}
let data: {
  emails: Record<string, string>;
  password: string;
  events: Record<string, string>;
  before: Record<string, number>;
};
let attendee: BrowserContext, rival: BrowserContext, organizer: BrowserContext;
let attendeePage: Page, rivalPage: Page, organizerPage: Page;
const consoleErrors: string[] = [];
let recoveryId = "";
test.describe.configure({ mode: "serial" });
test.beforeAll(async ({ browser }) => {
  data = await fixture("prepare");
  [attendee, rival, organizer] = await Promise.all([
    browser.newContext(),
    browser.newContext(),
    browser.newContext(),
  ]);
  [attendeePage, rivalPage, organizerPage] = await Promise.all([
    attendee.newPage(),
    rival.newPage(),
    organizer.newPage(),
  ]);
  for (const page of [attendeePage, rivalPage, organizerPage])
    page.on("pageerror", (error) => consoleErrors.push(error.message));
});
test.afterAll(async () => {
  const cookies = (
    await Promise.all(
      [attendee, rival, organizer]
        .filter(Boolean)
        .map((context) => context.cookies()),
    )
  )
    .flat()
    .filter((cookie) => cookie.name === "csrs_session")
    .map((cookie) => cookie.value);
  await Promise.all([attendee?.close(), rival?.close(), organizer?.close()]);
  const cleanup = await fixture("cleanup", cookies);
  if (data) expect(cleanup.after).toEqual(data.before);
});
async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(data.password);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "My reservations." }),
  ).toBeVisible();
}
async function hold(page: Page, event: string) {
  await page.goto(`/events/${event}`);
  await page.getByRole("button", { name: "Hold one seat" }).click();
  await expect(page).toHaveURL(/\/reservations\/[0-9a-f-]+$/);
  await expect(page.getByRole("timer")).toBeVisible();
  return page.url().split("/").pop()!;
}
test("attendee registration, login, hold, confirmation, history, cancellation, reload", async () => {
  await attendeePage.goto("/");
  await expect(
    attendeePage.getByRole("heading", { name: "Find your next thing." }),
  ).toBeVisible();
  await expect(
    attendeePage.getByRole("button", { name: "Refresh events" }),
  ).toBeEnabled();
  await expect(attendeePage.locator(".event-card").first()).toBeVisible();
  await capture(attendeePage, "discovery");
  await attendeePage.goto(`/events/${data.events.experience}`);
  await expect(
    attendeePage.getByRole("link", { name: "Log in to hold a seat" }),
  ).toBeVisible();
  await capture(attendeePage, "event-detail");
  await attendeePage.goto("/register");
  await attendeePage.getByLabel("Email address").fill(data.emails.attendee);
  await attendeePage
    .getByLabel("Password", { exact: true })
    .fill(data.password);
  await attendeePage.getByRole("button", { name: "Create account" }).click();
  await expect(
    attendeePage.getByRole("heading", { name: "Account created" }),
  ).toBeVisible();
  await login(attendeePage, data.emails.attendee);
  await hold(attendeePage, data.events.experience);
  await attendeePage.reload();
  await expect(attendeePage.getByRole("timer")).toBeVisible();
  await capture(attendeePage, "held-countdown");
  await attendeePage
    .getByRole("button", { name: "Confirm reservation" })
    .click();
  await expect(
    attendeePage.getByText("CONFIRMED", { exact: true }),
  ).toBeVisible();
  await capture(attendeePage, "confirmed-reservation");
  await attendeePage
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "My reservations", exact: true })
    .click();
  await expect(
    attendeePage.getByText("CONFIRMED", { exact: true }),
  ).toBeVisible();
  await capture(attendeePage, "reservation-history");
  await attendeePage.getByRole("link", { name: "View reservation" }).click();
  await attendeePage
    .getByRole("button", { name: "Cancel reservation", exact: true })
    .click();
  const dialog = attendeePage.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog
    .getByRole("button", { name: "Cancel reservation", exact: true })
    .click();
  await expect(
    attendeePage.getByText("CANCELLED", { exact: true }),
  ).toBeVisible();
});
test("organizer creates, edits, changes capacity, publishes, views bookings, and closes", async () => {
  await login(organizerPage, data.emails.owner);
  await organizerPage
    .getByRole("link", { name: "Organizer", exact: true })
    .click();
  await organizerPage.getByRole("link", { name: /Create an event/ }).click();
  await capture(organizerPage, "event-creation");
  await organizerPage
    .getByLabel("Event title")
    .fill(`Browser lifecycle ${scope.slice(0, 8)}`);
  await organizerPage
    .getByLabel("Location", { exact: true })
    .fill("Lifecycle lab");
  await organizerPage
    .getByLabel("Description")
    .fill("An event created through the real browser form.");
  const start = new Date(Date.now() + 3 * 86400000);
  const local = (value: Date) =>
    new Date(value.getTime() - value.getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 16);
  await organizerPage.getByLabel("Starts", { exact: true }).fill(local(start));
  await organizerPage
    .getByLabel("Ends", { exact: true })
    .fill(local(new Date(start.getTime() + 3600000)));
  await organizerPage
    .getByLabel("Booking closes", { exact: true })
    .fill(local(new Date(start.getTime() - 3600000)));
  await organizerPage.getByLabel("Seat capacity").fill("5");
  await organizerPage.getByRole("button", { name: "Create draft" }).click();
  await expect(organizerPage.getByText("DRAFT", { exact: true })).toBeVisible();
  const url = organizerPage.url();
  await organizerPage.getByRole("link", { name: "Edit details" }).click();
  await organizerPage
    .getByLabel("Location", { exact: true })
    .fill("Updated lifecycle lab");
  await organizerPage.getByRole("button", { name: "Save changes" }).click();
  await expect(
    organizerPage.getByRole("heading", { name: "Updated lifecycle lab" }),
  ).toBeVisible();
  await organizerPage.getByLabel("Seat capacity").fill("6");
  await organizerPage.getByRole("button", { name: "Update capacity" }).click();
  await expect(organizerPage.getByText("Capacity updated.")).toBeVisible();
  await organizerPage
    .getByRole("button", { name: "Publish event", exact: true })
    .click();
  await organizerPage
    .getByRole("dialog")
    .getByRole("button", { name: "Publish event", exact: true })
    .click();
  await expect(
    organizerPage.getByText("PUBLISHED", { exact: true }),
  ).toBeVisible();
  await organizerPage.getByRole("link", { name: "Edit details" }).click();
  await expect(
    organizerPage.getByLabel("Starts", { exact: true }),
  ).toBeDisabled();
  await expect(
    organizerPage.getByLabel("Booking closes", { exact: true }),
  ).toBeDisabled();
  await organizerPage.goto(url);
  await expect(
    organizerPage.getByText("Overdue holds awaiting cleanup"),
  ).toBeVisible();
  await capture(organizerPage, "organizer-dashboard");
  await organizerPage
    .getByRole("button", { name: "Close event", exact: true })
    .click();
  await organizerPage
    .getByRole("dialog")
    .getByRole("button", { name: "Close event", exact: true })
    .click();
  await expect(
    organizerPage.getByText("CLOSED", { exact: true }),
  ).toBeVisible();
  const id = url.split("/").pop();
  await attendeePage.goto(`/events/${id}`);
  await expect(attendeePage.getByRole("alert")).toContainText("unpublished");
});
test("two independent browser sessions contend for the final seat", async () => {
  await login(rivalPage, data.emails.rival);
  await Promise.all([
    attendeePage.goto(`/events/${data.events.final}`),
    rivalPage.goto(`/events/${data.events.final}`),
  ]);
  await Promise.all([
    expect(
      attendeePage.getByRole("button", { name: "Hold one seat" }),
    ).toBeEnabled(),
    expect(
      rivalPage.getByRole("button", { name: "Hold one seat" }),
    ).toBeEnabled(),
  ]);
  let arrivals = 0;
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const statuses = new Map<Page, number>();
  for (const page of [attendeePage, rivalPage]) {
    await page.route(`**/events/${data.events.final}/holds`, async (route) => {
      arrivals++;
      if (arrivals === 2) release();
      await gate;
      await route.continue();
    });
    page.on("response", (response) => {
      if (response.url().endsWith(`/events/${data.events.final}/holds`))
        statuses.set(page, response.status());
    });
  }
  await Promise.all([
    attendeePage.getByRole("button", { name: "Hold one seat" }).click(),
    rivalPage.getByRole("button", { name: "Hold one seat" }).click(),
  ]);
  await expect.poll(() => [...statuses.values()].sort()).toEqual([201, 409]);
  const loser = statuses.get(attendeePage) === 409 ? attendeePage : rivalPage;
  const winner = loser === attendeePage ? rivalPage : attendeePage;
  await expect(winner).toHaveURL(/\/reservations\/[0-9a-f-]+$/);
  await expect(loser.getByRole("alert")).toContainText(
    "That seat was just reserved by someone else",
  );
  for (const page of [attendeePage, rivalPage])
    await page.unroute(`**/events/${data.events.final}/holds`);
});
test("expired hold is projected from the server and late confirmation is rejected", async () => {
  const id = await hold(attendeePage, data.events.expiry);
  await fixture("expire");
  await attendeePage.getByRole("button", { name: "Refresh status" }).click();
  await expect(
    attendeePage.getByText("EXPIRED", { exact: true }),
  ).toBeVisible();
  await expect(
    attendeePage.getByRole("button", { name: "Confirm reservation" }),
  ).toHaveCount(0);
  const status = await attendeePage.evaluate(async (reservationId) => {
    const csrf = await (
      await fetch("/api/v1/auth/csrf", { credentials: "include" })
    ).json();
    const result = await fetch(
      `/api/v1/reservations/${reservationId}/confirm`,
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf.csrf_token,
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: "{}",
      },
    );
    return { status: result.status, body: await result.json() };
  }, id);
  expect(status.status).toBe(409);
  expect(status.body.error.code).toBe("HOLD_EXPIRED");
});
test("lost successful HTTP response retries the same key and recovers one reservation", async () => {
  await attendeePage.goto(`/events/${data.events.recovery}`);
  const keys: string[] = [];
  let lost = false;
  await attendeePage.route(
    `**/events/${data.events.recovery}/holds`,
    async (route) => {
      keys.push(route.request().headers()["idempotency-key"]);
      if (!lost) {
        lost = true;
        const response = await route.fetch();
        expect(response.status()).toBe(201);
        await route.abort("failed");
      } else await route.continue();
    },
  );
  await attendeePage.getByRole("button", { name: "Hold one seat" }).click();
  await expect(attendeePage.getByRole("alert")).toContainText(
    "response was lost",
  );
  await attendeePage.getByRole("button", { name: "Hold one seat" }).click();
  await expect(attendeePage).toHaveURL(/\/reservations\/[0-9a-f-]+$/);
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  await attendeePage.unroute(`**/events/${data.events.recovery}/holds`);
  await expect(attendeePage.getByRole("timer")).toBeVisible();
  recoveryId = attendeePage.url().split("/").pop()!;
});
test("responsive, keyboard, accessibility, deep-link and private-state checks", async () => {
  await organizerPage.goto(`/organizer/events/${data.events.experience}/edit`);
  await organizerPage.getByLabel("Event title").fill("W".repeat(200));
  await organizerPage
    .getByLabel("Location", { exact: true })
    .fill("L".repeat(300));
  await organizerPage.getByRole("button", { name: "Save changes" }).click();
  await expect(
    organizerPage.getByRole("heading", { name: "W".repeat(200), exact: true }),
  ).toBeVisible();
  for (const width of [390, 768, 1440]) {
    await organizerPage.setViewportSize({ width, height: 900 });
    await organizerPage.goto(`/organizer/events/${data.events.experience}`);
    await expect(
      organizerPage.getByText("Stored allocations", { exact: true }),
    ).toBeVisible();
    expect(
      await organizerPage.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }
  expect(
    (
      await new AxeBuilder({ page: organizerPage })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await attendeePage.setViewportSize({ width: 390, height: 844 });
  for (const path of [
    "/",
    `/events/${data.events.experience}`,
    "/reservations",
    `/reservations/${recoveryId}`,
  ]) {
    await attendeePage.goto(path);
    await expect(attendeePage.locator("main h1")).toBeVisible();
    await expect(
      attendeePage.getByRole("button", { name: "Log out" }),
    ).toBeVisible();
    const results = await new AxeBuilder({ page: attendeePage })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(results.violations).toEqual([]);
    expect(
      await attendeePage.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  // Exercise native dialog focus, keyboard dismissal, and focus restoration.
  await attendeePage.getByRole("button", { name: "Release hold" }).focus();
  await attendeePage.keyboard.press("Enter");
  await expect(attendeePage.getByRole("dialog")).toBeVisible();
  await expect(
    attendeePage.getByRole("button", { name: "Keep it" }),
  ).toBeFocused();
  expect(
    (
      await new AxeBuilder({ page: attendeePage })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await attendeePage.keyboard.press("Escape");
  await expect(attendeePage.getByRole("dialog")).toHaveCount(0);
  await expect(
    attendeePage.getByRole("button", { name: "Release hold" }),
  ).toBeFocused();
  await attendeePage.goto(`/reservations`);
  await attendeePage.getByRole("button", { name: "Log out" }).click();
  await expect(
    attendeePage.getByRole("link", { name: "Log in securely" }),
  ).toBeVisible();
  await expect(attendeePage.getByText("HELD", { exact: true })).toHaveCount(0);
  for (const path of ["/login", "/register"]) {
    await attendeePage.goto(path);
    await expect(attendeePage.getByLabel("Email address")).toBeVisible();
    expect(
      (
        await new AxeBuilder({ page: attendeePage })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
          .analyze()
      ).violations,
    ).toEqual([]);
  }
  await login(attendeePage, data.emails.rival);
  await expect(
    attendeePage.getByText(`Event ID: ${data.events.recovery}`, {
      exact: true,
    }),
  ).toHaveCount(0);
  await attendeePage.goto(`/reservations/${recoveryId}`);
  await expect(attendeePage.getByRole("alert")).toContainText(
    "belongs to another account",
  );
  expect(consoleErrors).toEqual([]);
});
test("SQL capacity/counter/uniqueness reconciliation", async () => {
  expect(await fixture("verify")).toEqual({
    counter_invariants: true,
    active_uniqueness: true,
    final_seat_allocated: 1,
  });
});
test("server session expiration clears private browser state", async () => {
  const cookies = (await attendee.cookies())
    .filter((cookie) => cookie.name === "csrs_session")
    .map((cookie) => cookie.value);
  expect(await fixture("expire-session", cookies)).toEqual({
    sessions_expired: 1,
  });
  await attendeePage.goto("/reservations");
  await attendeePage.reload();
  await expect(
    attendeePage.getByRole("link", { name: "Log in securely" }),
  ).toBeVisible();
  await expect(
    attendeePage.getByRole("button", { name: "Log out" }),
  ).toHaveCount(0);
  await expect(
    attendeePage.getByText("CONFIRMED", { exact: true }),
  ).toHaveCount(0);
});
