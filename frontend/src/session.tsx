import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError, isAbort } from "./api/client";
import type { User } from "./api/models";

type Session = {
  user: User | null;
  loading: boolean;
  error: unknown;
  revision: number;
  restore: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};
const Context = createContext<Session | null>(null);
export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>();
  const [revision, setRevision] = useState(0);
  const current = useRef<User | null>(null);
  const sequence = useRef(0);
  const channel = useRef<BroadcastChannel | null>(null);
  const clear = useCallback(() => {
    current.current = null;
    setUser(null);
    setRevision((n) => n + 1);
  }, []);
  const restore = useCallback(async () => {
    const ticket = ++sequence.current;
    setLoading(true);
    setError(undefined);
    try {
      const next = await api.me();
      if (ticket !== sequence.current) return;
      if (
        current.current?.id !== next.id ||
        current.current?.role !== next.role
      ) {
        api.reset();
        setRevision((n) => n + 1);
      }
      current.current = next;
      setUser(next);
    } catch (failure) {
      if (ticket !== sequence.current || isAbort(failure)) return;
      api.reset();
      clear();
      if (!(failure instanceof ApiError && failure.status === 401))
        setError(failure);
    } finally {
      if (ticket === sequence.current) setLoading(false);
    }
  }, [clear]);
  useEffect(() => {
    api.onSessionLost = () => {
      ++sequence.current;
      clear();
      setLoading(false);
      setError(
        new ApiError(
          401,
          "AUTHENTICATION_REQUIRED",
          "Your session has ended. Please log in again.",
        ),
      );
    };
    void restore();
    const focus = () => {
      if (document.visibilityState === "visible") void restore();
    };
    window.addEventListener("focus", focus);
    if (typeof BroadcastChannel !== "undefined") {
      channel.current = new BroadcastChannel("csrs-session");
      channel.current.onmessage = () => {
        api.reset();
        clear();
        void restore();
      };
    }
    return () => {
      ++sequence.current;
      api.onSessionLost = undefined;
      window.removeEventListener("focus", focus);
      channel.current?.close();
      api.reset();
    };
  }, [restore, clear]);
  const login = async (email: string, password: string) => {
    await api.authenticate("login", email, password);
    await restore();
    channel.current?.postMessage("changed");
  };
  const logout = async () => {
    try {
      await api.logout();
    } catch (failure) {
      if (!(failure instanceof ApiError && failure.status === 401))
        throw failure;
    }
    ++sequence.current;
    clear();
    setError(undefined);
    setLoading(false);
    channel.current?.postMessage("changed");
  };
  return (
    <Context.Provider
      value={{ user, loading, error, revision, restore, login, logout }}
    >
      {children}
    </Context.Provider>
  );
}
export function useSession() {
  const value = useContext(Context);
  if (!value) throw new Error("SessionProvider missing");
  return value;
}
export function safeRedirect(value: string | null) {
  // Only known application destinations; never follow supplied schemes or protocol-relative URLs.
  return value &&
    /^\/(?:events\/[0-9a-f-]{36}|reservations(?:\/[0-9a-f-]{36})?|organizer(?:\/events\/(?:new|[0-9a-f-]{36}(?:\/edit)?))?)$/.test(
      value,
    )
    ? value
    : "/reservations";
}
