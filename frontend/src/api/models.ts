import { z } from "zod";

// Small runtime-validated contract layer; mirrors docs/contracts/api.openapi.yaml.
const timestamp = z.iso.datetime({ offset: true });
const id = z.uuid();
export const userSchema = z.object({
  id,
  email: z.string(),
  role: z.enum(["ATTENDEE", "ORGANIZER"]),
});
export const csrfSchema = z.object({ csrf_token: z.string().min(1) });
export const authSchema = csrfSchema.extend({ user: userSchema });
export const eventSchema = z.object({
  id,
  title: z.string(),
  location: z.string(),
  starts_at: timestamp,
  booking_closes_at: timestamp,
  status: z.enum(["DRAFT", "PUBLISHED", "CLOSED"]),
  capacity: z.number().int().positive(),
});
export const detailSchema = eventSchema.extend({
  description: z.string(),
  ends_at: timestamp,
  organizer_id: id,
});
export const ownerSchema = detailSchema.extend({
  allocated_seats: z.number().int().nonnegative(),
});
export const ownerSummarySchema = eventSchema.extend({
  allocated_seats: z.number().int().nonnegative(),
});
export const reservationSchema = z.object({
  id,
  event_id: id,
  status: z.enum(["HELD", "CONFIRMED", "CANCELLED", "EXPIRED"]),
  created_at: timestamp,
  hold_expires_at: timestamp,
  confirmed_at: timestamp.nullable(),
  cancelled_at: timestamp.nullable(),
  expired_at: timestamp.nullable(),
  server_time: timestamp,
});
export const availabilitySchema = z.object({
  event_id: id,
  capacity: z.number().int(),
  available_seats: z.number().int().nonnegative(),
  as_of: timestamp,
});
export const pageSchema = <T extends z.ZodType>(item: T) =>
  z.object({ items: z.array(item), next_cursor: z.string().nullable() });
export const dashboardSchema = z.object({
  event_id: id,
  capacity: z.number().int(),
  allocated_seats: z.number().int(),
  as_of: timestamp,
  counts: z.object({
    valid_held: z.number().int(),
    overdue_held: z.number().int(),
    confirmed: z.number().int(),
    cancelled: z.number().int(),
    expired: z.number().int(),
  }),
  ...pageSchema(reservationSchema).shape,
});
export type User = z.infer<typeof userSchema>;
export type EventSummary = z.infer<typeof eventSchema>;
export type EventDetail = z.infer<typeof detailSchema>;
export type OwnerEvent = z.infer<typeof ownerSchema>;
export type Reservation = z.infer<typeof reservationSchema>;
export type Page<T> = { items: T[]; next_cursor: string | null };
export type EventInput = {
  title: string;
  description: string;
  location: string;
  starts_at: string;
  ends_at: string;
  booking_closes_at: string;
  capacity: number;
};
