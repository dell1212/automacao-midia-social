import type { ReactNode } from "react";
import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import { SessionProvider, useSession } from "./context/SessionProvider";
import { AppShell } from "./components/AppShell";
import { EmptyState } from "./components/ui/Feedback";
import { Calendar } from "./pages/Calendar";
import { SocialAgent } from "./pages/SocialAgent";
import { Analytics } from "./pages/Analytics";
import { Composer } from "./pages/Composer";
import { PieceQueue } from "./pages/PieceQueue";
import { PieceDetail } from "./pages/PieceDetail";
import { Clients } from "./pages/config/Clients";
import { Campaigns } from "./pages/config/Campaigns";
import { SocialAccounts } from "./pages/config/SocialAccounts";
import { Avatars } from "./pages/config/Avatars";
import { ApprovalRules } from "./pages/config/ApprovalRules";
import { GenerationTemplates } from "./pages/config/GenerationTemplates";
import { Providers } from "./pages/config/Providers";
import { HistoryPage } from "./pages/History";

function GateMessage({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center justify-center min-h-svh p-6 text-[13px] text-[var(--text)]">
      {children}
    </div>
  );
}

function Gate({ children }: { children: ReactNode }) {
  const { status } = useSession();

  if (status === "waiting") return <GateMessage>Aguardando sessão do app mãe…</GateMessage>;
  if (status === "loading") return <GateMessage>Validando sessão…</GateMessage>;
  if (status === "error")
    return <GateMessage>Sessão expirada ou inválida. Feche e reabra este painel.</GateMessage>;

  return <>{children}</>;
}

function NotFound() {
  return (
    <EmptyState
      title="Página não encontrada"
      hint="O endereço acessado não existe neste painel."
      action={
        <Link
          to="/calendar"
          className="inline-flex items-center h-8 px-3.5 rounded-[4px] bg-lime text-ink text-[13px] font-medium no-underline hover:bg-lime-strong"
        >
          Ir para o calendário
        </Link>
      }
    />
  );
}

export function App() {
  return (
    <SessionProvider>
      <Gate>
        <BrowserRouter>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/calendar" element={<Calendar />} />
              <Route path="/agent" element={<SocialAgent />} />
              <Route path="/analytics" element={<Analytics />} />
              <Route path="/" element={<PieceQueue />} />
              <Route path="/pieces/:id" element={<PieceDetail />} />
              <Route path="/pieces/:id/compose" element={<Composer />} />
              <Route path="/config/clients" element={<Clients />} />
              <Route path="/config/campaigns" element={<Campaigns />} />
              <Route path="/config/social-accounts" element={<SocialAccounts />} />
              <Route path="/config/avatars" element={<Avatars />} />
              <Route path="/config/approval-rules" element={<ApprovalRules />} />
              <Route path="/config/templates" element={<GenerationTemplates />} />
              <Route path="/config/providers" element={<Providers />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </Gate>
    </SessionProvider>
  );
}
