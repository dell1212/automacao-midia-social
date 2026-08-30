import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import { ApiError } from "./lib/apiClient";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // The default of 3 retries turns an expired session or a rejected
      // request into four identical calls before the UI says anything. A 4xx
      // will not change on its own, so only retry what might: once.
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status < 500) return false;
        return failureCount < 1;
      },
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>
);
