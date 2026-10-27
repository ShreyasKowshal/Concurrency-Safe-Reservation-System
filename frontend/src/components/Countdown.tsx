import { useEffect, useMemo, useRef, useState } from "react";
import type { Reservation } from "../api/models";

export function remainingSeconds(
  expires: string,
  serverTime: string,
  elapsed: number,
) {
  return Math.max(
    0,
    Math.ceil((Date.parse(expires) - Date.parse(serverTime) - elapsed) / 1000),
  );
}
export function Countdown({
  reservation,
  onElapsed,
}: {
  reservation: Reservation;
  onElapsed?: () => void;
}) {
  const anchor = useMemo(
    () => ({ at: performance.now(), server: reservation.server_time }),
    [reservation],
  );
  const [tick, setTick] = useState(0);
  const fired = useRef(false);
  const callback = useRef(onElapsed);
  callback.current = onElapsed;
  const remaining = remainingSeconds(
    reservation.hold_expires_at,
    anchor.server,
    performance.now() - anchor.at,
  );
  useEffect(() => {
    const update = () => setTick((n) => n + 1);
    const timer = setInterval(update, 1000);
    document.addEventListener("visibilitychange", update);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", update);
    };
  }, []);
  useEffect(() => {
    if (!remaining && !fired.current) {
      fired.current = true;
      callback.current?.();
    }
  }, [remaining, tick]);
  return (
    <div className={`countdown ${remaining ? "" : "ended"}`}>
      <p className="eyebrow">Your temporary hold</p>
      <div role="timer" aria-live="off" aria-label="Estimated time remaining">
        {String(Math.floor(remaining / 60)).padStart(2, "0")}
        <span>:</span>
        {String(remaining % 60).padStart(2, "0")}
      </div>
      <p role="status">
        {remaining
          ? "Confirm before this time runs out."
          : "Estimated hold time elapsed. Refresh to check server state."}
      </p>
      <small>Based on server time. The server makes the final decision.</small>
    </div>
  );
}
