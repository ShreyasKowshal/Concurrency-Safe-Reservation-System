import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError, isAbort } from "../api/client";
import { ErrorNotice, Loading } from "../components/ui";
import { useActive } from "../hooks";
import { safeRedirect, useSession } from "../session";

export function Auth({ mode }: { mode: "login" | "register" }) {
  const active = useActive();
  const session = useSession();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const destination = safeRedirect(params.get("next"));
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const [ready, setReady] = useState(false);
  const [registered, setRegistered] = useState(false);
  useEffect(() => {
    if (session.loading || session.user) return;
    let active = true;
    void api
      .refreshCsrf()
      .then(() => {
        if (active) setReady(true);
      })
      .catch((failure) => {
        if (active && !isAbort(failure)) setError(failure);
      });
    return () => {
      active = false;
    };
  }, [session.loading, session.user]);
  if (session.loading) return <Loading label="Checking your session…" />;
  if (session.user) return <Navigate replace to={destination} />;
  const register = mode === "register";
  const fields = error instanceof ApiError ? error.fields : {};
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting.current) return;
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const values = new FormData(form);
    submitting.current = true;
    setBusy(true);
    setError(undefined);
    try {
      const email = String(values.get("email")).trim(),
        password = String(values.get("password"));
      if (register) {
        await api.authenticate("register", email, password);
        if (active.current) {
          form.reset();
          setRegistered(true);
        }
      } else {
        await session.login(email, password);
        if (active.current) navigate(destination, { replace: true });
      }
    } catch (failure) {
      if (active.current && !isAbort(failure)) setError(failure);
    } finally {
      submitting.current = false;
      if (active.current) setBusy(false);
    }
  };
  return (
    <div className="auth-layout">
      <aside className="auth-story">
        <span className="brand-mark large" aria-hidden="true">
          c.
        </span>
        <p className="eyebrow">Make room for something great</p>
        <h1>
          A seat at your
          <br />
          next big idea.
        </h1>
        <p>
          Discover workshops, meet new people, and turn a little curiosity into
          your next experience.
        </p>
        <div className="auth-note">
          One seat. A five-minute hold.
          <br />A clear confirmation from the server.
        </div>
      </aside>
      <section className="panel auth-panel">
        <p className="eyebrow">Your CSRS account</p>
        <h2>{register ? "Start exploring." : "Welcome back."}</h2>
        <p className="muted">
          {register
            ? "Create an attendee account to reserve your place."
            : "Log in to pick up where you left off."}
        </p>
        {registered ? (
          <div className="notice success" role="status">
            <h3>Account created</h3>
            <p>
              Registration does not sign you in. Log in with your new account to
              continue.
            </p>
            <Link
              className="button"
              to={`/login?next=${encodeURIComponent(destination)}`}
            >
              Continue to login
            </Link>
          </div>
        ) : (
          <form
            onSubmit={submit}
            aria-describedby={error ? "auth-feedback" : undefined}
          >
            <label htmlFor="email">Email address</label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              maxLength={254}
              aria-invalid={!!fields.email}
              aria-describedby={fields.email ? "email-error" : undefined}
            />
            {fields.email && (
              <small id="email-error" className="field-error">
                {fields.email}
              </small>
            )}
            <label htmlFor="password">Password</label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete={register ? "new-password" : "current-password"}
              minLength={register ? 15 : 1}
              maxLength={128}
              required
              aria-invalid={!!fields.password}
              aria-describedby={`password-help${fields.password ? " password-error" : ""}`}
            />
            {fields.password && (
              <small id="password-error" className="field-error">
                {fields.password}
              </small>
            )}
            <small id="password-help">
              {register
                ? "Use 15–128 characters. A memorable passphrase works well."
                : "Enter your account password."}
            </small>
            <div id="auth-feedback">
              <ErrorNotice
                error={error}
                retry={
                  !ready
                    ? () => {
                        setError(undefined);
                        void api
                          .refreshCsrf()
                          .then(() => setReady(true))
                          .catch(setError);
                      }
                    : undefined
                }
              />
            </div>
            <button className="full" disabled={busy || !ready}>
              {busy ? "Please wait…" : register ? "Create account" : "Log in"}
              <span aria-hidden="true"> →</span>
            </button>
          </form>
        )}
        <p className="auth-switch">
          {register ? "Already have an account?" : "New to CSRS?"}{" "}
          <Link
            to={`/${register ? "login" : "register"}?next=${encodeURIComponent(destination)}`}
          >
            {register ? "Log in" : "Create an account"}
          </Link>
        </p>
        <p className="fine-print">
          Organizer access is provisioned by a local administrator.
        </p>
      </section>
    </div>
  );
}
