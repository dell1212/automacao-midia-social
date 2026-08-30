export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// True for exactly the ApiError.status values apiClient can throw with a 401
// or 409, so callers can branch without importing ApiError themselves.
export function apiErrorStatus(error: unknown): number | null {
  return error instanceof ApiError ? error.status : null;
}

let currentToken: string | null = null;

export function setToken(token: string | null): void {
  currentToken = token;
}

// Every request funnels through here, so this is the one place a 401 can be
// observed for the whole SPA — including the session handshake itself, the
// only apiClient caller outside React Query. Subscribers are notified once
// per dead token: the sentToken check below means a straggler response from
// a token that has already been replaced can't fire this and wipe out a
// session that is otherwise fine.
const unauthorizedHandlers = new Set<() => void>();

export function onUnauthorized(handler: () => void): () => void {
  unauthorizedHandlers.add(handler);
  return () => unauthorizedHandlers.delete(handler);
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const sentToken = currentToken;
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      ...(sentToken ? { Authorization: `Bearer ${sentToken}` } : {}),
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
    },
  });

  if (response.status === 401 && sentToken !== null && sentToken === currentToken) {
    currentToken = null;
    unauthorizedHandlers.forEach((handler) => handler());
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, body.detail ?? response.statusText);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export const apiClient = {
  get: <T>(path: string): Promise<T> => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown): Promise<T> =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown): Promise<T> =>
    request<T>(path, { method: "PUT", body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown): Promise<T> =>
    request<T>(path, { method: "PATCH", body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string): Promise<T> => request<T>(path, { method: "DELETE" }),
  uploadFile: <T>(path: string, formData: FormData): Promise<T> =>
    request<T>(path, { method: "POST", body: formData }),
  setToken,
};
