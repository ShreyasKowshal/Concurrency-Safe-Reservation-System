import { z } from "zod";
import {
  authSchema,
  availabilitySchema,
  csrfSchema,
  dashboardSchema,
  detailSchema,
  eventSchema,
  ownerSchema,
  ownerSummarySchema,
  pageSchema,
  reservationSchema,
  userSchema,
  type EventInput,
  type Reservation,
} from "./models";

const messages: Record<string, string> = {
  AUTHENTICATION_REQUIRED: "Your session has ended. Please log in again.",
  INVALID_CREDENTIALS: "The email or password is incorrect.",
  CSRF_FAILED:
    "Your security token has expired. Refresh the security token and try again.",
  FORBIDDEN: "Your account does not have permission for this action.",
  NOT_FOUND:
    "This resource is unavailable, unpublished, or belongs to another account.",
  EVENT_FULL:
    "That seat was just reserved by someone else. Please check availability again.",
  BOOKING_CLOSED: "Booking has closed for this event.",
  ACTIVE_RESERVATION_EXISTS:
    "You already have a hold or confirmed reservation. Check My reservations.",
  HOLD_EXPIRED:
    "The server reports that your hold has expired. Please make a new hold if seats remain.",
  INVALID_RESERVATION_STATE:
    "This reservation cannot be confirmed in its current state.",
  CANCELLATION_CLOSED: "Cancellation is closed because the event has started.",
  CAPACITY_BELOW_ALLOCATED:
    "Capacity cannot be lower than the current allocations.",
  INVALID_EVENT_STATE:
    "This action is unavailable in the event's current state. Refresh its details.",
  EVENT_SCHEDULE_IMMUTABLE:
    "Published start times and booking deadlines cannot change.",
  EVENT_NOT_PUBLISHABLE:
    "Set a future start and booking deadline before publishing.",
  INVALID_EVENT_SCHEDULE:
    "Booking must close at or before the start, and the event must end after it starts.",
  INVALID_CURSOR: "This page has changed. Return to the first page.",
  IDEMPOTENCY_KEY_REUSED:
    "This operation conflicts with an earlier request. Refresh your reservations before continuing.",
  REGISTRATION_UNAVAILABLE:
    "This email cannot be registered. Try logging in or use another email.",
  RATE_LIMITED: "Too many requests. Please wait before trying again.",
  TEMPORARILY_UNAVAILABLE:
    "The service is temporarily unavailable. Please try again shortly.",
};
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public retryAfter = 0,
    public uncertain = false,
    public fields: Record<string, string> = {},
  ) {
    super(message);
  }
}
export const isAbort = (error: unknown) =>
  error instanceof DOMException && error.name === "AbortError";
export const errorMessage = (error: unknown) =>
  error instanceof ApiError
    ? error.message
    : "Unable to reach the service. Check your connection and try again.";
const envelope = z.object({
  error: z.object({ code: z.string(), message: z.string() }),
});
const validation = z.object({
  detail: z.array(
    z.object({
      loc: z.array(z.union([z.string(), z.number()])),
      type: z.string(),
      msg: z.string(),
    }),
  ),
});
const fieldNames: Record<string, string> = {
  email: "Email",
  password: "Password",
  title: "Title",
  description: "Description",
  location: "Location",
  starts_at: "Start time",
  ends_at: "End time",
  booking_closes_at: "Booking deadline",
  capacity: "Capacity",
};
type RequestOptions = {
  method?: "POST" | "PATCH";
  body?: unknown;
  key?: string;
  signal?: AbortSignal;
  anonymous?: boolean;
};

export class ApiClient {
  private csrf?: string;
  private csrfRequest?: Promise<string>;
  private generation = 0;
  private controllers = new Set<AbortController>();
  private intents = new Map<string, string>();
  private running = new Map<string, Promise<Reservation>>();
  private cooldown = new Map<string, number>();
  onSessionLost?: () => void;
  constructor(private base = import.meta.env.VITE_API_BASE_URL ?? "/api/v1") {
    // Keep cookie and CSRF traffic on the supported origin, even with configuration.
    if (
      !base.startsWith("/") ||
      base.startsWith("//") ||
      base.includes("?") ||
      base.includes("#") ||
      base.includes("\\")
    )
      throw new Error("Use a same-origin API base path.");
    this.base = base.replace(/\/$/, "");
  }
  reset() {
    this.generation++;
    this.controllers.forEach((c) => c.abort());
    this.controllers.clear();
    this.csrf = undefined;
    this.csrfRequest = undefined;
    this.intents.clear();
    this.running.clear();
    this.cooldown.clear();
  }
  async refreshCsrf() {
    this.csrf = undefined;
    return this.token();
  }
  private token(): Promise<string> {
    if (this.csrf) return Promise.resolve(this.csrf);
    if (this.csrfRequest) return this.csrfRequest;
    const generation = this.generation;
    const pending = this.request("/auth/csrf", csrfSchema)
      .then((value) => {
        if (generation !== this.generation)
          throw new DOMException("Session changed", "AbortError");
        this.csrf = value.csrf_token;
        return this.csrf;
      })
      .finally(() => {
        if (this.csrfRequest === pending) this.csrfRequest = undefined;
      });
    this.csrfRequest = pending;
    return pending;
  }
  async request<T>(
    path: string,
    schema: z.ZodType<T>,
    options: RequestOptions = {},
  ): Promise<T> {
    const generation = this.generation;
    const mutation = !!options.method;
    const scope = path.startsWith("/auth")
      ? "auth"
      : mutation
        ? "mutation"
        : path.startsWith("/events")
          ? "public"
          : "private";
    const wait = Math.ceil(
      ((this.cooldown.get(scope) ?? 0) - performance.now()) / 1000,
    );
    if (wait > 0)
      throw new ApiError(429, "RATE_LIMITED", messages.RATE_LIMITED, wait);
    const token = mutation ? await this.token() : undefined;
    if (generation !== this.generation || options.signal?.aborted)
      throw new DOMException("Cancelled", "AbortError");
    const controller = new AbortController();
    this.controllers.add(controller);
    const abort = () => controller.abort();
    options.signal?.addEventListener("abort", abort, { once: true });
    const timeout = setTimeout(abort, 15000);
    try {
      const response = await fetch(this.base + path, {
        method: options.method ?? "GET",
        credentials: "include",
        cache: "no-store",
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          ...(mutation
            ? { "Content-Type": "application/json", "X-CSRF-Token": token! }
            : {}),
          ...(options.key ? { "Idempotency-Key": options.key } : {}),
        },
        ...(mutation ? { body: JSON.stringify(options.body ?? {}) } : {}),
      });
      if (generation !== this.generation)
        throw new DOMException("Session changed", "AbortError");
      const body: unknown =
        response.status === 204
          ? undefined
          : await response.json().catch(() => null);
      if (!response.ok) {
        const parsed = envelope.safeParse(body);
        const code = parsed.success
          ? parsed.data.error.code
          : `HTTP_${response.status}`;
        const fields: Record<string, string> = {};
        const details = validation.safeParse(body);
        if (details.success)
          details.data.detail.forEach((item) => {
            const name = String(item.loc[1]);
            if (fieldNames[name])
              fields[name] =
                `${fieldNames[name]} is invalid. Check the required format and limits.`;
          });
        const retryHeader = response.headers.get("Retry-After") ?? "";
        const retry = /^\d{1,6}$/.test(retryHeader)
          ? Math.min(Number(retryHeader), 86400)
          : 0;
        if (retry && (response.status === 429 || response.status === 503))
          this.cooldown.set(scope, performance.now() + retry * 1000);
        if (code === "CSRF_FAILED") this.csrf = undefined;
        if (
          response.status === 401 &&
          !options.anonymous &&
          path !== "/auth/me"
        ) {
          this.reset();
          this.onSessionLost?.();
        }
        const fallback =
          response.status === 422
            ? "Please check the form fields and schedule."
            : response.status === 403
              ? messages.FORBIDDEN
              : response.status === 404
                ? messages.NOT_FOUND
                : response.status === 415
                  ? "The server rejected the request format. Refresh this page."
                  : "The service could not complete this request.";
        throw new ApiError(
          response.status,
          code,
          messages[code] ?? fallback,
          retry,
          mutation && response.status >= 500,
          fields,
        );
      }
      const result = schema.safeParse(body);
      if (!result.success)
        throw new ApiError(
          0,
          "INVALID_RESPONSE",
          "The server returned an unexpected response. Refresh authoritative state before continuing.",
          0,
          mutation,
        );
      return result.data;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (generation !== this.generation || options.signal?.aborted)
        throw new DOMException("Cancelled", "AbortError");
      throw new ApiError(
        0,
        "NETWORK_ERROR",
        mutation
          ? options.key
            ? "The response was lost or timed out. The operation may have completed. Retry this same operation or check your reservations."
            : path.startsWith("/auth/")
              ? "The response was lost or timed out. This action may have completed. Reload this page to check your session before trying again."
              : "The response was lost or timed out. This change may have saved. Check the current event before trying again."
          : "Unable to reach the service. Check your connection and try again.",
        0,
        mutation,
      );
    } finally {
      clearTimeout(timeout);
      this.controllers.delete(controller);
      options.signal?.removeEventListener("abort", abort);
    }
  }
  me = (signal?: AbortSignal) =>
    this.request("/auth/me", userSchema, { signal });
  async authenticate(
    mode: "login" | "register",
    email: string,
    password: string,
  ) {
    const result = await this.request(`/auth/${mode}`, authSchema, {
      method: "POST",
      body: { email, password },
      anonymous: true,
    });
    this.csrf = result.csrf_token;
    return result.user;
  }
  async logout() {
    await this.request("/auth/logout", z.undefined(), { method: "POST" });
    this.reset();
  }
  events = (cursor?: string, signal?: AbortSignal) =>
    this.request(`/events${query(cursor)}`, pageSchema(eventSchema), {
      signal,
    });
  event = (id: string, signal?: AbortSignal) =>
    this.request(`/events/${id}`, detailSchema, { signal });
  availability = (id: string, signal?: AbortSignal) =>
    this.request(`/events/${id}/availability`, availabilitySchema, { signal });
  history = (cursor?: string, signal?: AbortSignal) =>
    this.request(
      `/me/reservations${query(cursor)}`,
      pageSchema(reservationSchema),
      { signal },
    );
  reservation = (id: string, signal?: AbortSignal) =>
    this.request(`/reservations/${id}`, reservationSchema, { signal });
  owned = (cursor?: string, signal?: AbortSignal) =>
    this.request(
      `/organizer/events${query(cursor)}`,
      pageSchema(ownerSummarySchema),
      { signal },
    );
  ownerEvent = (id: string, signal?: AbortSignal) =>
    this.request(`/organizer/events/${id}`, ownerSchema, { signal });
  dashboard = (id: string, cursor?: string, signal?: AbortSignal) =>
    this.request(
      `/organizer/events/${id}/dashboard${query(cursor)}`,
      dashboardSchema,
      { signal },
    );
  createEvent = (body: EventInput) =>
    this.request("/organizer/events", ownerSchema, { method: "POST", body });
  editEvent = (id: string, body: Partial<Omit<EventInput, "capacity">>) =>
    this.request(`/organizer/events/${id}`, ownerSchema, {
      method: "PATCH",
      body,
    });
  capacity = (id: string, capacity: number) =>
    this.request(`/organizer/events/${id}/capacity`, ownerSchema, {
      method: "PATCH",
      body: { capacity },
    });
  transition = (id: string, action: "publish" | "close") =>
    this.request(`/organizer/events/${id}/${action}`, ownerSchema, {
      method: "POST",
    });
  hasIntent(action: "hold" | "confirm" | "cancel", id: string) {
    return this.intents.has(
      action === "hold"
        ? `/events/${id}/holds`
        : `/reservations/${id}/${action}`,
    );
  }
  command(
    action: "hold" | "confirm" | "cancel",
    id: string,
  ): Promise<Reservation> {
    const path =
      action === "hold"
        ? `/events/${id}/holds`
        : `/reservations/${id}/${action}`;
    const running = this.running.get(path);
    if (running) return running;
    const generation = this.generation;
    const execute = async () => {
      if (action === "hold" && !this.intents.has(path)) {
        // On reload/navigation, reconcile all owner history pages before creating a fresh intent.
        let cursor: string | undefined;
        const visited = new Set<string>();
        do {
          const page = await this.history(cursor);
          const active = page.items.find(
            (r) =>
              r.event_id === id &&
              (r.status === "HELD" || r.status === "CONFIRMED"),
          );
          if (active) return this.reservation(active.id);
          cursor = page.next_cursor ?? undefined;
          if (cursor && visited.has(cursor))
            throw new ApiError(
              0,
              "INVALID_RESPONSE",
              "Could not reconcile reservation history. Refresh before booking.",
            );
          if (cursor) visited.add(cursor);
        } while (cursor);
      }
      if (generation !== this.generation)
        throw new DOMException("Session changed", "AbortError");
      const key = this.intents.get(path) ?? crypto.randomUUID();
      this.intents.set(path, key);
      let result: Reservation;
      try {
        result = await this.request(path, reservationSchema, {
          method: "POST",
          key,
        });
      } catch (error) {
        if (
          error instanceof ApiError &&
          error.status >= 400 &&
          error.status < 500 &&
          ![401, 403, 429].includes(error.status)
        )
          this.intents.delete(path);
        throw error;
      }
      // Replay bodies can be old, including HELD after a confirmed/cancelled transition.
      const current = await this.reservation(result.id);
      this.intents.delete(path);
      return current;
    };
    const promise = execute().finally(() => {
      if (this.running.get(path) === promise) this.running.delete(path);
    });
    this.running.set(path, promise);
    return promise;
  }
}
function query(cursor?: string) {
  return `?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
}
export const api = new ApiClient();
