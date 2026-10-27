import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "./client";
import {
  eventId,
  reservationId,
  reservation,
  json,
  page,
  user,
} from "../test/fixtures";

const clients: ApiClient[] = [];
const client = () => {
  const value = new ApiClient();
  clients.push(value);
  return value;
};
afterEach(() => clients.splice(0).forEach((value) => value.reset()));
const path = (input: RequestInfo | URL) => String(input).split("?")[0];
describe("cookie/CSRF transport and contract validation", () => {
  it("bootstraps CSRF, includes credentials, rotates registration/login tokens, and sends JSON", async () => {
    const calls: RequestInit[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init: RequestInit) => {
        calls.push(init);
        if (path(input).endsWith("/csrf"))
          return json({ csrf_token: "anonymous" });
        if (path(input).endsWith("/register"))
          return json({ user, csrf_token: "rotated-anonymous" }, 201);
        return json({ user, csrf_token: "authenticated" });
      }),
    );
    const api = client();
    await api.authenticate("register", "a@example.com", "a secure passphrase");
    await api.authenticate("login", "a@example.com", "a secure passphrase");
    expect(calls).toHaveLength(3);
    expect(
      calls.every(
        (init) => init.credentials === "include" && init.cache === "no-store",
      ),
    ).toBe(true);
    expect(calls[1].headers).toMatchObject({
      "X-CSRF-Token": "anonymous",
      "Content-Type": "application/json",
    });
    expect(calls[2].headers).toMatchObject({
      "X-CSRF-Token": "rotated-anonymous",
    });
    expect(JSON.parse(String(calls[2].body))).toEqual({
      email: "a@example.com",
      password: "a secure passphrase",
    });
  });
  it("clears session state after a 204 logout", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) =>
      path(input).endsWith("/csrf")
        ? json({ csrf_token: "token" })
        : new Response(null, { status: 204 }),
    );
    vi.stubGlobal("fetch", fetch);
    const api = client();
    await api.logout();
    await api.refreshCsrf();
    expect(
      fetch.mock.calls.filter(([input]) => path(input).endsWith("/csrf")),
    ).toHaveLength(2);
  });
  it("rejects malformed success data rather than treating it as a reservation", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ id: "invalid" })),
    );
    await expect(client().reservation(reservationId)).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });
  it.each([401, 403, 404, 409, 415, 422, 429, 503])(
    "handles HTTP %i without exposing arbitrary server text",
    async (status) => {
      vi.stubGlobal(
        "fetch",
        vi.fn(async () =>
          json(
            {
              error: {
                code: "UNRECOGNIZED",
                message: "postgresql://secret:credential@internal",
              },
            },
            status,
          ),
        ),
      );
      const api = client();
      const lost = vi.fn();
      api.onSessionLost = lost;
      try {
        await api.reservation(reservationId);
        throw new Error("Expected rejection");
      } catch (error) {
        expect(error).toBeInstanceOf(ApiError);
        expect((error as ApiError).status).toBe(status);
        expect((error as ApiError).message).not.toContain("credential");
      }
      expect(lost).toHaveBeenCalledTimes(status === 401 ? 1 : 0);
    },
  );
  it("sanitizes field errors and maps their field names", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(
          {
            detail: [
              {
                loc: ["body", "password"],
                type: "string_too_short",
                msg: "sensitive request input",
              },
            ],
          },
          422,
        ),
      ),
    );
    await expect(client().me()).rejects.toMatchObject({
      fields: { password: expect.stringContaining("Password") },
      uncertain: false,
    });
  });
  it("respects numeric Retry-After without automatic retries", async () => {
    const fetch = vi.fn(async () =>
      json({ error: { code: "RATE_LIMITED", message: "limit" } }, 429, {
        "Retry-After": "30",
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const api = client();
    await expect(api.events()).rejects.toMatchObject({ retryAfter: 30 });
    await expect(api.events()).rejects.toMatchObject({ code: "RATE_LIMITED" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it.each([
    "-1",
    "NaN",
    "https://evil.example",
    "Wed, 21 Oct 2015 07:28:00 GMT",
  ])("ignores untrusted Retry-After %s", async (header) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json({ error: { code: "RATE_LIMITED", message: "limit" } }, 429, {
          "Retry-After": header,
        }),
      ),
    );
    await expect(client().events()).rejects.toMatchObject({ retryAfter: 0 });
  });
  it("refreshes a failed CSRF token only on the next intentional request", async () => {
    let tokens = 0;
    let mutations = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (path(input).endsWith("/csrf"))
          return json({ csrf_token: `token-${++tokens}` });
        if (++mutations === 1)
          return json(
            { error: { code: "CSRF_FAILED", message: "failure" } },
            403,
          );
        return json({ user, csrf_token: "next" });
      }),
    );
    const api = client();
    await expect(
      api.authenticate("login", user.email, "password"),
    ).rejects.toMatchObject({ code: "CSRF_FAILED" });
    expect(tokens).toBe(1);
    await api.authenticate("login", user.email, "password");
    expect(tokens).toBe(2);
  });
  it("aborts stale responses after account reset", async () => {
    let resolve!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((done) => {
            resolve = done;
          }),
      ),
    );
    const api = client();
    const request = api.me();
    api.reset();
    resolve(json(user));
    await expect(request).rejects.toMatchObject({ name: "AbortError" });
  });
  it.each([
    "https://evil.example/api",
    "//evil.example",
    "/api\\evil",
    "/api?secret",
    "/api#fragment",
  ])("rejects unsafe API base %s", (base) => {
    expect(() => new ApiClient(base)).toThrow();
  });
});
describe("durable booking intents", () => {
  it("retains a command key when the mutation succeeds but reconciliation fails", async () => {
    let reads = 0;
    const keys: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init: RequestInit) => {
        if (path(input).endsWith("/csrf")) return json({ csrf_token: "token" });
        if (init.method === "POST") {
          keys.push(
            (init.headers as Record<string, string>)["Idempotency-Key"],
          );
          return json(reservation);
        }
        if (++reads === 1) throw new TypeError("lost reconciliation");
        return json(reservation);
      }),
    );
    const api = client();
    await expect(api.command("confirm", reservationId)).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
    await api.command("confirm", reservationId);
    expect(keys[0]).toBe(keys[1]);
  });
  function transport(
    options: {
      failOnce?: boolean;
      conflictOnce?: boolean;
      replay?: boolean;
    } = {},
  ) {
    let writes = 0;
    const keys: string[] = [];
    const fetch = vi.fn(async (input: RequestInfo | URL, init: RequestInit) => {
      if (path(input).endsWith("/csrf")) return json({ csrf_token: "token" });
      if (path(input).includes("/me/reservations")) return json(page());
      if (init.method === "POST") {
        writes++;
        keys.push((init.headers as Record<string, string>)["Idempotency-Key"]);
        if (options.failOnce && writes === 1)
          throw new TypeError("Response lost after commit");
        if (options.conflictOnce && writes === 1)
          return json({ error: { code: "EVENT_FULL", message: "full" } }, 409);
        return json(reservation, path(input).endsWith("/holds") ? 201 : 200, {
          "Idempotency-Replayed": String(!!options.replay),
        });
      }
      return json(
        options.replay
          ? {
              ...reservation,
              status: "CONFIRMED",
              confirmed_at: "2035-01-01T12:01:00Z",
            }
          : reservation,
      );
    });
    vi.stubGlobal("fetch", fetch);
    return { fetch, keys };
  }
  it.each(["hold", "confirm", "cancel"] as const)(
    "reuses the same key after uncertain %s outcome",
    async (action) => {
      const { keys } = transport({ failOnce: true });
      const api = client();
      const id = action === "hold" ? eventId : reservationId;
      await expect(api.command(action, id)).rejects.toMatchObject({
        uncertain: true,
      });
      await api.command(action, id);
      expect(keys).toHaveLength(2);
      expect(keys[0]).toBe(keys[1]);
    },
  );
  it("collapses duplicate clicks into one logical operation", async () => {
    const { keys } = transport();
    const api = client();
    const a = api.command("hold", eventId),
      b = api.command("hold", eventId);
    expect(a).toBe(b);
    await Promise.all([a, b]);
    expect(keys).toHaveLength(1);
  });
  it("uses a fresh key for an intentional attempt after stored final-seat conflict", async () => {
    const { keys } = transport({ conflictOnce: true });
    const api = client();
    await expect(api.command("hold", eventId)).rejects.toMatchObject({
      code: "EVENT_FULL",
      message: expect.stringContaining("someone else"),
    });
    await api.command("hold", eventId);
    expect(keys[0]).not.toBe(keys[1]);
  });
  it("reconciles an old replay body against fresh authoritative detail", async () => {
    transport({ replay: true });
    expect((await client().command("confirm", reservationId)).status).toBe(
      "CONFIRMED",
    );
  });
  it("recovers a hold from later history pages after reload without another POST", async () => {
    const fetch = vi.fn(async (input: RequestInfo | URL) =>
      path(input).includes("/me/reservations")
        ? json(
            String(input).includes("cursor=")
              ? page(reservation)
              : { items: [], next_cursor: "next" },
          )
        : json(reservation),
    );
    vi.stubGlobal("fetch", fetch);
    expect((await client().command("hold", eventId)).id).toBe(reservationId);
    expect(fetch).toHaveBeenCalledTimes(3);
  });
  it("rejects cyclic pagination before creating a new hold", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ items: [], next_cursor: "cycle" })),
    );
    await expect(client().command("hold", eventId)).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });
});
