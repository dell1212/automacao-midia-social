import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiClient, onUnauthorized, setToken } from "../lib/apiClient";

interface UserSessionRead {
  tenant_id: number;
  tenant_name: string;
  user_id: string;
  role: "admin" | "member";
  name: string | null;
}

type SessionStatus = "waiting" | "loading" | "ready" | "error";

interface SessionContextValue {
  status: SessionStatus;
  session: UserSessionRead | null;
  canApprove: () => boolean;
}

const SessionContext = createContext<SessionContextValue | undefined>(undefined);

const PARENT_ORIGIN = import.meta.env.VITE_PARENT_ORIGIN as string | undefined;
const WAIT_TIMEOUT_MS = 15000;

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>("waiting");
  const [session, setSession] = useState<UserSessionRead | null>(null);
  const queryClient = useQueryClient();

  // Separate from the handshake effect below: this must register even when
  // the handshake bails out early (no VITE_PARENT_ORIGIN), and a 401 from any
  // page's query or mutation — not just the handshake's own session fetch —
  // has to reach here. apiClient has already dropped the dead token by the
  // time this fires.
  useEffect(() => {
    return onUnauthorized(() => {
      setSession(null);
      setStatus("error");
      // The QueryClient outlives this remount (it's created above <App/>), so
      // without this a token later issued for a different user in the same
      // tab would still show the previous tenant's cached lists.
      queryClient.clear();
    });
  }, [queryClient]);

  useEffect(() => {
    if (!PARENT_ORIGIN) {
      setStatus("error");
      return;
    }

    const timeout = setTimeout(() => {
      setStatus((current) => (current === "waiting" ? "error" : current));
    }, WAIT_TIMEOUT_MS);

    async function handleMessage(event: MessageEvent) {
      if (event.origin !== PARENT_ORIGIN) return;
      if (event.data?.type !== "session" || typeof event.data.token !== "string") return;

      clearTimeout(timeout);
      setStatus("loading");
      setToken(event.data.token);

      try {
        const result = await apiClient.get<UserSessionRead>("/content/ui/session");
        setSession(result);
        setStatus("ready");
      } catch {
        // A network error or 5xx here is not a 401, so onUnauthorized never
        // fires — but the token is just as dead, so drop it the same way.
        setToken(null);
        setStatus("error");
      }
    }

    window.addEventListener("message", handleMessage);
    window.parent.postMessage({ type: "ready" }, PARENT_ORIGIN);

    return () => {
      window.removeEventListener("message", handleMessage);
      clearTimeout(timeout);
    };
  }, []);

  const canApprove = () => session?.role === "admin";

  return (
    <SessionContext.Provider value={{ status, session, canApprove }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession must be used within a SessionProvider");
  return context;
}
