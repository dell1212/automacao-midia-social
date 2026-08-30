import { apiErrorStatus } from "../lib/apiClient";

/**
 * Renders a mutation/query error as user-facing text, with 409 given its own
 * message when the caller has one. 401 renders nothing — the session-expired
 * screen (App.tsx's Gate) already takes over the whole app for that case, so
 * a "tente novamente" underneath it would be exactly the wrong advice.
 */
export function ErrorText({
  error,
  fallback,
  conflict,
}: {
  error: unknown;
  fallback: string;
  conflict?: string;
}) {
  if (!error) return null;

  const status = apiErrorStatus(error);
  if (status === 401) return null;
  if (status === 409 && conflict) return <p>{conflict}</p>;

  return <p>{fallback}</p>;
}
