import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, errorMessage } from "../api/client";

export const dateTime = (value: string) =>
  new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZoneName: undefined,
  }).format(new Date(value));
export function Time({ value }: { value: string }) {
  return <time dateTime={value}>{dateTime(value)}</time>;
}
export function Status({ value }: { value: string }) {
  return (
    <span className={`badge ${value.toLowerCase()}`}>
      <span aria-hidden="true">●</span>
      <span>{value}</span>
    </span>
  );
}
export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-symbol" aria-hidden="true">
        ◇
      </span>
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
  );
}
export function ErrorNotice({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  const [remaining, setRemaining] = useState(0);
  const [tokenStatus, setTokenStatus] = useState("");
  const [tokenBusy, setTokenBusy] = useState(false);
  useEffect(() => {
    const deadline =
      performance.now() +
      (error instanceof ApiError ? error.retryAfter * 1000 : 0);
    const update = () =>
      setRemaining(
        Math.max(0, Math.ceil((deadline - performance.now()) / 1000)),
      );
    update();
    if (!(error instanceof ApiError) || error.retryAfter <= 0) return;
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [error]);
  if (!error) return null;
  return (
    <div className="notice error" role="alert">
      <strong>{errorMessage(error)}</strong>
      {error instanceof ApiError && error.retryAfter > 0 && (
        <p aria-live="off">
          {remaining
            ? `Try again in ${remaining} seconds.`
            : "You can try again now."}
        </p>
      )}
      {error instanceof ApiError && error.uncertain && (
        <p>Check the current server state before starting another operation.</p>
      )}
      {error instanceof ApiError && Object.keys(error.fields).length > 0 && (
        <ul>
          {Object.values(error.fields).map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}
      {error instanceof ApiError && error.code === "CSRF_FAILED" && (
        <>
          <button
            className="secondary"
            disabled={tokenBusy}
            onClick={() => {
              setTokenBusy(true);
              void api
                .refreshCsrf()
                .then(() =>
                  setTokenStatus(
                    "Security token refreshed. You can retry your action.",
                  ),
                )
                .catch(() =>
                  setTokenStatus(
                    "Could not refresh security token. Please reload the page.",
                  ),
                )
                .finally(() => setTokenBusy(false));
            }}
          >
            Refresh security token
          </button>
          <p role="status">{tokenStatus}</p>
        </>
      )}
      {retry && (
        <button className="secondary" disabled={remaining > 0} onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}
export function PageHeading({
  eyebrow,
  title,
  children,
  action,
  level = 1,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  level?: 1 | 2;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (level === 1) heading.current?.focus({ preventScroll: true });
  }, [title, level]);
  const Heading = level === 1 ? "h1" : "h2";
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <Heading className="page-title" ref={heading} tabIndex={-1}>
          {title}
        </Heading>
        {children && <p className="lede">{children}</p>}
      </div>
      {action}
    </div>
  );
}
export function Pager({
  next,
  cursor,
  setCursor,
}: {
  next: string | null | undefined;
  cursor: string;
  setCursor: (cursor: string) => void;
}) {
  return (
    <div className="pager">
      {cursor && (
        <button className="secondary" onClick={() => setCursor("")}>
          First page
        </button>
      )}
      {next && (
        <button className="secondary" onClick={() => setCursor(next)}>
          Next page <span aria-hidden="true">→</span>
        </button>
      )}
    </div>
  );
}
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  busy,
  onConfirm,
  onClose,
}: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  busy: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef(
    document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null,
  );
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    return () => {
      if (element.open) element.close();
      if (opener.current?.isConnected) opener.current.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      aria-labelledby="dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
    >
      <h2 id="dialog-title">{title}</h2>
      <p>{children}</p>
      <div className="actions">
        <button
          className="secondary"
          disabled={busy}
          autoFocus
          onClick={onClose}
        >
          Keep it
        </button>
        <button className="danger" disabled={busy} onClick={onConfirm}>
          {busy ? "Working…" : confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
export function Breadcrumb({
  to,
  children,
}: {
  to: string;
  children: ReactNode;
}) {
  return (
    <Link className="back-link" to={to}>
      <span aria-hidden="true">←</span> {children}
    </Link>
  );
}
