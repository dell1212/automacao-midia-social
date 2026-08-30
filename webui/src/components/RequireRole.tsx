import type { ReactNode } from "react";
import { useSession } from "../context/SessionProvider";

export function RequireRole({
  role,
  children,
  fallback,
}: {
  role: "admin" | "member";
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const { session } = useSession();

  if (session?.role !== role) {
    return <>{fallback ?? <p>Acesso restrito a administradores.</p>}</>;
  }

  return <>{children}</>;
}
