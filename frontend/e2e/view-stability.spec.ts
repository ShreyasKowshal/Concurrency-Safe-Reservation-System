import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { test, expect, type BrowserContext, type Page } from "@playwright/test";

// The existing UUID-scoped fixture owns every record and verifies cleanup counts.
const root = fileURLToPath(new URL("../../", import.meta.url));
const scope = randomUUID();
async function fixture(action: string, cookies: string[] = []) {
  return JSON.parse(
    await new Promise<string>((resolve, reject) => {
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
        { cwd: root, encoding: "utf8", timeout: 30000 },
        (error, stdout) => (error ? reject(error) : resolve(stdout)),
      );
      child.stdin?.end(JSON.stringify(cookies));
    }),
  );
}
let data: {
  emails: Record<string, string>;
  password: string;
  events: Record<string, string>;
  before: Record<string, number>;
};
let contexts: BrowserContext[] = [];
let guest: Page, owner: Page, attendee: Page;
let reservationId: string;
const errors: string[] = [];
test.beforeAll(async ({ browser }) => {
  // Other spec files share the same peer quota. Allow one real server-directed
  // cooldown (at most its default 60s window), without changing test deadlines.
  test.setTimeout(120000);
  data = await fixture("prepare");
  contexts = await Promise.all(
    [0, 1, 2].map(() =>
      browser.newContext({ viewport: { width: 1100, height: 360 } }),
    ),
  );
  [guest, owner, attendee] = await Promise.all(
    contexts.map((c) => c.newPage()),
  );
  for (const page of [guest, owner, attendee])
    page.on("pageerror", (error) => errors.push(error.message));
  for (const [page, email] of [
    [owner, data.emails.owner],
    [attendee, data.emails.rival],
  ] as const) {
    await page.goto("/login");
    await page.getByLabel("Email address").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(data.password);
    for (let attempt = 0; attempt < 2; attempt++) {
      const response = page.waitForResponse(
        (r) =>
          new URL(r.url()).pathname === "/api/v1/auth/login" &&
          r.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Log in", exact: true }).click();
      const reply = await response;
      if (reply.status() !== 429 || attempt === 1) {
        expect(reply.status()).toBe(200);
        break;
      }
      const retryAfter = reply.headers()["retry-after"] ?? "";
      expect(retryAfter).toMatch(/^\d+$/);
      const seconds = Number(retryAfter);
      expect(seconds).toBeGreaterThan(0);
      expect(seconds).toBeLessThanOrEqual(60);
      console.log(`Browser fixture honoring auth Retry-After: ${seconds}s`);
      const alert = page.getByRole("alert");
      await expect(alert).toContainText("Too many requests");
      // Follow the existing UI's authoritative cooldown. Do not disable quotas,
      // clear Redis, mock login success or retry other authentication failures.
      await expect(alert).toContainText("You can try again now.", {
        timeout: (seconds + 2) * 1000,
      });
    }
    await expect(
      page.getByRole("heading", { name: "My reservations." }),
    ).toBeVisible();
  }
  await attendee.goto(`/events/${data.events.experience}`);
  await attendee.getByRole("button", { name: "Hold one seat" }).click();
  await expect(attendee).toHaveURL(/\/reservations\/[0-9a-f-]+$/);
  reservationId = attendee.url().split("/").pop()!;
  await attendee
    .getByRole("button", { name: "Confirm reservation", exact: true })
    .click();
  await expect(attendee.getByText("CONFIRMED", { exact: true })).toBeVisible();
});
test.afterAll(async () => {
  const cookies = (await Promise.all(contexts.map((c) => c.cookies())))
    .flat()
    .filter((c) => c.name === "csrs_session")
    .map((c) => c.value);
  await Promise.all(contexts.map((c) => c.close()));
  if (data)
    expect((await fixture("cleanup", cookies)).after).toEqual(data.before);
});

async function ready(page: Page) {
  await expect(page.locator("main .loading")).toHaveCount(0);
  await expect(
    page.getByText("Checking session…", { exact: true }),
  ).toHaveCount(0);
}

async function switchAwayAndBack(page: Page) {
  // Real separate tab activation, plus a deterministic focus event for headless
  // platforms that do not deliver OS focus notifications. The server is real:
  // pause only its response delivery so assertions cover the pending interval.
  await ready(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let started!: () => void;
  const requested = new Promise<void>((resolve) => {
    started = resolve;
  });
  const pattern = "**/api/v1/auth/me";
  await page.route(pattern, async (route) => {
    const response = await route.fetch();
    started();
    await gate;
    await route.fulfill({ response });
  });
  await page.evaluate(() => {
    const state = window as typeof window & {
      stability?: {
        main: Element | null;
        samples: number[];
      };
    };
    state.stability = {
      main: document.querySelector("main"),
      samples: [],
    };
    const sample = () => state.stability!.samples.push(scrollY);
    window.addEventListener("scroll", sample);
    window.addEventListener("focus", sample);
  });
  const before = await page.evaluate(() => ({
    y: scrollY,
    url: location.href,
    timeOrigin: performance.timeOrigin,
  }));
  const away = await page.context().newPage();
  await away.setContent("<title>Another tab</title><p>Another application</p>");
  await away.bringToFront();
  await page.bringToFront();
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await requested;
  return {
    before,
    finish: async () => {
      const response = page.waitForResponse(
        (r) => new URL(r.url()).pathname === "/api/v1/auth/me",
      );
      release();
      await (await response).finished();
      // Let response parsing, React's commit and a paint finish, including the
      // anonymous 401 path which has no visible loading indicator.
      await page.evaluate(
        () =>
          new Promise<void>((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
          ),
      );
      await expect(
        page.getByText("Checking session…", { exact: true }),
      ).toHaveCount(0);
      await ready(page);
      await page.unroute(pattern);
      await away.close();
    },
  };
}

for (const name of [
  "guest Discover",
  "guest event details",
  "signed-in Discover",
  "signed-in event details",
  "organizer workspace",
  "event creation",
  "event management",
  "event editing",
  "reservation details",
  "My reservations",
]) {
  test(`focus preserves content and scroll: ${name}`, async () => {
    const page = name.startsWith("guest")
      ? guest
      : name.startsWith("signed-in") || name.includes("reservation")
        ? attendee
        : owner;
    const path = name.endsWith("Discover")
      ? "/"
      : name.endsWith("event details")
        ? `/events/${data.events.experience}`
        : name === "organizer workspace"
          ? "/organizer"
          : name === "event creation"
            ? "/organizer/events/new"
            : name === "event management"
              ? `/organizer/events/${data.events.experience}`
              : name === "event editing"
                ? `/organizer/events/${data.events.experience}/edit`
                : name === "reservation details"
                  ? `/reservations/${reservationId}`
                  : "/reservations";
    await page.goto(path);
    await ready(page);
    await expect(page.locator("main h1").first()).toBeVisible();
    if (name === "event creation" || name === "event editing") {
      await page.getByLabel("Event title").fill("Unsaved workshop title");
      await page.getByLabel("Location", { exact: true }).fill("Unsaved room");
      await page
        .getByLabel("Description", { exact: true })
        .fill("Unsaved detailed description");
      if (name === "event creation") {
        await page
          .getByLabel("Starts", { exact: true })
          .fill("2035-01-02T10:00");
        await page.getByLabel("Ends", { exact: true }).fill("2035-01-02T12:00");
        await page
          .getByLabel("Booking closes", { exact: true })
          .fill("2035-01-01T10:00");
        await page.getByLabel("Seat capacity").fill("25");
      }
    }
    // Scroll real page content, including deeply into Discover's event grid.
    await page.evaluate(() =>
      scrollTo(0, document.documentElement.scrollHeight - innerHeight - 20),
    );
    await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(100);
    const transition = await switchAwayAndBack(page);
    let pending;
    try {
      pending = await page.evaluate(() => ({
        heading: !!document.querySelector("main h1"),
        title: document.querySelector<HTMLInputElement>("#title")?.value,
        y: scrollY,
      }));
    } finally {
      await transition.finish();
    }
    console.log(
      JSON.stringify({
        view: name,
        beforeY: transition.before.y,
        pending,
        afterY: await page.evaluate(() => scrollY),
        documentUnchanged:
          (await page.evaluate(() => performance.timeOrigin)) ===
          transition.before.timeOrigin,
      }),
    );
    // A session read is pending. The loaded page and form must remain mounted.
    expect(pending.heading).toBe(true);
    expect(pending.y).toBeCloseTo(transition.before.y, 0);
    if (name === "event creation" || name === "event editing")
      expect(pending.title).toBe("Unsaved workshop title");
    expect(await page.evaluate(() => performance.timeOrigin)).toBe(
      transition.before.timeOrigin,
    );
    expect(page.url()).toBe(transition.before.url);
    await expect
      .poll(() => page.evaluate(() => scrollY))
      .toBeCloseTo(transition.before.y, 0);
    expect(
      await page.evaluate((expectedY) => {
        const s = (
          window as typeof window & {
            stability: { main: Element; samples: number[] };
          }
        ).stability;
        return (
          s.main === document.querySelector("main") &&
          s.samples.every((y) => Math.abs(y - expectedY) < 1)
        );
      }, transition.before.y),
    ).toBe(true);
    if (name === "event creation" || name === "event editing") {
      await expect(page.getByLabel("Event title")).toHaveValue(
        "Unsaved workshop title",
      );
      await expect(page.getByLabel("Location", { exact: true })).toHaveValue(
        "Unsaved room",
      );
      await expect(page.getByLabel("Description", { exact: true })).toHaveValue(
        "Unsaved detailed description",
      );
      if (name === "event creation") {
        await expect(page.getByLabel("Starts", { exact: true })).toHaveValue(
          "2035-01-02T10:00",
        );
        await expect(page.getByLabel("Ends", { exact: true })).toHaveValue(
          "2035-01-02T12:00",
        );
        await expect(
          page.getByLabel("Booking closes", { exact: true }),
        ).toHaveValue("2035-01-01T10:00");
        await expect(page.getByLabel("Seat capacity")).toHaveValue("25");
      }
    }
  });
}

test("intentional links and browser back retain route navigation behavior", async () => {
  await guest.goto("/");
  await ready(guest);
  await guest.evaluate(() => scrollTo(0, 900));
  const link = guest
    .locator(".event-card")
    .first()
    .getByRole("link", { name: /View / });
  await link.scrollIntoViewIfNeeded();
  await link.click();
  await expect(guest).toHaveURL(/\/events\//);
  await ready(guest);
  await expect.poll(() => guest.evaluate(() => scrollY)).toBe(0);
  await guest.goBack();
  await expect(guest).toHaveURL(/\/$/);
  await ready(guest);
  // Native history restoration and scroll anchoring can adjust the pixel offset
  // as the event grid reloads. Keep that existing policy, then verify a focus
  // refresh preserves the resulting view exactly, without another navigation.
  await expect.poll(() => guest.evaluate(() => scrollY)).toBeGreaterThan(100);
  const transition = await switchAwayAndBack(guest);
  await transition.finish();
  expect(guest.url()).toBe(transition.before.url);
  expect(await guest.evaluate(() => performance.timeOrigin)).toBe(
    transition.before.timeOrigin,
  );
  await expect
    .poll(() => guest.evaluate(() => scrollY))
    .toBeCloseTo(transition.before.y, 0);
});

test("ordinary undelayed focus refresh keeps the organizer draft across repeated tab activation", async () => {
  await owner.goto("/organizer/events/new");
  await ready(owner);
  await owner
    .getByLabel("Event title")
    .fill("Draft without network interception");
  await owner.getByLabel("Location", { exact: true }).fill("Unsent room");
  await owner
    .getByLabel("Description", { exact: true })
    .fill("Unsent description");
  await owner.evaluate(() => scrollTo(0, 600));
  const y = await owner.evaluate(() => scrollY);
  expect(y).toBeGreaterThan(100);
  const away = await owner.context().newPage();
  try {
    for (let i = 0; i < 2; i++) {
      await away.bringToFront();
      const response = owner.waitForResponse(
        (r) => new URL(r.url()).pathname === "/api/v1/auth/me",
      );
      await owner.bringToFront();
      await owner.evaluate(() => window.dispatchEvent(new Event("focus")));
      await (await response).finished();
      await expect(owner.getByLabel("Event title")).toHaveValue(
        "Draft without network interception",
      );
      await expect(owner.getByLabel("Location", { exact: true })).toHaveValue(
        "Unsent room",
      );
      await expect(
        owner.getByLabel("Description", { exact: true }),
      ).toHaveValue("Unsent description");
      await expect.poll(() => owner.evaluate(() => scrollY)).toBe(y);
    }
  } finally {
    await away.close();
  }
});

test("focus still detects real server session expiry and removes private state", async () => {
  await owner.goto("/organizer/events/new");
  await ready(owner);
  await owner.getByLabel("Event title").fill("Private unsaved draft");
  const cookies = (await owner.context().cookies())
    .filter((c) => c.name === "csrs_session")
    .map((c) => c.value);
  expect(await fixture("expire-session", cookies)).toEqual({
    sessions_expired: 1,
  });
  await owner.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(
    owner.getByRole("link", { name: "Log in securely" }),
  ).toBeVisible();
  await expect(owner.getByLabel("Event title")).toHaveCount(0);
  await expect(
    owner.getByRole("link", { name: "Organizer", exact: true }),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
});
