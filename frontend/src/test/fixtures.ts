export const eventId = "4d128920-06a2-439c-8f1f-9bbff351399a";
export const reservationId = "c3ae72da-0fd7-400f-b5d0-cb85ca77b552";
export const user = {
  id: "d7ff995d-d753-443c-8854-7519a4426fac",
  email: "attendee@example.com",
  role: "ATTENDEE" as const,
};
export const owner = { ...user, role: "ORGANIZER" as const };
export const event = {
  id: eventId,
  title: "PostgreSQL workshop",
  description: "Learn transactions together.",
  location: "Room 101",
  starts_at: "2035-01-02T10:00:00Z",
  ends_at: "2035-01-02T12:00:00Z",
  booking_closes_at: "2035-01-01T20:00:00Z",
  status: "PUBLISHED" as const,
  capacity: 10,
  organizer_id: user.id,
  allocated_seats: 0,
};
export const reservation = {
  id: reservationId,
  event_id: eventId,
  status: "HELD" as const,
  created_at: "2035-01-01T12:00:00Z",
  hold_expires_at: "2035-01-01T12:05:00Z",
  server_time: "2035-01-01T12:00:00Z",
  confirmed_at: null,
  cancelled_at: null,
  expired_at: null,
};
export const page = <T>(...items: T[]) => ({ items, next_cursor: null });
export function json(
  body: unknown,
  status = 200,
  headers: Record<string, string> = {},
) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}
